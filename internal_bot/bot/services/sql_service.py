"""
Query intent generation and validation utilities.

The LLM no longer generates raw SQL — it generates a typed JSON intent
that the backend compiles into a permission-safe query.

generate_query_intent() — calls the LLM and returns a validated JSON dict
validate_sql()          — kept for defense-in-depth checks (analytics SQL)
"""
import datetime
import json
import re
from typing import TYPE_CHECKING

import frappe

if TYPE_CHECKING:
    from internal_bot.bot.services.llm_client import LLMClient

# Defense-in-depth: block dangerous SQL keywords even in compiler-generated SQL
_BLOCKED_KEYWORDS_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|EXEC|EXECUTE|REPLACE|LOAD\s+DATA|INTO\s+OUTFILE)\b",
    re.IGNORECASE,
)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)

_QUERY_INTENT_SYSTEM_PROMPT = """\
You are an expert data query planner for a Frappe/ERPNext MariaDB database.

Your task: Given a business question and a schema context, output a JSON query \
plan — NOT SQL.

## Output format

Output ONLY valid JSON — no SQL, no Markdown fences, no explanation.

Choose one of two modes based on the question:

### Mode "list"
Use when the question asks for specific records, documents, or a filtered list.
Examples: "show me open sales orders", "list customers added this week"

{
  "mode": "list",
  "doctype": "<DocType name from schema>",
  "fields": ["field1", "field2"],
  "filters": [["fieldname", "operator", "value"]],
  "order_by": "fieldname asc",
  "limit": 20
}

### Mode "analytics"
Use when the question requires aggregation: totals, counts, averages, or GROUP BY.
Examples: "total sales by customer this month", "how many invoices submitted today"

{
  "mode": "analytics",
  "primary_doctype": "<DocType name from schema>",
  "joins": [
    {
      "child_doctype": "<child DocType name>",
      "parent_link_field": "<fieldname in child that links to parent>",
      "join_type": "LEFT"
    }
  ],
  "dimensions": ["fieldname"],
  "metrics": [
    {"func": "SUM", "field": "fieldname", "alias": "total_amount"},
    {"func": "COUNT", "field": "*", "alias": "record_count"}
  ],
  "filters": [["fieldname", "operator", "value"]],
  "date_range": {
    "field": "fieldname",
    "preset": "this_month",
    "from_date": "YYYY-MM-DD",
    "to_date": "YYYY-MM-DD"
  },
  "order_by": "total_amount desc",
  "limit": 20
}

## Rules

1. Use ONLY DocTypes and fields listed in ## Available Schema below.
2. DocType names must match exactly (case-sensitive).
3. Field names must match exactly (snake_case as shown in schema).
4. Allowed filter operators: =, !=, >, <, >=, <=, like, in, not in, between, is
5. Allowed aggregate functions: SUM, COUNT, AVG, MAX, MIN, COUNT_DISTINCT
6. Allowed date presets (use ONLY inside date_range.preset): today, yesterday, \
this_week, this_month, last_month, this_year, last_30_days
7. limit must be ≤ 100.
8. joins list may be empty [].
9. date_range may be omitted entirely.
10. Output JSON only — no explanation, no SQL, no Markdown fences.
11. For submittable DocTypes (Sales Invoice, Purchase Invoice, Purchase Order, \
Sales Order, Stock Entry, Payment Entry, Journal Entry, Delivery Note, \
Purchase Receipt, etc.) ALWAYS add ["docstatus", "=", 1] to filters to \
include only submitted/confirmed records. The "docstatus" field is always \
available in the schema.
12. NEVER put date preset names (today, this_year, this_month, etc.) as values \
inside the filters array. Date presets belong ONLY in date_range.preset. \
For date filtering always use date_range, never a filter with a preset string.
13. Do NOT add date_range unless the user explicitly mentions a time period \
(e.g. "this month", "last year", "today", "in 2024"). If no period is \
mentioned, omit date_range entirely.
14. Do NOT add dimensions unless the user explicitly asks for a breakdown or \
grouping (e.g. "by customer", "per month", "grouped by"). For a plain \
total or count with no grouping requested, leave dimensions as [].
15. When the question starts with "total" or "count" followed by a DocType name \
(e.g. "total sales invoice", "count purchase orders"), ALWAYS use analytics \
mode. "Total" means the user wants an aggregate number, not a list of records. \
Use COUNT(*) if the question does not specify a numeric field, or SUM(field) \
if a specific amount field is implied.
16. For time-based grouping ("per year", "per month", "per day", "per week"), \
use date extraction functions in dimensions: YEAR(fieldname), MONTH(fieldname), \
YEAR_MONTH(fieldname), DAY(fieldname), DATE(fieldname), WEEK(fieldname). The inner field must be a \
valid date field from the schema (e.g. "per year" → "YEAR(posting_date)"). \
For monthly grouping across open-ended or multi-year data, prefer YEAR_MONTH(fieldname) \
so months from different years stay separate.
17. NEVER include SQL table names, backticks, or SQL expressions like \
`tabSales Invoice`.grand_total in fields, dimensions, filters, or date_range.field. \
For the primary DocType, use plain field names: "grand_total", "customer", "posting_date". \
NEVER prefix primary DocType fields with the DocType name (wrong: "Sales Invoice.grand_total"). \
NEVER reference DocTypes that are not the primary or in the joins list (wrong: "Customer.customer_name").
18. For ERPNext child tables (like Sales Invoice Item), if you need line-item data, \
add a join with {"child_doctype": "...", "parent_link_field": "parent", "join_type": "LEFT"}. \
NEVER use a child table as the primary_doctype/doctype — always use the parent DocType \
(e.g. "Sales Invoice") and JOIN the child table. ONLY child-table fields need a DocType \
prefix (e.g. "Sales Invoice Item.item_code", "Sales Invoice Item.qty"). \
Primary DocType fields must always be plain names without prefix.
19. Child-table link fields "parent", "parenttype", and "parentfield" are valid even \
if they are not shown in the schema table.
"""


def generate_query_intent(
    question: str,
    schema_context: str,
    memory_context: str,
    llm_client: "LLMClient",
    current_date: str | None = None,
    current_day_name: str | None = None,
    current_year: int | None = None,
    attempt: int = 0,
    previous_error: str | None = None,
    trace_metadata: dict | None = None,
    trace_tags: list[str] | None = None,
) -> dict:
    """
    Call the LLM and return a validated JSON query intent dict.

    The LLM produces a typed JSON structure (ListIntent or AnalyticsIntent),
    never raw SQL.  The backend compiles the intent into a permission-safe query.

    Raises:
        ValueError — if the LLM response cannot be parsed as valid JSON,
                     or if the parsed dict is missing required fields.
                     The raw response is attached to the error for retry context.
    """
    user_parts = []

    if memory_context:
        user_parts.append(f"## Conversation Context\n{memory_context}\n")

    if schema_context:
        user_parts.append(f"## Available Schema\n{schema_context}\n")

    resolved_date = current_date or frappe.utils.nowdate()
    resolved_year = current_year or datetime.date.today().year
    resolved_day_name = current_day_name or frappe.utils.get_datetime().strftime("%A")
    user_parts.append(f"## Current Date\n{resolved_date}")
    user_parts.append(f"## Current Day\n{resolved_day_name}")
    user_parts.append(f"## Current Year\n{resolved_year}")
    user_parts.append(f"## Question\n{question}")

    if attempt > 0 and previous_error:
        user_parts.append(
            f"\n## Previous Attempt (attempt {attempt}) Failed\n"
            f"Error: {previous_error}\n"
            "Please fix your JSON and try again. Output JSON only."
        )

    messages = [
        {"role": "system", "content": _QUERY_INTENT_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]

    raw = llm_client.chat_completion(
        messages,
        trace_metadata=trace_metadata,
        trace_tags=trace_tags,
    )
    return _parse_intent(raw)


def _parse_intent(raw: str) -> dict:
    """Parse and validate the LLM's JSON response into an intent dict."""
    cleaned = _extract_json_block(raw)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        repaired = _repair_json_like_string(cleaned)
        if repaired != cleaned:
            try:
                data = json.loads(repaired)
            except json.JSONDecodeError:
                raise ValueError(
                    f"LLM response was not valid JSON: {exc}\nRaw response: {raw!r}"
                ) from exc
        else:
            raise ValueError(
                f"LLM response was not valid JSON: {exc}\nRaw response: {raw!r}"
            ) from exc

    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object, got {type(data).__name__}. Raw: {raw!r}")

    mode = data.get("mode")
    if mode not in ("list", "analytics"):
        raise ValueError(
            f"Intent 'mode' must be 'list' or 'analytics', got {mode!r}. Raw: {raw!r}"
        )

    if mode == "list" and not data.get("doctype"):
        raise ValueError(f"List intent missing 'doctype'. Raw: {raw!r}")

    if mode == "analytics" and not data.get("primary_doctype"):
        raise ValueError(f"Analytics intent missing 'primary_doctype'. Raw: {raw!r}")

    if mode == "analytics" and not data.get("metrics"):
        raise ValueError(f"Analytics intent missing 'metrics'. Raw: {raw!r}")

    return _normalize_time_dimensions(data)

def _extract_json_block(raw: str) -> str:
    """Strip Markdown fences and whitespace from the LLM response."""
    match = _JSON_FENCE_RE.search(raw)
    if match:
        return match.group(1).strip()
    return raw.strip()


def _repair_json_like_string(raw: str) -> str:
    """Repair minor JSON-like issues from LLM output before giving up."""
    cleaned = (raw or "").strip()
    if not cleaned:
        return cleaned

    object_start = cleaned.find("{")
    object_end = cleaned.rfind("}")
    if object_start != -1 and object_end != -1 and object_start < object_end:
        cleaned = cleaned[object_start : object_end + 1]

    cleaned = (
        cleaned.replace("“", '"')
        .replace("”", '"')
        .replace("‘", "'")
        .replace("’", "'")
    )
    cleaned = re.sub(r"/\*[\s\S]*?\*/", "", cleaned)
    cleaned = re.sub(r"(^|\s)//.*?$", r"\1", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    cleaned = re.sub(r'([{\[,]\s*)([A-Za-z_][A-Za-z0-9_()\-]*)(\s*:)', r'\1"\2"\3', cleaned)
    cleaned = re.sub(
        r"'([^'\\]*(?:\\.[^'\\]*)*)'",
        lambda match: '"' + match.group(1).replace('"', '\\"') + '"',
        cleaned,
    )
    return cleaned.strip()


_MONTH_DIM_RE = re.compile(r"^MONTH\((.+)\)$", re.IGNORECASE)
_YEAR_DIM_RE = re.compile(r"^YEAR\((.+)\)$", re.IGNORECASE)
_YEAR_MONTH_DIM_RE = re.compile(r"^YEAR_MONTH\((.+)\)$", re.IGNORECASE)


def _normalize_time_dimensions(intent: dict) -> dict:
    """Prevent month buckets from collapsing across different years."""
    if intent.get("mode") != "analytics":
        return intent

    dimensions = intent.get("dimensions") or []
    if not dimensions:
        return intent

    year_fields = {
        match.group(1).strip()
        for dim in dimensions
        if (match := _YEAR_DIM_RE.match(dim or ""))
    }
    year_month_fields = {
        match.group(1).strip()
        for dim in dimensions
        if (match := _YEAR_MONTH_DIM_RE.match(dim or ""))
    }

    normalized_dimensions = []
    changed = False
    for dim in dimensions:
        month_match = _MONTH_DIM_RE.match(dim or "")
        if not month_match:
            normalized_dimensions.append(dim)
            continue

        field = month_match.group(1).strip()
        if field in year_fields or field in year_month_fields:
            normalized_dimensions.append(dim)
            continue

        normalized_dimensions.append(f"YEAR_MONTH({field})")
        changed = True

    if not changed:
        return intent

    normalized_intent = dict(intent)
    normalized_intent["dimensions"] = normalized_dimensions
    return normalized_intent


# ------------------------------------------------------------------
# Defense-in-depth: SQL validation (used by query_compiler as a
# secondary check on compiler-generated analytics SQL)
# ------------------------------------------------------------------


def validate_sql(sql: str, blocked_doctypes: list | None = None) -> tuple[bool, str]:
    """
    Validate that a SQL string is a safe SELECT statement.
    Returns (is_valid: bool, reason: str).

    This is a secondary defense check.  The primary permission gates are
    in permission_service.py.
    """
    if not sql or not sql.strip():
        return False, "Empty SQL"

    # Layer 1: sqlparse statement type check
    try:
        import sqlparse  # noqa: PLC0415

        parsed = sqlparse.parse(sql)
        if not parsed:
            return False, "Could not parse SQL"

        stmt_type = parsed[0].get_type()
        if stmt_type != "SELECT":
            return False, f"Only SELECT queries are allowed. Detected: {stmt_type or 'UNKNOWN'}"
    except ImportError:
        pass  # Fall through to regex check if sqlparse not available

    # Layer 2: regex scan for blocked keywords
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
