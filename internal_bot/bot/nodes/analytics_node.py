"""
Node 9 — Analytics

Final node in the pipeline. Always runs.
Responsibilities:
1. Save the user message and the assistant response to AI Chat Message
2. Trigger summary regeneration if threshold exceeded
3. Write an AI Bot Analytics record
"""
import time

import frappe

from internal_bot.bot.services import analytics_service, memory as memory_svc
from internal_bot.bot.state import GraphState
from internal_bot.bot import progress, trace


def run(state: GraphState) -> dict:
    t0 = time.monotonic()
    node_name = "analytics"
    log_t0 = trace.node_start(state, node_name)
    if state.get("_emit_progress"):
        progress.emit(state, node_name, "Saving results")

    user = state.get("user") or frappe.session.user
    session_name = state.get("session_name") or ""
    response = state.get("formatted_response") or {}
    status = response.get("status", "error")
    trace.detail(state, "Persisting status", status)

    # ── 1. Persist chat messages ─────────────────────────────────────
    if session_name:
        import json
        # User message
        try:
            memory_svc.save_message(
                session_name=session_name,
                role="user",
                content=state.get("raw_message") or "",
                status="success",  # user messages are always "success"
            )
        except Exception:
            frappe.log_error(frappe.get_traceback(), "AI Chat: failed to save user message")

        # Assistant message (with debug fields)
        _VALID_STATUSES = {"success", "clarification_needed", "blocked", "error", "greeting"}
        save_status = status if status in _VALID_STATUSES else "success"
        try:
            assistant_msg_name = memory_svc.save_message(
                session_name=session_name,
                role="assistant",
                content=_response_to_text(response),
                status=save_status,
                structured_response=json.dumps(response),
                normalized_question=state.get("normalized_question"),
                discovered_entities=json.dumps(state.get("discovered_doctypes") or []),
                generated_sql=frappe.as_json(state.get("generated_intent") or {}),
                validated_sql=state.get("compiled_sql"),
                retries=state.get("query_generation_attempts") or 0,
                response_time_ms=round(
                    (time.monotonic() - state.get("start_time", t0)) * 1000
                ),
                llm_provider=state.get("llm_provider"),
                llm_model=state.get("llm_model"),
                node_trace=state.get("node_trace") or [],
                error_detail=(
                    state.get("query_execution_error")
                    or state.get("query_invalid_reason")
                ),
            )
            frappe.db.commit()
        except Exception:
            frappe.log_error(
                frappe.get_traceback(), "AI Chat: failed to save assistant message"
            )
            assistant_msg_name = None

        # ── 2. Maybe update summary ──────────────────────────────────
        llm_client = state.get("_llm_client")
        settings = state.get("_settings")
        threshold = settings.summary_threshold if settings else 20
        if llm_client:
            try:
                memory_svc.maybe_update_summary(session_name, threshold, llm_client)
            except Exception:
                pass
    else:
        assistant_msg_name = None

    # ── 3. Write analytics record ────────────────────────────────────
    event_type = "ask"
    if status == "blocked":
        event_type = "blocked"
    elif status == "error":
        event_type = "error"

    response_time_ms = round((time.monotonic() - state.get("start_time", t0)) * 1000)

    analytics_service.save_analytics(
        user=user,
        event_type=event_type,
        session=session_name,
        message=assistant_msg_name,
        status=status,
        provider=state.get("llm_provider"),
        model=state.get("llm_model"),
        input_tokens=state.get("input_tokens") or 0,
        output_tokens=state.get("output_tokens") or 0,
        response_time_ms=response_time_ms,
        retries=state.get("query_generation_attempts") or 0,
        sql_executed=state.get("compiled_sql") or "",
        result_row_count=state.get("result_row_count") or 0,
    )

    return _update(state, node_name, t0, {}, log_t0)


def _response_to_text(response: dict) -> str:
    """Convert the structured response to a plain-text string for storage."""
    status = response.get("status", "")
    if status == "success":
        rows = response.get("rows") or []
        return f"Returned {len(rows)} row(s)."
    elif status == "clarification_needed":
        return response.get("question", "Clarification needed.")
    elif status == "blocked":
        return response.get("reason", "Blocked.")
    elif status == "greeting":
        return response.get("message", "Hello!")
    else:
        return response.get("reason", "Error.")


def _update(state: GraphState, node_name: str, t0: float, updates: dict, log_t0: float) -> dict:
    elapsed = round((time.monotonic() - t0) * 1000, 2)
    trace = list(state.get("node_trace") or []) + [node_name]
    timing = dict(state.get("timing") or {})
    timing[node_name] = elapsed
    from internal_bot.bot import trace as bench_trace
    bench_trace.node_end(state, node_name, log_t0)
    return {**updates, "node_trace": trace, "timing": timing}
