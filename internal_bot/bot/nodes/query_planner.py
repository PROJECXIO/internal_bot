"""
Node: Query Planner

Unified replacement for sql_generator + sql_validator + sql_executor.

Steps per invocation:
1. Call LLM via sql_service.generate_query_intent() → JSON intent dict
2. Permission re-check: verify the requested DocType is accessible
   (LLM may hallucinate a DocType not in schema_context)
3. Execute via query_executor.execute_query_intent()

On frappe.PermissionError:
    Force give_up immediately (query_generation_attempts = MAX_RETRIES).
    Permission denied is not a transient error — retrying won't help.

On other exceptions:
    Increment query_generation_attempts, allowing the graph router to retry
    up to _MAX_RETRIES times with the error as context for the next LLM call.
"""
import time

import frappe

from internal_bot.bot.services import permission_service, query_executor, sql_service
from internal_bot.bot.state import GraphState
from internal_bot.bot import progress

_MAX_RETRIES = 3


def run(state: GraphState) -> dict:
    t0 = time.monotonic()
    node_name = "query_planner"

    attempt = state.get("query_generation_attempts") or 0
    if state.get("_emit_progress"):
        label = (
            "Planning query"
            if attempt == 0
            else f"Trying again\u2026 (attempt {attempt + 1})"
        )
        progress.emit(state, node_name, label)

    llm_client = state.get("_llm_client")
    if not llm_client:
        return _update(state, node_name, t0, {
            "query_is_valid": False,
            "query_invalid_reason": "No LLM client configured",
            "query_generation_attempts": _MAX_RETRIES,  # force give_up
        })

    user = state.get("user") or frappe.session.user
    settings = state.get("_settings")
    max_rows = (settings.max_result_rows if settings else None) or 100

    # Build memory context from chat history + rolling summary
    memory_parts = []
    if state.get("memory_summary"):
        memory_parts.append(f"Previous context summary:\n{state['memory_summary']}")
    history = state.get("chat_history") or []
    if history:
        history_text = "\n".join(
            f"{m['role'].upper()}: {m['content']}" for m in history[-6:]
        )
        memory_parts.append(f"Recent messages:\n{history_text}")
    memory_context = "\n\n".join(memory_parts)

    previous_error = (
        state.get("query_execution_error")
        or state.get("query_invalid_reason")
        or None
    )

    # ── Step 1: LLM generates a JSON query intent ─────────────────────
    try:
        intent = sql_service.generate_query_intent(
            question=state.get("normalized_question") or state.get("raw_message", ""),
            schema_context=state.get("schema_context") or "",
            memory_context=memory_context,
            llm_client=llm_client,
            attempt=attempt,
            previous_error=previous_error,
        )
        input_tokens = (state.get("input_tokens") or 0) + (
            getattr(llm_client, "last_input_tokens", 0) or 0
        )
        output_tokens = (state.get("output_tokens") or 0) + (
            getattr(llm_client, "last_output_tokens", 0) or 0
        )
    except Exception as exc:
        frappe.log_error(message=str(exc), title="QueryPlanner LLM error")
        return _update(state, node_name, t0, {
            "query_is_valid": False,
            "query_invalid_reason": f"LLM error: {exc}",
            "query_generation_attempts": attempt + 1,
            "retries": attempt + 1,
            "input_tokens": (state.get("input_tokens") or 0) + (
                getattr(llm_client, "last_input_tokens", 0) or 0
            ),
            "output_tokens": (state.get("output_tokens") or 0) + (
                getattr(llm_client, "last_output_tokens", 0) or 0
            ),
            "llm_provider": getattr(llm_client, "provider", ""),
            "llm_model": getattr(llm_client, "model", ""),
        })

    # ── Step 2: Permission re-check on the selected DocType ───────────
    # The LLM only sees permitted DocTypes in schema_context, but it may
    # hallucinate a DocType name not in the list.
    primary_doctype = intent.get("doctype") or intent.get("primary_doctype")
    if not primary_doctype or not permission_service.check_doctype_read_access(
        primary_doctype, user
    ):
        return _update(state, node_name, t0, {
            "generated_intent": intent,
            "query_is_valid": False,
            "query_invalid_reason": (
                f"DocType '{primary_doctype}' is not accessible. "
                "Use only the DocTypes listed in the schema context."
            ),
            "query_generation_attempts": attempt + 1,
            "retries": attempt + 1,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "llm_provider": getattr(llm_client, "provider", ""),
            "llm_model": getattr(llm_client, "model", ""),
        })

    # ── Step 3: Execute ───────────────────────────────────────────────
    try:
        rows, compiled_sql = query_executor.execute_query_intent(intent, user, max_rows)
        return _update(state, node_name, t0, {
            "generated_intent": intent,
            "validated_intent": intent,
            "compiled_sql": compiled_sql,
            "query_result_rows": rows,
            "query_execution_error": "",
            "query_invalid_reason": "",
            "query_is_valid": True,
            "result_row_count": len(rows),
            "query_generation_attempts": attempt,
            "retries": attempt,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "llm_provider": getattr(llm_client, "provider", ""),
            "llm_model": getattr(llm_client, "model", ""),
        })
    except frappe.PermissionError as exc:
        # Permission errors are not retryable — force give_up immediately
        return _update(state, node_name, t0, {
            "generated_intent": intent,
            "query_is_valid": False,
            "query_invalid_reason": str(exc),
            "query_generation_attempts": _MAX_RETRIES,  # forces give_up routing
            "retries": _MAX_RETRIES,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "llm_provider": getattr(llm_client, "provider", ""),
            "llm_model": getattr(llm_client, "model", ""),
        })
    except Exception as exc:
        return _update(state, node_name, t0, {
            "generated_intent": intent,
            "query_is_valid": False,
            "query_execution_error": str(exc),
            "query_generation_attempts": attempt + 1,
            "retries": attempt + 1,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "llm_provider": getattr(llm_client, "provider", ""),
            "llm_model": getattr(llm_client, "model", ""),
        })


def _update(state: GraphState, node_name: str, t0: float, updates: dict) -> dict:
    elapsed = round((time.monotonic() - t0) * 1000, 2)
    trace = list(state.get("node_trace") or []) + [node_name]
    timing = dict(state.get("timing") or {})
    timing[node_name] = elapsed
    return {**updates, "node_trace": trace, "timing": timing}
