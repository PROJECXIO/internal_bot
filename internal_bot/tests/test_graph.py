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
		"query_generation_attempts": 0,
		"retries": 0,
		"cache_hit": False,
		"input_tokens": 0,
		"output_tokens": 0,
		"result_row_count": 0,
		"_llm_client": llm_client,
		"_settings": settings or _make_mock_settings(),
	}


# JSON responses for the query_planner's LLM call
_LIST_INTENT = '{"mode": "list", "doctype": "Customer", "fields": ["name", "customer_name"], "filters": [], "order_by": "creation desc", "limit": 10}'
_ANALYTICS_INTENT = '{"mode": "analytics", "primary_doctype": "Sales Invoice", "joins": [], "dimensions": [], "metrics": [{"func": "SUM", "field": "grand_total", "alias": "total_sales"}], "filters": [], "limit": 1}'


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
		"""A valid question with a valid intent should return status: success."""
		intent_response = '{"intent": "query", "normalized_question": "show all customers", "reason": "", "clarification_options": []}'

		llm = _make_mock_llm([intent_response, _LIST_INTENT])
		state = _base_state("show all customers", llm_client=llm)

		graph = get_graph()

		with patch("internal_bot.bot.nodes.query_planner.query_executor") as mock_qe, \
		     patch("internal_bot.bot.nodes.query_planner.permission_service") as mock_perm:
			mock_perm.check_doctype_read_access.return_value = True
			mock_qe.execute_query_intent.return_value = (
				[{"name": "CUST-001", "customer_name": "Acme Corp"}], None
			)
			result = graph.invoke(state)

		response = result["formatted_response"]
		self.assertEqual(response["status"], "success")
		self.assertEqual(len(response["rows"]), 1)
		self.assertIn("name", response["columns"])
		self.assertEqual(response["response_type"], "table")

	# ── Node trace ────────────────────────────────────────────────────

	def test_node_trace_contains_all_nodes_for_successful_query(self):
		intent_response = '{"intent": "query", "normalized_question": "show customers", "reason": "", "clarification_options": []}'

		llm = _make_mock_llm([intent_response, _LIST_INTENT])
		state = _base_state("show customers", llm_client=llm)

		graph = get_graph()

		with patch("internal_bot.bot.nodes.query_planner.query_executor") as mock_qe, \
		     patch("internal_bot.bot.nodes.query_planner.permission_service") as mock_perm:
			mock_perm.check_doctype_read_access.return_value = True
			mock_qe.execute_query_intent.return_value = ([], None)
			result = graph.invoke(state)

		trace = result["node_trace"]
		for expected in ["intent_classifier", "memory_loader", "schema_discovery",
		                 "query_planner", "result_formatter", "analytics"]:
			self.assertIn(expected, trace, f"Expected '{expected}' in node_trace: {trace}")

		# Old nodes must not appear
		for removed in ["sql_generator", "sql_validator", "sql_executor"]:
			self.assertNotIn(removed, trace, f"Removed node '{removed}' should not be in trace")

	# ── Retry logic ───────────────────────────────────────────────────

	def test_invalid_intent_triggers_retries_then_error(self):
		"""LLM returns unparseable responses 3 times → response status should be error."""
		intent_response = '{"intent": "query", "normalized_question": "show customers", "reason": "", "clarification_options": []}'
		# Non-JSON response: _parse_intent will raise ValueError → triggers retry
		bad_response = "UPDATE `tabCustomer` SET name = 'x'"

		llm = _make_mock_llm([intent_response] + [bad_response] * 5)
		state = _base_state("show customers", llm_client=llm)

		graph = get_graph()
		result = graph.invoke(state)

		response = result["formatted_response"]
		self.assertEqual(response["status"], "error")
		self.assertGreaterEqual(result.get("query_generation_attempts", 0), 3)

	# ── Debug output ──────────────────────────────────────────────────

	def test_debug_flag_adds_debug_section(self):
		intent_response = '{"intent": "query", "normalized_question": "show customers", "reason": "", "clarification_options": []}'

		llm = _make_mock_llm([intent_response, _LIST_INTENT])
		state = _base_state("show customers", llm_client=llm, debug=True)

		graph = get_graph()

		with patch("internal_bot.bot.nodes.query_planner.query_executor") as mock_qe, \
		     patch("internal_bot.bot.nodes.query_planner.permission_service") as mock_perm:
			mock_perm.check_doctype_read_access.return_value = True
			mock_qe.execute_query_intent.return_value = ([], None)
			result = graph.invoke(state)

		response = result["formatted_response"]
		self.assertIn("debug", response)
		debug = response["debug"]
		self.assertIn("node_trace", debug)
		self.assertIn("timing", debug)
		self.assertIn("cache_hit", debug)
		self.assertIn("generated_intent", debug)
		self.assertIn("compiled_sql", debug)

	def test_single_value_query_returns_metric_card_response(self):
		intent_response = '{"intent": "query", "normalized_question": "show total sales", "reason": "", "clarification_options": []}'

		llm = _make_mock_llm([intent_response, _ANALYTICS_INTENT])
		state = _base_state("show total sales", llm_client=llm)

		graph = get_graph()

		with patch("internal_bot.bot.nodes.query_planner.query_executor") as mock_qe, \
		     patch("internal_bot.bot.nodes.query_planner.permission_service") as mock_perm:
			mock_perm.check_doctype_read_access.return_value = True
			mock_qe.execute_query_intent.return_value = (
				[{"total_sales": 125000}], "SELECT SUM(...)"
			)
			result = graph.invoke(state)

		response = result["formatted_response"]
		self.assertEqual(response["response_type"], "metric_card")
		self.assertEqual(response["visualization"]["kind"], "metric")

	def test_execution_error_retries_with_error_context(self):
		"""Execution error on first attempt → retry succeeds → status success."""
		intent_response = '{"intent": "query", "normalized_question": "show invoice totals", "reason": "", "clarification_options": []}'
		query_intent = '{"mode": "list", "doctype": "Sales Invoice", "fields": ["name", "posting_date"], "filters": [], "limit": 10}'

		llm = _make_mock_llm([intent_response, query_intent, query_intent])
		state = _base_state("show invoice totals", llm_client=llm)

		graph = get_graph()

		with patch("internal_bot.bot.nodes.query_planner.query_executor") as mock_qe, \
		     patch("internal_bot.bot.nodes.query_planner.permission_service") as mock_perm:
			mock_perm.check_doctype_read_access.return_value = True
			mock_qe.execute_query_intent.side_effect = [
				Exception('(1054, "Unknown column \'pi.posting_dateAS\' in \'SELECT\'")'),
				([{"posting_date": "2026-03-29"}], None),
			]
			result = graph.invoke(state)

		response = result["formatted_response"]
		self.assertEqual(response["status"], "success")
		self.assertEqual(response["rows"][0]["posting_date"], "2026-03-29")
		self.assertGreaterEqual(result.get("query_generation_attempts", 0), 1)

		# Verify that the error context was passed to the retry LLM call
		last_prompt = llm.chat_completion.call_args_list[-1].args[0][1]["content"]
		self.assertIn("Unknown column", last_prompt)

	def test_permission_error_does_not_retry(self):
		"""PermissionError must force give_up immediately (no retry)."""
		intent_response = '{"intent": "query", "normalized_question": "show purchase orders", "reason": "", "clarification_options": []}'
		query_intent = '{"mode": "list", "doctype": "Purchase Order", "fields": ["name"], "filters": [], "limit": 10}'

		llm = _make_mock_llm([intent_response, query_intent])
		state = _base_state("show purchase orders", llm_client=llm)

		graph = get_graph()

		with patch("internal_bot.bot.nodes.query_planner.query_executor") as mock_qe, \
		     patch("internal_bot.bot.nodes.query_planner.permission_service") as mock_perm:
			mock_perm.check_doctype_read_access.return_value = True
			mock_qe.execute_query_intent.side_effect = frappe.PermissionError(
				"Access denied to DocType 'Purchase Order'."
			)
			result = graph.invoke(state)

		response = result["formatted_response"]
		self.assertEqual(response["status"], "error")
		# query_generation_attempts must be MAX_RETRIES (forced give_up, not incremental)
		from internal_bot.bot.nodes.query_planner import _MAX_RETRIES
		self.assertEqual(result.get("query_generation_attempts", 0), _MAX_RETRIES)
		# Only 2 LLM calls: intent parser + 1 planning attempt (no retry)
		self.assertEqual(llm.chat_completion.call_count, 2)
