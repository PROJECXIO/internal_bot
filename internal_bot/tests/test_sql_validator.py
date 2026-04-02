"""
Level 1 — Pure unit tests for sql_service.

Run without Frappe context:
  cd /home/frappeuser/frappe-bench-v15/apps/internal_bot
  /home/frappeuser/frappe-bench-v15/env/bin/pytest internal_bot/tests/test_sql_validator.py -v
"""
import sys
import os
from unittest.mock import MagicMock

# Allow running standalone (without bench context)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

import pytest
from internal_bot.bot.services.sql_service import validate_sql, _extract_json_block, generate_query_intent


# ──────────────────────────────────────────────────────────────────
# validate_sql — defense-in-depth checks (still used by compiler)
# ──────────────────────────────────────────────────────────────────

class TestValidateSqlAllowed:
	def test_simple_select(self):
		is_valid, reason = validate_sql("SELECT name FROM `tabCustomer` LIMIT 10")
		assert is_valid, reason

	def test_select_with_join(self):
		sql = """
		SELECT si.name, si.customer, si.grand_total
		FROM `tabSales Invoice` si
		JOIN `tabCustomer` c ON c.name = si.customer
		WHERE si.docstatus = 1
		LIMIT 50
		"""
		is_valid, reason = validate_sql(sql)
		assert is_valid, reason

	def test_select_with_where_and_order(self):
		sql = "SELECT name, posting_date, grand_total FROM `tabSales Invoice` WHERE posting_date = CURDATE() ORDER BY grand_total DESC LIMIT 20"
		is_valid, reason = validate_sql(sql)
		assert is_valid, reason

	def test_select_aggregate(self):
		sql = "SELECT COUNT(*) AS total, SUM(grand_total) AS revenue FROM `tabSales Invoice` WHERE docstatus = 1 LIMIT 1"
		is_valid, reason = validate_sql(sql)
		assert is_valid, reason

	def test_select_subquery_in_where(self):
		sql = "SELECT name FROM `tabCustomer` WHERE name IN (SELECT customer FROM `tabSales Invoice` WHERE docstatus = 1) LIMIT 10"
		is_valid, reason = validate_sql(sql)
		assert is_valid, reason


class TestValidateSqlBlocked:
	def test_blocks_insert(self):
		is_valid, reason = validate_sql("INSERT INTO `tabCustomer` (name) VALUES ('test')")
		assert not is_valid
		assert "INSERT" in reason.upper() or "SELECT" in reason.upper()

	def test_blocks_update(self):
		is_valid, reason = validate_sql("UPDATE `tabCustomer` SET customer_name = 'x' WHERE name = 'y'")
		assert not is_valid

	def test_blocks_delete(self):
		is_valid, reason = validate_sql("DELETE FROM `tabCustomer` WHERE name = 'x'")
		assert not is_valid

	def test_blocks_drop(self):
		is_valid, reason = validate_sql("DROP TABLE `tabCustomer`")
		assert not is_valid

	def test_blocks_alter(self):
		is_valid, reason = validate_sql("ALTER TABLE `tabCustomer` ADD COLUMN foo VARCHAR(100)")
		assert not is_valid

	def test_blocks_truncate(self):
		is_valid, reason = validate_sql("TRUNCATE TABLE `tabCustomer`")
		assert not is_valid

	def test_blocks_create(self):
		is_valid, reason = validate_sql("CREATE TABLE foo (id INT)")
		assert not is_valid

	def test_blocks_grant(self):
		is_valid, reason = validate_sql("GRANT ALL ON *.* TO 'user'@'%'")
		assert not is_valid

	def test_blocks_exec(self):
		is_valid, reason = validate_sql("EXEC sp_something")
		assert not is_valid

	def test_blocks_empty_sql(self):
		is_valid, reason = validate_sql("")
		assert not is_valid
		assert "Empty" in reason

	def test_blocks_none_sql(self):
		is_valid, reason = validate_sql(None)
		assert not is_valid

	def test_blocks_subquery_with_delete(self):
		sql = "SELECT 1; DELETE FROM `tabCustomer`"
		is_valid, reason = validate_sql(sql)
		assert not is_valid

	def test_blocks_insert_in_comment_like_position(self):
		sql = "SELECT * FROM `tabCustomer` WHERE name = 'x' -- INSERT INTO foo VALUES (1)"
		is_valid, reason = validate_sql(sql)
		assert not is_valid

	def test_blocks_blocked_doctype_table(self):
		sql = "SELECT * FROM `tabSalary Slip` LIMIT 10"
		is_valid, reason = validate_sql(sql, blocked_doctypes=["Salary Slip"])
		assert not is_valid
		assert "Salary Slip" in reason

	def test_blocked_doctype_case_insensitive(self):
		sql = "SELECT * FROM `tabsalary slip` LIMIT 10"
		is_valid, reason = validate_sql(sql, blocked_doctypes=["Salary Slip"])
		assert not is_valid


# ──────────────────────────────────────────────────────────────────
# _extract_json_block helper
# ──────────────────────────────────────────────────────────────────

class TestExtractJsonBlock:
	def test_extracts_from_json_fence(self):
		raw = '```json\n{"mode": "list"}\n```'
		assert _extract_json_block(raw) == '{"mode": "list"}'

	def test_extracts_from_plain_fence(self):
		raw = '```\n{"mode": "analytics"}\n```'
		assert _extract_json_block(raw) == '{"mode": "analytics"}'

	def test_returns_raw_if_no_fence(self):
		raw = '{"mode": "list", "doctype": "Customer"}'
		assert _extract_json_block(raw) == raw

	def test_strips_whitespace(self):
		raw = '  {"mode": "list"}  '
		assert _extract_json_block(raw) == '{"mode": "list"}'


# ──────────────────────────────────────────────────────────────────
# generate_query_intent — LLM call + JSON parsing
# ──────────────────────────────────────────────────────────────────

def _mock_llm(response: str) -> MagicMock:
	client = MagicMock()
	client.chat_completion.return_value = response
	client.last_input_tokens = 5
	client.last_output_tokens = 10
	return client


class TestGenerateQueryIntent:
	def test_returns_valid_list_intent(self):
		raw = '{"mode": "list", "doctype": "Customer", "fields": ["name"], "filters": [], "limit": 10}'
		llm = _mock_llm(raw)
		intent = generate_query_intent("show customers", "", "", llm)
		assert intent["mode"] == "list"
		assert intent["doctype"] == "Customer"

	def test_returns_valid_analytics_intent(self):
		raw = '{"mode": "analytics", "primary_doctype": "Sales Invoice", "dimensions": ["customer"], "metrics": [{"func": "SUM", "field": "grand_total", "alias": "total"}], "filters": [], "limit": 20}'
		llm = _mock_llm(raw)
		intent = generate_query_intent("total sales by customer", "", "", llm)
		assert intent["mode"] == "analytics"
		assert intent["primary_doctype"] == "Sales Invoice"

	def test_strips_markdown_fences(self):
		raw = '```json\n{"mode": "list", "doctype": "Customer", "fields": ["name"], "filters": [], "limit": 5}\n```'
		llm = _mock_llm(raw)
		intent = generate_query_intent("show customers", "", "", llm)
		assert intent["mode"] == "list"

	def test_raises_on_non_json(self):
		llm = _mock_llm("SELECT name FROM tabCustomer LIMIT 10")
		with pytest.raises(ValueError, match="not valid JSON"):
			generate_query_intent("show customers", "", "", llm)

	def test_raises_on_wrong_mode(self):
		raw = '{"mode": "sql", "query": "SELECT 1"}'
		llm = _mock_llm(raw)
		with pytest.raises(ValueError, match="mode"):
			generate_query_intent("show customers", "", "", llm)

	def test_raises_if_list_mode_missing_doctype(self):
		raw = '{"mode": "list", "fields": ["name"], "filters": [], "limit": 10}'
		llm = _mock_llm(raw)
		with pytest.raises(ValueError, match="doctype"):
			generate_query_intent("show customers", "", "", llm)

	def test_raises_if_analytics_mode_missing_metrics(self):
		raw = '{"mode": "analytics", "primary_doctype": "Sales Invoice", "dimensions": ["customer"], "filters": []}'
		llm = _mock_llm(raw)
		with pytest.raises(ValueError, match="metrics"):
			generate_query_intent("total sales", "", "", llm)

	def test_retry_context_added_when_attempt_gt_zero(self):
		raw = '{"mode": "list", "doctype": "Customer", "fields": ["name"], "filters": [], "limit": 10}'
		llm = _mock_llm(raw)
		generate_query_intent("show customers", "", "", llm, attempt=1, previous_error="DB error")
		call_args = llm.chat_completion.call_args
		user_message = call_args[0][0][1]["content"]
		assert "DB error" in user_message
		assert "attempt 1" in user_message.lower() or "previous attempt" in user_message.lower()

	def test_passes_trace_context_to_llm_when_provided(self):
		raw = '{"mode": "list", "doctype": "Customer", "fields": ["name"], "filters": [], "limit": 10}'
		llm = _mock_llm(raw)
		generate_query_intent(
			"show customers",
			"",
			"",
			llm,
			trace_metadata={"node": "query_planner"},
			trace_tags=["internal_bot", "llm"],
		)
		assert llm.chat_completion.call_args.kwargs["trace_metadata"] == {"node": "query_planner"}
		assert llm.chat_completion.call_args.kwargs["trace_tags"] == ["internal_bot", "llm"]
