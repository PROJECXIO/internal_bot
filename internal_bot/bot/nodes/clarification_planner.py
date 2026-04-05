"""
Node: Clarification Planner

Runs when schema_discovery finds more than one matching DocType.
Uses the LLM to decide whether it has enough information to build a query,
or asks a single focused clarification question.

Multi-turn: on subsequent turns the LLM sees the full chat_history so it
naturally advances through questions until it has enough context, then
routes to query_planner.
"""
import json
import re
import time

import frappe

from internal_bot.bot.state import GraphState
from internal_bot.bot import progress, trace

_SYSTEM_PROMPT = """\
You are a data query assistant for an ERP system.

Given a user's question, the matching DocTypes, and conversation history, \
decide whether you have enough information to run a specific database query.

Output ONLY valid JSON — no explanation, no markdown fences.

If ready:   {"ready": true}
If not:     {"ready": false, "question": "ONE focused question", "options": ["option1", ...]}

---

## Step 1 — Is the DocType resolved?

Check if the user's question (or conversation history) already names one of \
the Matching DocTypes.
- If YES → DocType is resolved. Do NOT ask about it.
- If NO  → Ask which document. Options = 3-5 transactional DocType names from \
  the Matching DocTypes list (skip config types like "Sales Stage", \
  "Sales Taxes and Charges Template", "Sales Partner Type").

## Step 2 — Is the time period resolved?

Only ask about the period if the question contains a vague PLACEHOLDER for a \
period that the user clearly intends to specify (phrases like "for a period", \
"for some period", "during a period", "for the period").
- If the question has such a placeholder → ask for the period.
  Options = ["All dates", "This month", "Last month", "This year", "Last year", \
  "Last 30 days", "Custom range"]
- If NO period is mentioned at all → that is fine, do NOT invent a requirement.
- If a specific period IS already named ("all dates", "this month", "2024", "last year") → resolved.

## Step 3 — Decision

- Both DocType and period are resolved (or not needed) → {"ready": true}
- DocType unresolved → ask about DocType first
- DocType resolved but period placeholder remains → ask about period

## Rules:
- Ask only ONE question per turn
- Read conversation history — never re-ask an already-answered question
- "options" must always be present (use [] if truly no options apply)
"""


def run(state: GraphState) -> dict:
    t0 = time.monotonic()
    node_name = "clarification_planner"
    log_t0 = trace.node_start(state, node_name)
    if state.get("_emit_progress"):
        progress.emit(state, node_name, "Checking query details")

    llm_client = state.get("_llm_client")
    if not llm_client:
        return _update(state, node_name, t0, {"ready_to_query": True}, log_t0)

    question = state.get("normalized_question") or state.get("raw_message", "")
    schema_context = state.get("schema_context") or ""
    discovered = state.get("discovered_doctypes") or []

    # Short-circuit: if the user selected a DocType from the options AND the
    # question has no pending period placeholder, go straight to query_planner.
    raw = (state.get("raw_message") or "").strip()
    discovered_lower = {dt.lower() for dt in discovered}
    _PERIOD_PLACEHOLDERS = ("for a period", "for some period", "during a period", "for the period")
    has_period_placeholder = any(p in question.lower() for p in _PERIOD_PLACEHOLDERS)
    if raw.lower() in discovered_lower and not has_period_placeholder:
        return _update(state, node_name, t0, {"ready_to_query": True}, log_t0)

    # Build conversation history context
    history_lines = []
    for msg in (state.get("chat_history") or [])[-6:]:
        role = msg["role"].upper()
        history_lines.append(f"{role}: {msg['content']}")

    user_parts = []
    if history_lines:
        user_parts.append("## Conversation History\n" + "\n".join(history_lines))
    if state.get("last_assistant_context_text"):
        user_parts.append("## Last Structured Result Context\n" + state["last_assistant_context_text"])
    user_parts.append(f"## Current Question\n{question}")
    if schema_context:
        user_parts.append(f"## Available Schema\n{schema_context}")
    if discovered:
        user_parts.append(f"## Matching DocTypes\n{', '.join(discovered)}")

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]

    try:
        raw = llm_client.chat_completion(
            messages,
            temperature=0.0,
            max_tokens=200,
            **trace.llm_trace_context(state, node_name, "plan_clarification"),
        )
        input_tokens = (state.get("input_tokens") or 0) + (
            getattr(llm_client, "last_input_tokens", 0) or 0
        )
        output_tokens = (state.get("output_tokens") or 0) + (
            getattr(llm_client, "last_output_tokens", 0) or 0
        )
        result = _parse_response(raw)
    except Exception as exc:
        frappe.log_error(str(exc), "ClarificationPlanner LLM error")
        return _update(
            state,
            node_name,
            t0,
            {
                "ready_to_query": True,
                "input_tokens": (state.get("input_tokens") or 0) + (
                    getattr(llm_client, "last_input_tokens", 0) or 0
                ),
                "output_tokens": (state.get("output_tokens") or 0) + (
                    getattr(llm_client, "last_output_tokens", 0) or 0
                ),
                "llm_provider": getattr(llm_client, "provider", ""),
                "llm_model": getattr(llm_client, "model", ""),
            },
            log_t0,
        )

    if result.get("ready"):
        return _update(
            state,
            node_name,
            t0,
            {
                "ready_to_query": True,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "llm_provider": getattr(llm_client, "provider", ""),
                "llm_model": getattr(llm_client, "model", ""),
            },
            log_t0,
        )

    return _update(state, node_name, t0, {
        "ready_to_query": False,
        "clarification_question": result.get("question", "Could you provide more details about what you're looking for?"),
        "clarification_options": result.get("options") or [],
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
        # Cannot parse — fail-open and let query_planner try
        return {"ready": True}


def _update(state: GraphState, node_name: str, t0: float, updates: dict, log_t0: float) -> dict:
    elapsed = round((time.monotonic() - t0) * 1000, 2)
    trace = list(state.get("node_trace") or []) + [node_name]
    timing = dict(state.get("timing") or {})
    timing[node_name] = elapsed
    from internal_bot.bot import trace as bench_trace
    bench_trace.node_end(state, node_name, log_t0)
    return {**updates, "node_trace": trace, "timing": timing}
