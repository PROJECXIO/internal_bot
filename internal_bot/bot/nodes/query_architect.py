"""
Node: Query Architect

Sits between presentation_planner and query_planner.

Purpose: determine WHICH DocTypes and join paths are needed to answer the question
before the query_planner tries to generate the intent JSON.

This separation prevents the query_planner from hallucinating wrong joins
(e.g. using "Packed Item" instead of "Sales Invoice Item", or missing a cross-domain
join like Item Supplier when the question asks about suppliers of sold items).

The node makes one focused LLM call that outputs a join plan, then fetches schema
for any additional DocTypes not already in context. The enriched schema_context and
join_plan are passed to query_planner so it can generate the correct intent.

Failure is non-fatal: if the LLM call fails or returns garbage, the node passes
through the existing state unchanged and query_planner falls back to its own judgment.
"""
import json
import re
import time

import frappe

from internal_bot.bot.services import schema as schema_svc, schema_corpus
from internal_bot.bot.state import GraphState
from internal_bot.bot import progress, trace

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)

_SYSTEM_PROMPT = """\
You are a database schema architect for Frappe/ERPNext (MariaDB backend).

Given a business question and the primary discovered schema, decide EXACTLY which \
DocTypes and JOIN paths are needed to answer the question completely.

Output ONLY valid JSON — no explanation, no markdown fences:
{
  "primary_doctype": "<exact DocType name>",
  "joins": [
    {
      "child_doctype": "<DocType name>",
      "parent_link_field": "<field on child that links to parent>",
      "join_type": "LEFT",
      "join_on": "<optional — only for cross-domain joins>"
    }
  ]
}

Rules:
1. Only include DocTypes genuinely needed for the answer (dimensions, metrics, or filters).
2. joins are ORDERED — a later join may reference an earlier one in join_on.
3. For child tables of the primary DocType (e.g. Sales Invoice Item, Purchase Invoice Item):
   parent_link_field = "parent", omit join_on.
4. For cross-domain joins where the key comes from another joined table, use join_on:
   join_on = "<AlreadyJoinedDocType>.<fieldname>"
5. Do NOT add joins for DocTypes whose fields are not needed to answer the question.
6. If only the primary DocType is needed, output joins: [].
7. For Sales Invoice line items ALWAYS use "Sales Invoice Item", NEVER "Packed Item".
8. For Purchase Invoice line items ALWAYS use "Purchase Invoice Item".

CRITICAL — supplier info for sold/top-selling items:
  "Item Supplier" is the item MASTER's registered supplier list — NOT real transactions.
  NEVER use "Item Supplier" when the question asks which suppliers actually supplied
  the top selling items.  Instead, join Purchase Invoice data:
    Step 1: Sales Invoice Item  (get item_code + sales amount from sales side)
    Step 2: Purchase Invoice Item — match by item_code (join_on: Sales Invoice Item.item_code,
            parent_link_field: "item_code")
    Step 3: Purchase Invoice — get the supplier field (join_on: Purchase Invoice Item.parent,
            parent_link_field: "name")
  This gives the ACTUAL suppliers who delivered those items via purchase transactions.
  Correct join list for "top selling items and their suppliers":
  [
    {"child_doctype":"Sales Invoice Item","parent_link_field":"parent","join_type":"LEFT"},
    {"child_doctype":"Purchase Invoice Item","parent_link_field":"item_code",
     "join_on":"Sales Invoice Item.item_code","join_type":"LEFT"},
    {"child_doctype":"Purchase Invoice","parent_link_field":"name",
     "join_on":"Purchase Invoice Item.parent","join_type":"LEFT"}
  ]
  Use dimension "Purchase Invoice.supplier" to show the supplier name.

9. Output JSON only.
"""


def run(state: GraphState) -> dict:
    t0 = time.monotonic()
    node_name = "query_architect"
    log_t0 = trace.node_start(state, node_name)
    if state.get("_emit_progress"):
        progress.emit(state, node_name, "Planning query structure")

    llm_client = state.get("_llm_client")
    if not llm_client:
        return _passthrough(state, node_name, t0, log_t0)

    user = state.get("user") or frappe.session.user
    settings = state.get("_settings")
    blocked = set(settings.get_blocked_doctype_list() if settings else [])

    question = state.get("normalized_question") or state.get("raw_message", "")
    schema_context = state.get("schema_context") or ""
    presentation_plan = state.get("presentation_plan") or {}

    # Give the LLM a list of all accessible DocType names to choose cross-joins from
    corpus = schema_corpus.get_corpus(blocked)
    available_names = sorted({doc.doctype_name for doc in corpus})

    plan_keys = ("visualization", "query_shape", "dimension_hints", "metric_hints")
    compact_plan = {k: presentation_plan[k] for k in plan_keys if presentation_plan.get(k)}

    user_parts = [
        f"## Primary Schema\n{schema_context}",
        f"## All Available DocTypes\n{', '.join(available_names)}",
    ]
    if compact_plan:
        user_parts.append(f"## Presentation Plan\n{json.dumps(compact_plan)}")
    user_parts.append(f"## Question\n{question}")

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]

    try:
        raw = llm_client.chat_completion(
            messages,
            max_tokens=500,
            **trace.llm_trace_context(state, node_name, "plan_joins"),
        )
        plan = _parse_plan(raw)
    except Exception as exc:
        frappe.log_error(str(exc), "QueryArchitect: plan failed")
        return _passthrough(state, node_name, t0, log_t0)

    trace.detail(state, "Join plan", plan)

    # ── Enrich schema_context with any new DocTypes from the join plan ──
    enriched_by_name: dict = dict(state.get("enriched_schemas_by_doctype") or {})
    new_doctypes: list[str] = []

    for join in plan.get("joins", []):
        child_dt = join.get("child_doctype", "").strip()
        if not child_dt or child_dt in enriched_by_name:
            continue
        try:
            fields = schema_svc.get_doctype_fields(child_dt, user=user)
            links = schema_svc.get_doctype_links(child_dt)
            child_tables = schema_svc.get_child_tables(child_dt, user=user)
            enriched_by_name[child_dt] = {
                "name": child_dt,
                "fields": fields,
                "links": links,
                "child_tables": child_tables,
            }
            new_doctypes.append(child_dt)
        except Exception as exc:
            frappe.log_error(str(exc), f"QueryArchitect: schema fetch failed for {child_dt}")

    if new_doctypes:
        schema_context = schema_svc.build_schema_context(list(enriched_by_name.values()))
        trace.detail(state, "Schema enriched with", new_doctypes)

    return _update(state, node_name, t0, log_t0, {
        "join_plan": plan,
        "schema_context": schema_context,
        "enriched_schemas_by_doctype": enriched_by_name,
    })


def _parse_plan(raw: str) -> dict:
    match = _JSON_FENCE_RE.search(raw)
    cleaned = match.group(1).strip() if match else raw.strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return {"primary_doctype": "", "joins": []}
    if not isinstance(data, dict):
        return {"primary_doctype": "", "joins": []}
    if "joins" not in data:
        data["joins"] = []
    return data


def _passthrough(state: GraphState, node_name: str, t0: float, log_t0: float) -> dict:
    """Non-fatal skip — pass state through with only trace bookkeeping."""
    trace.node_end(state, node_name, log_t0)
    elapsed = round((time.monotonic() - t0) * 1000, 2)
    node_trace = list(state.get("node_trace") or []) + [node_name]
    timing = dict(state.get("timing") or {})
    timing[node_name] = elapsed
    return {"node_trace": node_trace, "timing": timing}


def _update(
    state: GraphState, node_name: str, t0: float, log_t0: float, updates: dict
) -> dict:
    trace.node_end(state, node_name, log_t0)
    elapsed = round((time.monotonic() - t0) * 1000, 2)
    node_trace = list(state.get("node_trace") or []) + [node_name]
    timing = dict(state.get("timing") or {})
    timing[node_name] = elapsed
    return {**updates, "node_trace": node_trace, "timing": timing}
