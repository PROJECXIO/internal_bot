"""
Level 3 — Graph integration tests using a MockLLMClient.

Run with bench:
  bench --site <site> run-tests --app internal_bot --module internal_bot.tests.test_graph
"""
import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import MagicMock, patch

from internal_bot.bot.graph import get_graph, reset_graph
from internal_bot.bot.state import GraphState

_TEST_USER = "Administrator"
_TEST_SESSION = _TEST_USER


def _make_mock_llm(responses: list[str]):
	"""Return a mock LLMClient that returns `responses` in sequence."""
	client = MagicMock()
	client.provider = "MockLLM"
	client.model = "mock-model"
	client.last_input_tokens = 10
	client.last_output_tokens = 20

	import itertools
	_iter = iter(responses)

	def _side_effect(messages, temperature=0.0, max_tokens=2000):
		try:
			return next(_iter)
		except StopIteration:
			return responses[-1]  # Repeat last response

	client.chat_completion.side_effect = _side_effect
	return client


def _make_mock_settings(
	memory_window=10,
	summary_threshold=20,
	enable_cache=False,  # disable cache for most tests
	max_result_rows=100,
	cache_ttl_hours=24,
	blocked_doctypes_str="",
):
	settings = MagicMock()
	settings.memory_window = memory_window
	settings.summary_threshold = summary_threshold
	settings.enable_cache = enable_cache
	settings.max_result_rows = max_result_rows
	settings.cache_ttl_hours = cache_ttl_hours
	settings.get_blocked_doctype_list.return_value = (
		[d.strip() for d in blocked_doctypes_str.splitlines() if d.strip()]
	)
	return settings


def _base_state(raw_message: str, llm_client=None, settings=None, debug=False) -> dict:
	import time
	return {
		"user": _TEST_USER,
		"raw_message": raw_message,
		"session_name": _TEST_SESSION,
		"debug": debug,
		"max_rows": 100,
		"start_time": time.monotonic(),
		"node_trace": [],
		"timing": {},
		"sql_generation_attempts": 0,
		"retries": 0,
		"cache_hit": False,
		"input_tokens": 0,
		"output_tokens": 0,
		"result_row_count": 0,
		"_llm_client": llm_client,
		"_settings": settings or _make_mock_settings(),
	}


class TestGraphIntegration(FrappeTestCase):
	def setUp(self):
		# Ensure the test session exists
		if not frappe.db.exists("AI Chat Session", _TEST_SESSION):
			frappe.get_doc({
				"doctype": "AI Chat Session",
				"name": _TEST_SESSION,
				"user": _TEST_USER,
				"is_active": 1,
				"total_messages": 0,
			}).insert(ignore_permissions=True)
			frappe.db.commit()

	def tearDown(self):
		frappe.db.delete("AI Chat Message", {"session": _TEST_SESSION})
		frappe.db.set_value("AI Chat Session", _TEST_SESSION, "total_messages", 0)
		frappe.db.commit()
		reset_graph()

	# ── Blocked intent ────────────────────────────────────────────────

	def test_salary_question_is_blocked(self):
		"""Questions with 'salary' keyword must be blocked without LLM call."""
		llm = _make_mock_llm(["should not be called"])
		state = _base_state("show me employee salaries", llm_client=llm)

		graph = get_graph()
		result = graph.invoke(state)
		response = result["formatted_response"]

		self.assertEqual(response["status"], "blocked")

	# ── Successful query ──────────────────────────────────────────────

	def test_simple_query_returns_success(self):
		"""A valid question with valid SQL should return status: success."""
		# LLM responses: intent classification → SQL generation
		intent_response = '{"intent": "query", "normalized_question": "show all customers", "reason": "", "clarification_options": []}'
		sql_response = "SELECT name, customer_name FROM `tabCustomer` LIMIT 10"

		llm = _make_mock_llm([intent_response, sql_response])
		state = _base_state("show all customers", llm_client=llm)

		graph = get_graph()

		with patch("internal_bot.bot.services.sql_service.execute_sql_readonly") as mock_exec:
			mock_exec.return_value = [{"name": "CUST-001", "customer_name": "Acme Corp"}]
			result = graph.invoke(state)

		response = result["formatted_response"]
		self.assertEqual(response["status"], "success")
		self.assertEqual(len(response["rows"]), 1)
		self.assertIn("name", response["columns"])

	# ── Node trace ────────────────────────────────────────────────────

	def test_node_trace_contains_all_nodes_for_successful_query(self):
		intent_response = '{"intent": "query", "normalized_question": "show customers", "reason": "", "clarification_options": []}'
		sql_response = "SELECT name FROM `tabCustomer` LIMIT 10"

		llm = _make_mock_llm([intent_response, sql_response])
		state = _base_state("show customers", llm_client=llm)

		graph = get_graph()

		with patch("internal_bot.bot.services.sql_service.execute_sql_readonly") as mock_exec:
			mock_exec.return_value = []
			result = graph.invoke(state)

		trace = result["node_trace"]
		for expected in ["intent_parser", "memory_loader", "schema_discovery",
		                 "cache_check", "sql_generator", "sql_validator",
		                 "sql_executor", "result_formatter", "analytics"]:
			self.assertIn(expected, trace, f"Expected '{expected}' in node_trace: {trace}")

	# ── Retry logic ───────────────────────────────────────────────────

	def test_invalid_sql_triggers_retries_then_error(self):
		"""LLM returns invalid SQL 3 times → response status should be error."""
		intent_response = '{"intent": "query", "normalized_question": "update something", "reason": "", "clarification_options": []}'
		bad_sql = "UPDATE `tabCustomer` SET name = 'x'"  # always blocked

		llm = _make_mock_llm([intent_response] + [bad_sql] * 5)
		state = _base_state("update something", llm_client=llm)

		graph = get_graph()
		result = graph.invoke(state)

		response = result["formatted_response"]
		self.assertEqual(response["status"], "error")
		self.assertGreaterEqual(result.get("sql_generation_attempts", 0), 3)

	# ── Debug output ──────────────────────────────────────────────────

	def test_debug_flag_adds_debug_section(self):
		intent_response = '{"intent": "query", "normalized_question": "show customers", "reason": "", "clarification_options": []}'
		sql_response = "SELECT name FROM `tabCustomer` LIMIT 5"

		llm = _make_mock_llm([intent_response, sql_response])
		state = _base_state("show customers", llm_client=llm, debug=True)

		graph = get_graph()

		with patch("internal_bot.bot.services.sql_service.execute_sql_readonly") as mock_exec:
			mock_exec.return_value = []
			result = graph.invoke(state)

		response = result["formatted_response"]
		self.assertIn("debug", response)
		debug = response["debug"]
		self.assertIn("node_trace", debug)
		self.assertIn("timing", debug)
		self.assertIn("cache_hit", debug)
