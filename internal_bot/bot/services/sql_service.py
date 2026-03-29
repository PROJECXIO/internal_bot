"""
SQL generation, validation, and read-only execution.

Safety rules (Phase 1):
- Only SELECT statements are allowed.
- INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, GRANT, REVOKE,
  EXEC, EXECUTE are blocked at both sqlparse and regex layers.
- Tables for blocked DocTypes are blocked by name.
- LIMIT is enforced before execution.
"""
import re
from typing import TYPE_CHECKING

import frappe

if TYPE_CHECKING:
	from internal_bot.bot.services.llm_client import LLMClient

# Patterns that must never appear in SQL (even in subqueries)
_BLOCKED_KEYWORDS_RE = re.compile(
	r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|EXEC|EXECUTE|REPLACE|LOAD\s+DATA|INTO\s+OUTFILE)\b",
	re.IGNORECASE,
)

_LIMIT_RE = re.compile(r"\bLIMIT\s+\d+", re.IGNORECASE)
_SQL_FENCE_RE = re.compile(r"```(?:sql)?\s*([\s\S]*?)```", re.IGNORECASE)


# ------------------------------------------------------------------
# SQL Generation
# ------------------------------------------------------------------


def generate_sql(
	question: str,
	schema_context: str,
	memory_context: str,
	llm_client: "LLMClient",
	attempt: int = 0,
	previous_error: str | None = None,
) -> str:
	"""
	Build a prompt and call the LLM to generate a SELECT SQL statement.
	Returns the raw SQL string (Markdown fences stripped).
	"""
	system_prompt = (
		"You are an expert SQL generator for a Frappe/ERPNext MariaDB database.\n"
		"Rules:\n"
		"1. Generate only SELECT queries — never INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE.\n"
		"2. Frappe table names follow the pattern: tab{DocTypeName}  "
		"(e.g. 'Sales Invoice' → `tabSales Invoice`, 'Customer' → `tabCustomer`).\n"
		"3. Column names match Frappe field names exactly (snake_case).\n"
		"4. Always include a LIMIT clause (max 100 rows).\n"
		"5. Output ONLY the raw SQL — no explanation, no Markdown fences.\n"
		"6. If the question is ambiguous, generate the most reasonable interpretation.\n"
		"7. Use table aliases for readability.\n"
		"8. For date-based queries, today = CURDATE().\n"
	)

	user_parts = []

	if memory_context:
		user_parts.append(f"## Conversation Summary\n{memory_context}\n")

	if schema_context:
		user_parts.append(f"## Available Schema\n{schema_context}\n")

	user_parts.append(f"## Question\n{question}")

	if attempt > 0 and previous_error:
		user_parts.append(
			f"\n## Previous Attempt (attempt {attempt}) Failed\n"
			f"Error: {previous_error}\n"
			"Please fix the SQL and try again."
		)

	messages = [
		{"role": "system", "content": system_prompt},
		{"role": "user", "content": "\n".join(user_parts)},
	]

	raw = llm_client.chat_completion(messages)
	return _extract_sql(raw)


def _extract_sql(raw: str) -> str:
	"""Strip Markdown fences and leading/trailing whitespace."""
	match = _SQL_FENCE_RE.search(raw)
	if match:
		return match.group(1).strip()
	return raw.strip()


# ------------------------------------------------------------------
# SQL Validation
# ------------------------------------------------------------------


def validate_sql(sql: str, blocked_doctypes: list | None = None) -> tuple[bool, str]:
	"""
	Validate that the SQL is a safe SELECT statement.
	Returns (is_valid: bool, reason: str).
	"""
	if not sql or not sql.strip():
		return False, "Empty SQL"

	# Layer 1: sqlparse statement type check
	try:
		import sqlparse

		parsed = sqlparse.parse(sql)
		if not parsed:
			return False, "Could not parse SQL"

		stmt_type = parsed[0].get_type()
		if stmt_type != "SELECT":
			return False, f"Only SELECT queries are allowed. Detected: {stmt_type or 'UNKNOWN'}"
	except ImportError:
		pass  # Fall through to regex check if sqlparse not available

	# Layer 2: regex scan for blocked keywords (catches subqueries too)
	match = _BLOCKED_KEYWORDS_RE.search(sql)
	if match:
		return False, f"Blocked keyword detected: {match.group(0).upper()}"

	# Layer 3: blocked DocType table name check
	if blocked_doctypes:
		for dt in blocked_doctypes:
			table_name = f"tab{dt}"
			if re.search(rf"\b{re.escape(table_name)}\b", sql, re.IGNORECASE):
				return False, f"Access to '{dt}' data is restricted"

	return True, ""


# ------------------------------------------------------------------
# SQL Execution
# ------------------------------------------------------------------


def execute_sql_readonly(sql: str, max_rows: int = 100) -> list[dict]:
	"""
	Execute a validated SELECT query via frappe.db.sql.
	Enforces LIMIT before execution.  Returns list of row dicts.
	"""
	sql = _enforce_limit(sql, max_rows)

	try:
		rows = frappe.db.sql(sql, as_dict=True)
		# Convert frappe Row objects to plain dicts for JSON serialization
		return [dict(r) for r in rows]
	except Exception as exc:
		frappe.throw(str(exc))


def _enforce_limit(sql: str, max_rows: int) -> str:
	"""Append LIMIT clause if absent or replace if it exceeds max_rows."""
	if not _LIMIT_RE.search(sql):
		# Strip trailing semicolons before appending
		sql = sql.rstrip("; \t\n")
		return f"{sql}\nLIMIT {max_rows}"

	# Replace existing LIMIT if it's larger than max_rows
	def _cap_limit(m: re.Match) -> str:
		current = int(re.search(r"\d+", m.group(0)).group(0))
		capped = min(current, max_rows)
		return f"LIMIT {capped}"

	return _LIMIT_RE.sub(_cap_limit, sql)
