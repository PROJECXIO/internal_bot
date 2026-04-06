"""
Level 3 — Graph integration tests using a MockLLMClient.

Run with bench:
  bench --site <site> run-tests --app internal_bot --module internal_bot.tests.test_graph
"""
import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import MagicMock, patch

from internal_bot.bot.graph import get_graph, reset_graph
from internal_bot.bot.services.doctype_aliases import invalidate_alias_cache
from internal_bot.bot.services.hybrid_scorer import ScoredCandidate
from internal_bot.bot.services.schema_corpus import invalidate_corpus_cache
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

	def _side_effect(messages, temperature=0.0, max_tokens=2000, **kwargs):
		try:
			return next(_iter)
		except StopIteration:
			return responses[-1]  # Repeat last response

	client.chat_completion.side_effect = _side_effect
	client.create_embeddings.return_value = None
	return client


def _make_mock_settings(
	memory_window=10,
	summary_threshold=20,
	enable_cache=False,  # disable cache for most tests
	enable_debug_context_window=False,
	max_result_rows=100,
	cache_ttl_hours=24,
	blocked_doctypes_str="",
):
	settings = MagicMock()
	settings.memory_window = memory_window
	settings.summary_threshold = summary_threshold
	settings.enable_cache = enable_cache
	settings.enable_debug_context_window = enable_debug_context_window
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
_VIZ_TEXT = "{\"visualization\": \"text\", \"prefix\": \"Here's what I found:\"}"
_VIZ_BAR = "{\"visualization\": \"bar\", \"prefix\": \"Here's the breakdown:\"}"
_ANSWER_MARKDOWN = "This is the markdown answer."
_ANSWER_MARKDOWN_AR = "هذا هو الرد النهائي."


class TestGraphIntegration(FrappeTestCase):
	TEST_SITE = "ai"

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
		frappe.db.delete(
			"AI DocType Alias",
			{"alias": ["in", ["فاتورة مبيعات", "عميل", "invoices", "مبيعات"]]},
		)
		frappe.db.commit()
		invalidate_alias_cache()
		invalidate_corpus_cache()
		reset_graph()

	def _ensure_alias(self, doctype_name: str, alias: str, language: str):
		if frappe.db.exists("AI DocType Alias", {"doctype_name": doctype_name, "alias": alias}):
			return
		frappe.get_doc(
			{
				"doctype": "AI DocType Alias",
				"doctype_name": doctype_name,
				"alias": alias,
				"language": language,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		invalidate_alias_cache()
		invalidate_corpus_cache()

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

		llm = _make_mock_llm([intent_response, _LIST_INTENT, _VIZ_TEXT, _ANSWER_MARKDOWN])
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
		self.assertEqual(response["response_type"], "plain_text")
		self.assertEqual(response["markdown"], _ANSWER_MARKDOWN)

	def test_arabic_query_keeps_arabic_across_successful_response(self):
		self._ensure_alias("Customer", "العملاء", "ar")
		intent_response = (
			'{"intent": "query", "normalized_question": "اعرض كل العملاء", '
			'"detected_language": "ar", "reason": "", "clarification_options": []}'
		)
		viz_response = '{"visualization": "text", "prefix": "إليك ما وجدته:"}'

		llm = _make_mock_llm([intent_response, _LIST_INTENT, viz_response, _ANSWER_MARKDOWN_AR])
		state = _base_state("اعرض كل العملاء", llm_client=llm)

		graph = get_graph()

		with patch("internal_bot.bot.nodes.query_planner.query_executor") as mock_qe, \
		     patch("internal_bot.bot.nodes.query_planner.permission_service") as mock_perm:
			mock_perm.check_doctype_read_access.return_value = True
			mock_qe.execute_query_intent.return_value = (
				[{"name": "CUST-001", "customer_name": "Acme Corp"}], None
			)
			result = graph.invoke(state)

		response = result["formatted_response"]
		self.assertEqual(result["response_language"], "ar")
		self.assertEqual(response["status"], "success")
		self.assertEqual(response["answer_prefix"], "إليك ما وجدته:")
		self.assertEqual(response["markdown"], _ANSWER_MARKDOWN_AR)

	# ── Node trace ────────────────────────────────────────────────────

	def test_node_trace_contains_all_nodes_for_successful_query(self):
		intent_response = '{"intent": "query", "normalized_question": "show customers", "reason": "", "clarification_options": []}'

		llm = _make_mock_llm([intent_response, _LIST_INTENT, _VIZ_TEXT, _ANSWER_MARKDOWN])
		state = _base_state("show customers", llm_client=llm)

		graph = get_graph()

		with patch("internal_bot.bot.nodes.query_planner.query_executor") as mock_qe, \
		     patch("internal_bot.bot.nodes.query_planner.permission_service") as mock_perm:
			mock_perm.check_doctype_read_access.return_value = True
			mock_qe.execute_query_intent.return_value = ([], None)
			result = graph.invoke(state)

		trace = result["node_trace"]
		for expected in ["intent_classifier", "memory_loader", "schema_discovery",
		                 "query_planner", "visualization_planner", "answer_composer",
		                 "analytics"]:
			self.assertIn(expected, trace, f"Expected '{expected}' in node_trace: {trace}")
		self.assertNotIn("result_formatter", trace, f"Successful path should not hit result_formatter: {trace}")

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

		llm = _make_mock_llm([intent_response, _LIST_INTENT, _VIZ_TEXT, _ANSWER_MARKDOWN])
		state = _base_state(
			"show customers",
			llm_client=llm,
			settings=_make_mock_settings(enable_debug_context_window=True),
			debug=True,
		)

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
		self.assertIn("context_window", debug)
		self.assertIn("token_usage", debug)

	def test_debug_context_window_is_omitted_when_setting_disabled(self):
		intent_response = '{"intent": "query", "normalized_question": "show customers", "reason": "", "clarification_options": []}'

		llm = _make_mock_llm([intent_response, _LIST_INTENT, _VIZ_TEXT, _ANSWER_MARKDOWN])
		state = _base_state(
			"show customers",
			llm_client=llm,
			settings=_make_mock_settings(enable_debug_context_window=False),
			debug=True,
		)

		graph = get_graph()

		with patch("internal_bot.bot.nodes.query_planner.query_executor") as mock_qe, \
		     patch("internal_bot.bot.nodes.query_planner.permission_service") as mock_perm:
			mock_perm.check_doctype_read_access.return_value = True
			mock_qe.execute_query_intent.return_value = ([], None)
			result = graph.invoke(state)

		debug = result["formatted_response"]["debug"]
		self.assertNotIn("context_window", debug)
		self.assertNotIn("token_usage", debug)

	def test_single_value_query_returns_metric_card_response(self):
		intent_response = '{"intent": "query", "normalized_question": "show total sales", "reason": "", "clarification_options": []}'

		llm = _make_mock_llm([intent_response, _ANALYTICS_INTENT, _VIZ_BAR, _ANSWER_MARKDOWN])
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
		self.assertEqual(response["markdown"], _ANSWER_MARKDOWN)

	def test_execution_error_retries_with_error_context(self):
		"""Execution error on first attempt → retry succeeds → status success."""
		intent_response = '{"intent": "query", "normalized_question": "show invoice totals", "reason": "", "clarification_options": []}'
		query_intent = '{"mode": "list", "doctype": "Sales Invoice", "fields": ["name", "posting_date"], "filters": [], "limit": 10}'

		llm = _make_mock_llm([intent_response, query_intent, query_intent, _VIZ_TEXT, _ANSWER_MARKDOWN])
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
		last_prompt = llm.chat_completion.call_args_list[2].args[0][1]["content"]
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

	def test_follow_up_analysis_reuses_previous_result_context(self):
		frappe.get_doc(
			{
				"doctype": "AI Chat Message",
				"session": _TEST_SESSION,
				"user": _TEST_USER,
				"role": "user",
				"status": "success",
				"content": "total grand sales invoice per day",
				"normalized_question": "total grand sales invoice per day",
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "AI Chat Message",
				"session": _TEST_SESSION,
				"user": _TEST_USER,
				"role": "assistant",
				"status": "success",
				"content": "Returned 8 rows.",
				"structured_response": frappe.as_json(
					{
						"status": "success",
						"response_type": "bar_chart",
						"title": "Total grand sales invoice per day",
						"summary": "Returned 8 rows.",
						"columns": ["posting_date", "total_grand_sales"],
						"rows": [{"posting_date": "2025-09-16", "total_grand_sales": 229000}],
						"visualization": None,
						"markdown": "**2025-09-16** is highest at **229,000**.",
					}
				),
				"discovered_entities": frappe.as_json(["Sales Invoice"]),
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

		intent_response = '{"intent": "query", "normalized_question": "analysis this data more", "reason": "", "clarification_options": []}'
		query_intent = '{"mode": "analytics", "primary_doctype": "Sales Invoice", "joins": [], "dimensions": ["DATE(posting_date)"], "metrics": [{"func": "SUM", "field": "grand_total", "alias": "total_sales"}], "filters": [], "limit": 100}'
		llm = _make_mock_llm([query_intent, _VIZ_TEXT, _ANSWER_MARKDOWN])
		state = _base_state("analysis this data more", llm_client=llm)

		graph = get_graph()

		with patch("internal_bot.bot.nodes.query_planner.query_executor") as mock_qe, \
		     patch("internal_bot.bot.nodes.query_planner.permission_service") as mock_perm:
			mock_perm.check_doctype_read_access.return_value = True
			mock_qe.execute_query_intent.return_value = (
				[{"posting_date": "2025-09-16", "total_sales": 229000}], None
			)
			result = graph.invoke(state)

		self.assertTrue(result["follow_up_to_previous_result"])
		self.assertEqual(result["discovered_doctypes"], ["Sales Invoice"])
		self.assertEqual(result["formatted_response"]["status"], "success")
		self.assertEqual(result["formatted_response"]["markdown"], _ANSWER_MARKDOWN)
		self.assertEqual(result["formatted_response"]["response_type"], "plain_text")
		self.assertIsNone(result["formatted_response"]["visualization"])

	def test_short_ranking_follow_up_prefers_previous_doctype(self):
		frappe.get_doc(
			{
				"doctype": "AI Chat Message",
				"session": _TEST_SESSION,
				"user": _TEST_USER,
				"role": "user",
				"status": "success",
				"content": "can you compare total sales for each item",
				"normalized_question": "can you compare total sales for each item",
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "AI Chat Message",
				"session": _TEST_SESSION,
				"user": _TEST_USER,
				"role": "assistant",
				"status": "success",
				"content": "Returned 3 rows.",
				"structured_response": frappe.as_json(
					{
						"status": "success",
						"response_type": "bar_chart",
						"title": "Can you compare total sales for each item",
						"summary": "SKU004 leads.",
						"columns": ["item_code", "total_sales"],
						"rows": [{"item_code": "SKU004", "total_sales": 100000}],
						"visualization": None,
						"markdown": "**SKU004** leads with **100,000** total sales.",
					}
				),
				"discovered_entities": frappe.as_json(["Sales Invoice"]),
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

		query_intent = '{"mode": "analytics", "primary_doctype": "Sales Invoice", "joins": [], "dimensions": ["item_code"], "metrics": [{"func": "SUM", "field": "grand_total", "alias": "total_sales"}], "filters": [], "limit": 3}'
		llm = _make_mock_llm([query_intent, _VIZ_TEXT, _ANSWER_MARKDOWN])
		state = _base_state("top three items", llm_client=llm)

		graph = get_graph()

		with patch("internal_bot.bot.nodes.query_planner.query_executor") as mock_qe, \
		     patch("internal_bot.bot.nodes.query_planner.permission_service") as mock_perm:
			mock_perm.check_doctype_read_access.return_value = True
			mock_qe.execute_query_intent.return_value = (
				[{"item_code": "SKU004", "total_sales": 100000}], None
			)
			result = graph.invoke(state)

		self.assertTrue(result["follow_up_to_previous_result"])
		self.assertEqual(result["discovered_doctypes"], ["Sales Invoice"])
		self.assertEqual(result["formatted_response"]["status"], "success")

	def test_arabic_direct_alias_resolves_sales_invoice_without_embeddings(self):
		self._ensure_alias("Sales Invoice", "فاتورة مبيعات", "ar")
		intent_response = '{"intent": "query", "normalized_question": "فاتورة مبيعات", "reason": "", "clarification_options": []}'
		llm = _make_mock_llm([intent_response, _LIST_INTENT, _VIZ_TEXT, _ANSWER_MARKDOWN])
		state = _base_state("فاتورة مبيعات", llm_client=llm)
		graph = get_graph()

		with patch("internal_bot.bot.nodes.query_planner.query_executor") as mock_qe, \
		     patch("internal_bot.bot.nodes.query_planner.permission_service") as mock_perm:
			mock_perm.check_doctype_read_access.return_value = True
			mock_qe.execute_query_intent.return_value = ([{"name": "SINV-0001"}], None)
			result = graph.invoke(state)

		self.assertEqual(result["schema_decision"], "clear_winner")
		self.assertEqual(result["discovered_doctypes"], ["Sales Invoice"])
		self.assertEqual(result["formatted_response"]["status"], "success")

	def test_arabic_sales_keyword_alias_prefers_sales_invoice(self):
		self._ensure_alias("Sales Invoice", "مبيعات", "ar")
		intent_response = '{"intent": "query", "normalized_question": "المبيعات بالشهر", "reason": "", "clarification_options": []}'
		query_intent = '{"mode": "analytics", "primary_doctype": "Sales Invoice", "joins": [], "dimensions": ["MONTH(posting_date)"], "metrics": [{"func": "SUM", "field": "grand_total", "alias": "total_sales"}], "filters": [], "limit": 12}'
		llm = _make_mock_llm([intent_response, query_intent, _VIZ_TEXT, _ANSWER_MARKDOWN])
		state = _base_state("المبيعات بالشهر", llm_client=llm)
		graph = get_graph()

		with patch("internal_bot.bot.nodes.query_planner.query_executor") as mock_qe, \
		     patch("internal_bot.bot.nodes.query_planner.permission_service") as mock_perm:
			mock_perm.check_doctype_read_access.return_value = True
			mock_qe.execute_query_intent.return_value = ([{"month": "2026-04", "total_sales": 229000}], None)
			result = graph.invoke(state)

		self.assertEqual(result["schema_decision"], "clear_winner")
		self.assertEqual(result["discovered_doctypes"], ["Sales Invoice"])
		self.assertEqual(result["formatted_response"]["status"], "success")

	def test_arabic_indirect_alias_resolves_customer(self):
		self._ensure_alias("Customer", "عميل", "ar")
		intent_response = '{"intent": "query", "normalized_question": "كم عميل عندي", "reason": "", "clarification_options": []}'
		llm = _make_mock_llm([intent_response, _LIST_INTENT, _VIZ_TEXT, _ANSWER_MARKDOWN])
		state = _base_state("كم عميل عندي", llm_client=llm)
		graph = get_graph()

		with patch("internal_bot.bot.nodes.query_planner.query_executor") as mock_qe, \
		     patch("internal_bot.bot.nodes.query_planner.permission_service") as mock_perm:
			mock_perm.check_doctype_read_access.return_value = True
			mock_qe.execute_query_intent.return_value = ([{"name": "CUST-0001"}], None)
			result = graph.invoke(state)

		self.assertEqual(result["discovered_doctypes"], ["Customer"])
		self.assertEqual(result["formatted_response"]["status"], "success")

	def test_ambiguous_invoice_query_routes_to_clarification(self):
		self._ensure_alias("Sales Invoice", "invoices", "en")
		self._ensure_alias("Purchase Invoice", "invoices", "en")
		intent_response = '{"intent": "query", "normalized_question": "invoices", "reason": "", "clarification_options": []}'
		clarification_response = '{"ready": false, "question": "Which invoice type do you mean?", "options": ["Sales Invoice", "Purchase Invoice"]}'
		llm = _make_mock_llm([intent_response, clarification_response])
		state = _base_state("invoices", llm_client=llm)
		graph = get_graph()
		result = graph.invoke(state)

		self.assertEqual(result["schema_decision"], "ambiguous")
		self.assertEqual(result["formatted_response"]["status"], "clarification_needed")
		self.assertIn("Sales Invoice", result["formatted_response"]["options"])
		self.assertIn("Purchase Invoice", result["formatted_response"]["options"])

	def test_no_match_formatter_uses_ranked_candidates(self):
		intent_response = '{"intent": "query", "normalized_question": "thing from accounting", "reason": "", "clarification_options": []}'
		llm = _make_mock_llm([intent_response])
		state = _base_state("thing from accounting", llm_client=llm)
		graph = get_graph()

		with patch("internal_bot.bot.nodes.schema_discovery.hybrid_scorer.rank_candidates") as mock_rank, \
		     patch("internal_bot.bot.nodes.schema_discovery.hybrid_scorer.classify_confidence") as mock_classify:
			mock_rank.return_value = [
				ScoredCandidate("Journal Entry", 0.05, 0.0, 0.05, "weak overlap"),
				ScoredCandidate("Payment Entry", 0.04, 0.0, 0.04, "weak overlap"),
			]
			mock_classify.return_value = ("no_match", [])
			result = graph.invoke(state)

		self.assertEqual(result["formatted_response"]["status"], "clarification_needed")
		self.assertEqual(result["formatted_response"]["options"], ["Journal Entry", "Payment Entry"])
