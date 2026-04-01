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
from internal_bot.bot import progress

_SYSTEM_PROMPT = """\
You are a data query assistant for an ERP system.

Given a user's question, the available database schema, and conversation \
history, decide whether you have enough information to run a specific \
database query.

Output ONLY valid JSON — no explanation, no markdown fences.

If you have enough information to query:
{"ready": true}

If you need more information, ask ONE focused question and provide \
context-appropriate options for the user to choose from:
{"ready": false, "question": "Your single question here", "options": ["option1", "option2"]}

## When you MUST ask (do NOT say ready: true):

1. MULTIPLE DOCUMENT TYPES match and the user has not explicitly named one.
   → Ask which document. Options = only the 3-5 most relevant document names
     from the Matching DocTypes list (exclude setup/configuration types like
     "Sales Partner Type", "Sales Taxes and Charges Template", "Sales Stage",
     "Sales Person" — keep only transactional documents).

2. A TIME PERIOD is implied but not specified ("a period", "some period",
   "last period", vague time reference).
   → Ask for the period. Options = ["This month", "Last month", "This year",
     "Last year", "Last 30 days", "Custom range"]

3. BOTH apply → ask about document type first (next turn will ask period).

## Rules:
- Ask only ONE question at a time
- Read conversation history — never re-ask an already-answered question
- Be conservative: when in doubt, ask rather than assume
- "options" must always be present (use [] if no good options exist)
"""


def run(state: GraphState) -> dict:
    t0 = time.monotonic()
    node_name = "clarification_planner"
    if state.get("_emit_progress"):
        progress.emit(state, node_name, "Checking query details")

    llm_client = state.get("_llm_client")
    if not llm_client:
        return _update(state, node_name, t0, {"ready_to_query": True})

    question = state.get("normalized_question") or state.get("raw_message", "")
    schema_context = state.get("schema_context") or ""
    discovered = state.get("discovered_doctypes") or []

    # Fast-path: if the user's question explicitly names one of the discovered
    # DocTypes AND there is no vague/unresolved time period, skip the LLM.
    _VAGUE_PERIOD_PHRASES = (
        "a period", "some period", "the period", "certain period",
        "a time", "some time", "a date range", "some date",
        "for period", "which period", "what period",
    )
    question_lower = question.lower()
    has_vague_period = any(p in question_lower for p in _VAGUE_PERIOD_PHRASES)
    if not has_vague_period:
        for dt in discovered:
            if dt.lower() in question_lower:
                return _update(state, node_name, t0, {"ready_to_query": True})

    # Build conversation history context
    history_lines = []
    for msg in (state.get("chat_history") or [])[-6:]:
        role = msg["role"].upper()
        history_lines.append(f"{role}: {msg['content']}")

    user_parts = []
    if history_lines:
        user_parts.append("## Conversation History\n" + "\n".join(history_lines))
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
        raw = llm_client.chat_completion(messages, temperature=0.0, max_tokens=200)
        result = _parse_response(raw)
    except Exception as exc:
        frappe.log_error(str(exc), "ClarificationPlanner LLM error")
        return _update(state, node_name, t0, {"ready_to_query": True})

    if result.get("ready"):
        return _update(state, node_name, t0, {"ready_to_query": True})

    return _update(state, node_name, t0, {
        "ready_to_query": False,
        "clarification_question": result.get("question", "Could you provide more details about what you're looking for?"),
        "clarification_options": result.get("options") or [],
    })


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


def _update(state: GraphState, node_name: str, t0: float, updates: dict) -> dict:
    elapsed = round((time.monotonic() - t0) * 1000, 2)
    trace = list(state.get("node_trace") or []) + [node_name]
    timing = dict(state.get("timing") or {})
    timing[node_name] = elapsed
    return {**updates, "node_trace": trace, "timing": timing}
