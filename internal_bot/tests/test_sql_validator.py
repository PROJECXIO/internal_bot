"""
Level 1 — Pure unit tests for sql_service.validate_sql and execute helpers.

Run without Frappe context:
  cd /home/frappeuser/frappe-bench-v15/apps/internal_bot
  /home/frappeuser/frappe-bench-v15/env/bin/pytest internal_bot/tests/test_sql_validator.py -v
"""
import sys
import os

# Allow running standalone (without bench context)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

import pytest
from internal_bot.bot.services.sql_service import validate_sql, _enforce_limit, _extract_sql


# ──────────────────────────────────────────────────────────────────
# validate_sql — allowed queries
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


# ──────────────────────────────────────────────────────────────────
# validate_sql — blocked statements
# ──────────────────────────────────────────────────────────────────

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
		# Attacker tries to embed DELETE in a subquery comment trick
		sql = "SELECT 1; DELETE FROM `tabCustomer`"
		is_valid, reason = validate_sql(sql)
		assert not is_valid

	def test_blocks_insert_in_comment_like_position(self):
		sql = "SELECT * FROM `tabCustomer` WHERE name = 'x' -- INSERT INTO foo VALUES (1)"
		# The comment contains INSERT — regex should still catch it
		# (This is intentionally strict for Phase 1)
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
# _enforce_limit helper
# ──────────────────────────────────────────────────────────────────

class TestEnforceLimit:
	def test_adds_limit_when_absent(self):
		sql = "SELECT name FROM `tabCustomer`"
		result = _enforce_limit(sql, 100)
		assert "LIMIT 100" in result

	def test_keeps_limit_when_within_max(self):
		sql = "SELECT name FROM `tabCustomer` LIMIT 20"
		result = _enforce_limit(sql, 100)
		assert "LIMIT 20" in result

	def test_caps_limit_when_exceeds_max(self):
		sql = "SELECT name FROM `tabCustomer` LIMIT 500"
		result = _enforce_limit(sql, 100)
		assert "LIMIT 100" in result
		assert "LIMIT 500" not in result

	def test_strips_semicolon_before_adding_limit(self):
		sql = "SELECT name FROM `tabCustomer`;"
		result = _enforce_limit(sql, 50)
		assert result.endswith("LIMIT 50")
		assert ";" not in result


# ──────────────────────────────────────────────────────────────────
# _extract_sql helper
# ──────────────────────────────────────────────────────────────────

class TestExtractSql:
	def test_extracts_from_sql_fence(self):
		raw = "```sql\nSELECT name FROM `tabCustomer` LIMIT 10\n```"
		assert _extract_sql(raw) == "SELECT name FROM `tabCustomer` LIMIT 10"

	def test_extracts_from_plain_fence(self):
		raw = "```\nSELECT 1\n```"
		assert _extract_sql(raw) == "SELECT 1"

	def test_returns_raw_if_no_fence(self):
		raw = "SELECT name FROM `tabCustomer`"
		assert _extract_sql(raw) == raw

	def test_strips_whitespace(self):
		raw = "  SELECT 1  "
		assert _extract_sql(raw) == "SELECT 1"
