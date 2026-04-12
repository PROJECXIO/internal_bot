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
Use when the question requires aggregation (totals, counts, averages, GROUP BY) OR
when the question needs data from child tables (e.g. Sales Invoice Item, Purchase
Order Item). frappe.get_list() (list mode) cannot access child table fields.
Examples: "total sales by customer this month", "how many invoices submitted today",
"show me the items in this invoice", "what did the customer buy"

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

### Mode "analytics" with rank_by_primary_dimension
Use for "top-X and their Y" questions — when the user wants top items/customers/products
ranked by their TOTAL metric (across all values of a secondary dimension), then wants
to see which secondary entities (suppliers, sales reps, warehouses, etc.) are associated.

Examples:
- "top purchased items and their suppliers" → rank items by total purchase amount, show each supplier
- "top selling SKUs and who sold them" → rank items by total sales, show each sales rep
- "top customers and their sales reps" → rank customers by total, show reps

Key: grouping by (item, supplier) and ordering by the pair's amount is WRONG — it ranks
pairs, not items. Use rank_by_primary_dimension=true instead:

{
  "mode": "analytics",
  "rank_by_primary_dimension": true,
  "primary_doctype": "<DocType>",
  "joins": [...],
  "dimensions": ["<primary ranking field>", "<secondary detail field>"],
  "metrics": [{"func": "SUM", "field": "...", "alias": "total_amount"}],
  "filters": [...],
  "limit": 20
}

The backend generates a CTE that ranks the first dimension by the first metric's total,
then the main query shows all secondary dimension values for only the top-ranked primaries.
The order_by field is ignored when rank_by_primary_dimension=true — ordering is always by
the primary dimension's total descending.

### Cross-table joins with join_on
When the join key comes from ANOTHER joined table (not the primary DocType's name), use
"join_on" in the join spec. This generates: ON child.parent_link = OtherTable.field.

CRITICAL — "Item Supplier" vs Purchase Invoice for supplier data:
  "Item Supplier" is the item MASTER's registered supplier list. It is NOT real transaction
  data. NEVER use it to answer "which suppliers supplied our top selling items".
  To find ACTUAL suppliers of sold items, join Purchase Invoice data instead:

Example — "top selling items and their actual suppliers":
  1. Sales Invoice Item: get item_code + sales amount (ranked by sales)
  2. Purchase Invoice Item: match by item_code (cross-join, parent_link_field="item_code")
  3. Purchase Invoice: get supplier field (join via Purchase Invoice Item.parent)

{
  "mode": "analytics",
  "rank_by_primary_dimension": true,
  "primary_doctype": "Sales Invoice",
  "joins": [
    {"child_doctype": "Sales Invoice Item", "parent_link_field": "parent", "join_type": "LEFT"},
    {"child_doctype": "Purchase Invoice Item", "parent_link_field": "item_code",
     "join_on": "Sales Invoice Item.item_code", "join_type": "LEFT"},
    {"child_doctype": "Purchase Invoice", "parent_link_field": "name",
     "join_on": "Purchase Invoice Item.parent", "join_type": "LEFT"}
  ],
  "dimensions": ["Sales Invoice Item.item_code", "Purchase Invoice.supplier"],
  "metrics": [{"func": "SUM", "field": "Sales Invoice Item.amount", "alias": "total_sales"}],
  "filters": [["docstatus", "=", 1]],
  "limit": 20
}

CRITICAL: For Sales Invoice line items ALWAYS use "Sales Invoice Item" — NEVER "Packed Item".

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
19. CRITICAL: Child table fields and JOINs are ONLY valid in "analytics" mode. \
NEVER use "list" mode when you need to access child table fields (item_code, qty, amount, \
item_name, or any field from a child DocType). If the query requires any child table field, \
you MUST use "analytics" mode. \
For a FLAT ITEM LISTING (e.g. "show me the items in this invoice", "what did they buy"): \
use analytics mode with dimensions = [child table fields] and metrics = [] (empty). \
This returns each row as-is without grouping. \
For AGGREGATION (e.g. "total sales per item"): use analytics mode with both dimensions and metrics. \
frappe.get_list() cannot handle child table field prefixes — using "list" mode with \
child table fields will cause a runtime error.
20. Child-table link fields "parent", "parenttype", and "parentfield" are valid even \
if they are not shown in the schema table.
21. In "list" mode, ALL filter field names must be plain parent DocType field names \
(e.g. "customer", "posting_date"). NEVER use dotted notation like "items.item_code" \
or "Sales Invoice Item.item_code" as a filter field in list mode — this will silently \
return wrong results. If you need to filter by a child table field, use "analytics" mode.
22. The ## Presentation Plan (Advisory) section, when present, is only a planning hint. \
The user's question and available schema override it. Never use fields or DocTypes that \
are not present in the schema context. If the plan says metric/card, prefer one aggregate \
with no dimensions unless the user explicitly asks for a grouping such as "by", "per", \
"each", "breakdown", or "grouped". Ignore dimension_hints for metric/card plans; those \
hints may identify business context, not GROUP BY fields. If it says time_series/line/area, \
include a date or time dimension and a metric when the schema supports it. If it says \
category_comparison/bar, include one category dimension and one metric. If it says \
composition/donut/pie, produce category plus metric data with a small limit. If it says \
stacked_composition/stacked_bar, use two dimensions plus one metric only when the user \
asks for a two-level breakdown. If it says matrix/heatmap, use two categorical dimensions \
plus one metric when the schema supports it. For item/SKU/product movement or sales per customer, \
including Arabic phrasing like "حركة الاصناف عند كل عميل", prefer two dimensions \
(customer + item/SKU/product) plus one metric when the schema supports it, but do not \
override the user's explicit request. \
If it says record_list/lookup/table/text, do not force \
aggregation.
23. For "top X and their Y" questions — where the user wants primary entities \
(items, customers, suppliers) ranked by their TOTAL metric across ALL values of a \
secondary dimension, then wants to see which secondary entities are associated — \
set "rank_by_primary_dimension": true. \
The first dimension must be the primary ranking entity (e.g. item_code), \
the second must be the secondary detail (e.g. supplier). \
NEVER use a plain (item, supplier) GROUP BY with order_by for this pattern — that \
ranks pairs, not items, and gives wrong results when one item has multiple suppliers.
24. When the join key comes from another already-joined table (not the primary DocType's \
name), use join_on. CRITICAL: NEVER use "Item Supplier" to find actual suppliers of sold \
items — "Item Supplier" is item master data, NOT transaction data. \
For "top selling items and their ACTUAL suppliers": \
  primary_doctype="Sales Invoice", \
  joins=[Sales Invoice Item (parent_link_field="parent"), \
         Purchase Invoice Item (parent_link_field="item_code", join_on="Sales Invoice Item.item_code"), \
         Purchase Invoice (parent_link_field="name", join_on="Purchase Invoice Item.parent")], \
  dimension: "Purchase Invoice.supplier". \
For "top purchased items and their suppliers": \
  primary_doctype="Purchase Invoice", \
  joins=[Purchase Invoice Item (parent_link_field="parent")], \
  dimension: "supplier" (on the Purchase Invoice itself). \
NEVER use "Packed Item" for line items — always use "Sales Invoice Item" or "Purchase Invoice Item".
"""


def generate_query_intent(
    question: str,
    schema_context: str,
    memory_context: str,
    llm_client: "LLMClient",
    current_date: str | None = None,
    current_day_name: str | None = None,
    current_year: int | None = None,
    presentation_plan: dict | None = None,
    join_plan: dict | None = None,
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
    if presentation_plan:
        user_parts.append(
            "## Presentation Plan (Advisory)\n"
            f"{json.dumps(_compact_presentation_plan(presentation_plan), ensure_ascii=True)}"
        )
    if join_plan and join_plan.get("primary_doctype"):
        user_parts.append(
            "## Pre-planned Join Architecture (FOLLOW THIS EXACTLY)\n"
            f"{json.dumps(join_plan, ensure_ascii=False)}\n"
            "Use this join plan as the basis for your intent. "
            "Do NOT change the primary_doctype or joins listed here. "
            "Fill in dimensions, metrics, filters, and limit to answer the question."
        )
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

    # Query intent JSON can be complex (multiple joins, dimensions, filters).
    # Enforce a minimum to avoid truncated responses when the global setting is low.
    _MIN_QUERY_PLANNER_TOKENS = 1500
    effective_max_tokens = max(llm_client.max_tokens, _MIN_QUERY_PLANNER_TOKENS)

    raw = llm_client.chat_completion(
        messages,
        max_tokens=effective_max_tokens,
        trace_metadata=trace_metadata,
        trace_tags=trace_tags,
    )
    intent = _parse_intent(raw)
    return _apply_presentation_plan_to_intent(intent, presentation_plan, question)


def _compact_presentation_plan(plan: dict) -> dict:
    if not isinstance(plan, dict):
        return {}
    allowed_keys = (
        "visualization",
        "query_shape",
        "dimension_hints",
        "metric_hints",
        "limit_hint",
        "reason",
    )
    return {key: plan.get(key) for key in allowed_keys if plan.get(key) not in (None, "", [])}


def _apply_presentation_plan_to_intent(
    intent: dict,
    presentation_plan: dict | None,
    question: str,
) -> dict:
    """Apply narrow, safe shape constraints from the advisory presentation plan."""
    if not isinstance(presentation_plan, dict):
        return intent

    visualization = str(presentation_plan.get("visualization") or "").lower()
    query_shape = str(presentation_plan.get("query_shape") or "").lower()
    if visualization != "card" and query_shape != "metric":
        return intent
    if _question_requests_grouping(question):
        return intent
    if intent.get("mode") != "analytics" or not intent.get("dimensions"):
        return intent

    normalized_intent = dict(intent)
    normalized_intent["dimensions"] = []
    return normalized_intent


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

    # metrics may be empty [] for flat child-table listing (no aggregation)
    if mode == "analytics" and data.get("metrics") is None:
        raise ValueError(f"Analytics intent missing 'metrics' key. Raw: {raw!r}")

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
_GROUPING_REQUEST_RE = re.compile(
    r"\b(by|per|each|every|breakdown|group(?:ed|ing)?|compare|comparison)\b|حسب|لكل",
    re.IGNORECASE,
)


def _question_requests_grouping(question: str) -> bool:
    return bool(_GROUPING_REQUEST_RE.search(question or ""))


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
