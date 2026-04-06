"""
Node: Visualization Planner

Runs after query_planner succeeds (has result rows).
Uses the LLM to:
1. Choose the best visualization type for the data.
2. Generate a short, friendly intro sentence shown above the result.

Sets in state:
  visualization_preference  — "card" | "bar" | "pie" | "donut" | "line" | "area" | "stacked_bar" | "text" | "auto"
  answer_prefix             — e.g. "Here's the breakdown you asked for:"
"""
import json
import re
import time

import frappe

from internal_bot.bot.state import GraphState
from internal_bot.bot.services.language import (
	language_name_for_prompt,
	localize_text,
)
from internal_bot.bot import progress, trace

_VALID_PREFERENCES = {"card", "bar", "pie", "donut", "line", "area", "stacked_bar", "text", "auto"}

_SYSTEM_PROMPT = """\
You are a data presentation assistant for an ERP chatbot.
Given a user question and SQL result shape, output ONLY valid JSON — no markdown:
{"visualization": "bar", "prefix": "Here's the breakdown:"}

visualization choices:
- "card"  — 1 row, 1 numeric value (a single KPI/metric)
- "bar"   — default for comparing values across categories (rankings, totals by group, item/SKU/customer/date sales)
- "donut" — proportions or shares across 2–8 categories; prefer this over pie for a more modern look
- "line"  — time-series or trend data; prefer when x-axis is temporal (dates, months, years, quarters) and there are more than 4 data points
- "area"  — time-series emphasizing volume, magnitude, or cumulative values with a filled line
- "stacked_bar" — composition across categories where each bar should show total plus a breakdown into parts
- "pie"   — proportions, shares, breakdowns, distributions, or "how much of the total" questions with 2–8 categories; also good for comparing a few items' contributions
- "text"  — factual lookup, large table, or when no chart fits
- "auto"  — genuinely uncertain; let the system decide

prefix: one short friendly sentence shown above the result.
For "text" answers use something like "Here's what I found:" or "I found your answer:".
For charts/cards use something like "Here is the sales comparison:" or "Here are the numbers:".
Prefer clear, professional phrasing. Avoid casual filler like "you asked for".
If the x-axis is a time dimension (months, dates, years) and there are more than 4 data points, prefer "line" over "bar".
When the question is about shares, proportions, breakdowns, or distribution across a small number of categories (2–8), prefer "donut" over "pie".
When the question is about temporal volume or magnitude, "area" is a good choice.
When each category contains multiple component parts and the user should see both the total and the composition, prefer "stacked_bar".
When the question is about ranking, top/bottom, or time-based comparisons, prefer "bar" or "line".\
Return the prefix in the requested response language.\
"""


def run(state: GraphState) -> dict:
    t0 = time.monotonic()
    node_name = "visualization_planner"
    log_t0 = trace.node_start(state, node_name)
    if state.get("_emit_progress"):
        progress.emit(state, node_name, "Choosing visualization")
    response_language = state.get("response_language") or state.get("user_profile_language") or "en"
    llm_client = state.get("_llm_client")

    if _should_explain_previous_result(state):
        answer_prefix, input_tokens, output_tokens = localize_text(
            "Here's a deeper analysis:",
            response_language,
            llm_client=llm_client,
            trace_context=trace.llm_trace_context(state, node_name, "follow_up_analysis_prefix"),
        )
        trace.detail(state, "Viz choice", "text (follow-up analysis)")
        trace.detail(state, "Answer prefix", answer_prefix)
        return _update(state, node_name, t0, {
            "visualization_preference": "text",
            "answer_prefix": answer_prefix,
            "input_tokens": (state.get("input_tokens") or 0) + input_tokens,
            "output_tokens": (state.get("output_tokens") or 0) + output_tokens,
        }, log_t0)

    if not llm_client:
        return _update(state, node_name, t0, {
            "visualization_preference": "auto",
            "answer_prefix": "",
        }, log_t0)

    rows = state.get("query_result_rows") or []
    columns = list(rows[0].keys()) if rows else []
    question = state.get("normalized_question") or state.get("raw_message", "")

    user_content = (
        f"Question: {question}\n"
        f"Response language: {language_name_for_prompt(response_language)}\n"
        f"Columns: {columns}\n"
        f"Row count: {len(rows)}\n"
        f"Sample (first 3 rows): {_safe_sample(rows, 3)}"
    )

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        raw = llm_client.chat_completion(
            messages,
            temperature=0.0,
            max_tokens=150,
            **trace.llm_trace_context(state, node_name, "choose_visualization"),
        )
        input_tokens = (state.get("input_tokens") or 0) + (
            getattr(llm_client, "last_input_tokens", 0) or 0
        )
        output_tokens = (state.get("output_tokens") or 0) + (
            getattr(llm_client, "last_output_tokens", 0) or 0
        )
        result = _parse_response(raw)
        localized_prefix, extra_in_tokens, extra_out_tokens = localize_text(
            result.get("prefix") or "",
            response_language,
            llm_client=llm_client,
            trace_context=trace.llm_trace_context(state, node_name, "localize_answer_prefix"),
        )
        input_tokens += extra_in_tokens
        output_tokens += extra_out_tokens
        trace.detail(state, "Viz choice", result.get("visualization"))
        trace.detail(state, "Answer prefix", localized_prefix)
    except Exception as exc:
        frappe.log_error(str(exc), "VisualizationPlanner LLM error")
        return _update(state, node_name, t0, {
            "visualization_preference": "auto",
            "answer_prefix": "",
            "input_tokens": (state.get("input_tokens") or 0) + (
                getattr(llm_client, "last_input_tokens", 0) or 0
            ),
            "output_tokens": (state.get("output_tokens") or 0) + (
                getattr(llm_client, "last_output_tokens", 0) or 0
            ),
            "llm_provider": getattr(llm_client, "provider", ""),
            "llm_model": getattr(llm_client, "model", ""),
        }, log_t0)

    visualization = result.get("visualization") or "auto"
    if visualization not in _VALID_PREFERENCES:
        visualization = "auto"

    return _update(state, node_name, t0, {
        "visualization_preference": visualization,
        "answer_prefix": localized_prefix or result.get("prefix") or "",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "llm_provider": getattr(llm_client, "provider", ""),
        "llm_model": getattr(llm_client, "model", ""),
    }, log_t0)


def _parse_response(raw: str) -> dict:
    """Parse JSON from LLM response, stripping markdown fences if present."""
    cleaned = raw.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned, re.IGNORECASE)
    if match:
        cleaned = match.group(1).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        return {"visualization": "auto", "prefix": ""}


def _safe_sample(rows: list[dict], n: int) -> list[dict]:
    """Return first n rows with all values converted to JSON-safe types."""
    import datetime
    import decimal
    import math

    result = []
    for row in rows[:n]:
        clean = {}
        for k, v in row.items():
            if isinstance(v, decimal.Decimal):
                clean[k] = float(v) if math.isfinite(float(v)) else str(v)
            elif isinstance(v, (datetime.date, datetime.datetime)):
                clean[k] = str(v)
            elif v is None:
                clean[k] = None
            else:
                clean[k] = v
        result.append(clean)
    return result


def _should_explain_previous_result(state: GraphState) -> bool:
    """Only force 'deeper analysis' mode for explicit analysis requests.

    Simple follow-up questions (who's the lowest, what did they buy) should
    go through normal visualization planning so they get a proper title and
    chart type from the LLM.
    """
    if not state.get("follow_up_to_previous_result"):
        return False

    question = (state.get("normalized_question") or state.get("raw_message") or "").lower()
    if not any(re.search(p, question) for p in (
        r"\banaly[sz]e\b", r"\banalysis\b", r"\bexplain\b", r"\binterpret\b",
        r"\bbreak down\b", r"\bdeeper\b", r"\bfurther\b", r"\binsight(s)?\b",
        r"\bwhat does this mean\b",
    )):
        return False

    last_response = state.get("last_assistant_response") or {}
    last_response_type = last_response.get("response_type")
    if last_response_type not in {
        "bar_chart",
        "pie_chart",
        "donut_chart",
        "line_chart",
        "area_chart",
        "stacked_bar_chart",
        "metric_card",
        "table",
    }:
        return False

    return True


def _update(state: GraphState, node_name: str, t0: float, updates: dict, log_t0: float) -> dict:
    elapsed = round((time.monotonic() - t0) * 1000, 2)
    node_trace = list(state.get("node_trace") or []) + [node_name]
    timing = dict(state.get("timing") or {})
    timing[node_name] = elapsed
    from internal_bot.bot import trace as bench_trace
    bench_trace.node_end(state, node_name, log_t0)
    return {**updates, "node_trace": node_trace, "timing": timing}
