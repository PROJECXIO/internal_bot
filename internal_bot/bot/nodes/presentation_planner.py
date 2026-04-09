"""
Node: Presentation Planner

Runs before query_planner. It asks the LLM for an advisory result shape and
visualization direction so query generation can produce data that fits the
intended presentation.

This node does not decide the final visualization. visualization_planner still
runs after query execution and uses the actual returned rows as the source of
truth.
"""
import json
import re
import time

import frappe

from internal_bot.bot.state import GraphState
from internal_bot.bot.services.language import language_name_for_prompt
from internal_bot.bot import progress, trace


_VALID_VISUALIZATIONS = {
	"card",
	"bar",
	"donut",
	"pie",
	"line",
	"area",
	"stacked_bar",
	"heatmap",
	"table",
	"text",
	"auto",
}
_VALID_QUERY_SHAPES = {
	"metric",
	"category_comparison",
	"time_series",
	"composition",
	"stacked_composition",
	"matrix",
	"record_list",
	"lookup",
	"flat_rows",
	"auto",
}

_DEFAULT_PLAN = {
	"visualization": "auto",
	"query_shape": "auto",
	"dimension_hints": [],
	"metric_hints": [],
	"limit_hint": None,
	"reason": "",
}

_SYSTEM_PROMPT = """\
You plan the result shape for an ERP analytics chatbot before the database query
is generated.

Return ONLY valid JSON. Do not return markdown, SQL, or explanations.

Output shape:
{
  "visualization": "card|bar|donut|pie|line|area|stacked_bar|heatmap|table|text|auto",
  "query_shape": "metric|category_comparison|time_series|composition|stacked_composition|matrix|record_list|lookup|flat_rows|auto",
  "dimension_hints": ["field or role hints"],
  "metric_hints": ["field or role hints"],
  "limit_hint": 20,
  "reason": "short reason"
}

Rules:
- This plan is advisory. The backend will still validate schema, permissions,
  and returned data shape later.
- Use only fields, DocTypes, or field roles that are supported by the available
  schema. If unsure, use role hints like "date", "category", or "amount".
- For one aggregate number, choose visualization "card" and query_shape "metric".
  In this case, keep dimension_hints empty. Entity words like customer or item
  may describe the business domain, but they are not dimensions unless the user
  asks "by customer", "per item", "each customer", "breakdown", or similar.
- For category ranking or comparison, choose "bar" and "category_comparison".
- For trends over time, choose "line" or "area" and "time_series".
- For share/proportion questions, choose "donut" and "composition".
- For two-level breakdowns where each category has component parts, choose
  "stacked_bar" and "stacked_composition" for compact comparisons.
- For dense cross-tab questions with two categorical dimensions and one metric,
  choose "heatmap" and "matrix".
- For item/SKU/product movement or sales per customer, including Arabic phrasing
  like "حركة الاصناف عند كل عميل", prefer "heatmap" and "matrix" when the user
  needs a broad customer-by-item view. Use "stacked_bar" only for a smaller
  compact comparison.
- For record lists, factual lookups, or large/detail-oriented answers, choose
  "table" or "text" and do not force aggregation.
- Use "auto" when the question or schema is not specific enough.
"""


def run(state: GraphState) -> dict:
	t0 = time.monotonic()
	node_name = "presentation_planner"
	log_t0 = trace.node_start(state, node_name)
	if state.get("_emit_progress"):
		progress.emit(state, node_name, "Planning result shape")

	llm_client = state.get("_llm_client")
	if not llm_client:
		return _update(state, node_name, t0, _state_from_plan(dict(_DEFAULT_PLAN)), log_t0)

	question = state.get("normalized_question") or state.get("raw_message", "")
	response_language = state.get("response_language") or state.get("user_profile_language") or "en"
	user_content = _build_user_content(state, question, response_language)
	messages = [
		{"role": "system", "content": _SYSTEM_PROMPT},
		{"role": "user", "content": user_content},
	]

	try:
		raw = llm_client.chat_completion(
			messages,
			temperature=0.0,
			max_tokens=250,
			**trace.llm_trace_context(state, node_name, "plan_presentation"),
		)
		input_tokens = (state.get("input_tokens") or 0) + (
			getattr(llm_client, "last_input_tokens", 0) or 0
		)
		output_tokens = (state.get("output_tokens") or 0) + (
			getattr(llm_client, "last_output_tokens", 0) or 0
		)
		plan = _normalize_plan(_parse_response(raw))
		trace.detail(state, "Presentation plan", plan)
	except Exception as exc:
		try:
			frappe.log_error(str(exc), "PresentationPlanner LLM error")
		except Exception:
			pass
		plan = dict(_DEFAULT_PLAN)
		input_tokens = (state.get("input_tokens") or 0) + (
			getattr(llm_client, "last_input_tokens", 0) or 0
		)
		output_tokens = (state.get("output_tokens") or 0) + (
			getattr(llm_client, "last_output_tokens", 0) or 0
		)

	return _update(
		state,
		node_name,
		t0,
		{
			**_state_from_plan(plan),
			"input_tokens": input_tokens,
			"output_tokens": output_tokens,
			"llm_provider": getattr(llm_client, "provider", ""),
			"llm_model": getattr(llm_client, "model", ""),
		},
		log_t0,
	)


def _build_user_content(state: GraphState, question: str, response_language: str) -> str:
	parts = [
		f"## Question\n{question}",
		f"## Response Language\n{language_name_for_prompt(response_language)}",
	]
	if state.get("current_date") or state.get("current_day_name") or state.get("current_year"):
		parts.append(
			"## Current Date Context\n"
			f"Date: {state.get('current_date') or ''}\n"
			f"Day: {state.get('current_day_name') or ''}\n"
			f"Year: {state.get('current_year') or ''}"
		)
	if state.get("memory_summary"):
		parts.append(f"## Conversation Summary\n{state['memory_summary']}")
	history = state.get("chat_history") or []
	if history:
		history_text = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in history[-4:])
		parts.append(f"## Recent Messages\n{history_text}")
	if state.get("last_assistant_context_text"):
		parts.append(f"## Last Structured Result Context\n{state['last_assistant_context_text']}")
	if state.get("discovered_doctypes"):
		parts.append(f"## Matching DocTypes\n{', '.join(state['discovered_doctypes'])}")
	if state.get("schema_context"):
		parts.append(f"## Available Schema\n{state['schema_context']}")
	return "\n\n".join(parts)


def _parse_response(raw: str) -> dict:
	cleaned = (raw or "").strip()
	match = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned, re.IGNORECASE)
	if match:
		cleaned = match.group(1).strip()
	return json.loads(cleaned)


def _normalize_plan(raw_plan: dict) -> dict:
	if not isinstance(raw_plan, dict):
		return dict(_DEFAULT_PLAN)

	visualization = str(raw_plan.get("visualization") or "auto").strip().lower()
	if visualization not in _VALID_VISUALIZATIONS:
		visualization = "auto"

	query_shape = str(raw_plan.get("query_shape") or "auto").strip().lower()
	if query_shape not in _VALID_QUERY_SHAPES:
		query_shape = "auto"

	dimension_hints = _normalize_string_list(raw_plan.get("dimension_hints"))
	if query_shape == "metric" or visualization == "card":
		dimension_hints = []

	return {
		"visualization": visualization,
		"query_shape": query_shape,
		"dimension_hints": dimension_hints,
		"metric_hints": _normalize_string_list(raw_plan.get("metric_hints")),
		"limit_hint": _normalize_limit(raw_plan.get("limit_hint")),
		"reason": str(raw_plan.get("reason") or "")[:240],
	}


def _normalize_string_list(value) -> list[str]:
	if not isinstance(value, list):
		return []
	return [str(item).strip() for item in value if str(item).strip()][:8]


def _normalize_limit(value) -> int | None:
	try:
		limit = int(value)
	except (TypeError, ValueError):
		return None
	if limit <= 0:
		return None
	return min(limit, 100)


def _state_from_plan(plan: dict) -> dict:
	return {
		"presentation_plan": plan,
		"pre_query_visualization_preference": plan.get("visualization") or "auto",
		"query_shape": plan.get("query_shape") or "auto",
		"presentation_reason": plan.get("reason") or "",
	}


def _update(state: GraphState, node_name: str, t0: float, updates: dict, log_t0: float) -> dict:
	elapsed = round((time.monotonic() - t0) * 1000, 2)
	node_trace = list(state.get("node_trace") or []) + [node_name]
	timing = dict(state.get("timing") or {})
	timing[node_name] = elapsed
	from internal_bot.bot import trace as bench_trace
	bench_trace.node_end(state, node_name, log_t0)
	return {**updates, "node_trace": node_trace, "timing": timing}
