"""
Background pipeline runner for the async chat path.

Called via frappe.enqueue() from ask_async(). Runs the full LangGraph
pipeline in a background RQ worker, emitting progress events to the
browser via frappe.publish_realtime for each node.

frappe.set_user(user) is called automatically by Frappe's execute_job()
before this function runs, so frappe.session.user is valid here.
"""
import time
from pathlib import Path

import frappe
from dotenv import load_dotenv

from internal_bot.bot import progress
from internal_bot.bot import trace
from internal_bot.bot.graph import get_graph
from internal_bot.bot.services.language import get_user_profile_language
from internal_bot.bot.services.llm_client import get_llm_client

# Load env vars (LangSmith etc.) — same as chat.py
_ENV_FILE = Path(__file__).parents[2] / ".env"
load_dotenv(_ENV_FILE, override=False)


def run_pipeline_job(
    user: str,
    message: str,
    session_name: str,
    pipeline_job_id: str,
    debug: bool = False,
) -> dict:
    """
    Execute the LangGraph pipeline as a background job.

    Emits bot_progress realtime events at each node, then emits
    a final is_complete event with the full response payload.
    The result is also stored in frappe.cache for the polling fallback.

    Note: parameter is named pipeline_job_id (not job_id) because
    frappe.enqueue intercepts the job_id kwarg for RQ's own job ID
    and does not forward it to this function.
    """
    # Minimal state needed for progress emission before graph starts
    _bootstrap_state = {
        "user": user,
        "session_name": session_name,
        "_job_id": pipeline_job_id,
        "_emit_progress": True,
        "query_generation_attempts": 0,
    }

    # Emit a "starting" event so the browser knows the job is alive
    progress.emit(_bootstrap_state, "starting", "Starting\u2026")

    try:
        settings = frappe.get_doc("AI Provider Settings")
    except Exception:
        _store_result(pipeline_job_id, {
            "status": "error",
            "reason": "AI Provider is not configured. Please ask your system administrator.",
            "meta": {"confidence": 0.0},
            "session_id": session_name,
        })
        progress.emit_error(_bootstrap_state, user=user)
        return

    try:
        llm_client = get_llm_client()
    except Exception as exc:
        frappe.log_error(message=str(exc), title="Internal Bot: LLM client init failed (job)")
        _store_result(pipeline_job_id, {
            "status": "error",
            "reason": "Could not initialise the AI provider. Please check your settings.",
            "meta": {"confidence": 0.0},
            "session_id": session_name,
        })
        progress.emit_error(_bootstrap_state, user=user)
        return

    current_dt = frappe.utils.get_datetime()
    initial_state = {
        "user": user,
        "raw_message": message.strip(),
        "session_name": session_name,
        "debug": bool(debug),
        "max_rows": settings.max_result_rows or 100,
        "current_date": str(current_dt.date()),
        "current_day_name": current_dt.strftime("%A"),
        "current_year": current_dt.year,
        "user_profile_language": get_user_profile_language(user),
        "start_time": time.monotonic(),
        "node_trace": [],
        "timing": {},
        "query_generation_attempts": 0,
        "retries": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "result_row_count": 0,
        "answer_markdown": "",
        # Async-path flags
        "_emit_progress": True,
        "_job_id": pipeline_job_id,
        # Injected objects
        "_llm_client": llm_client,
        "_settings": settings,
    }

    try:
        trace.request_start(
            initial_state,
            [
                f'Question: "{message.strip()}"',
                f"Session: {session_name}",
                f"Job: {pipeline_job_id}",
                "Invoking graph...",
            ],
        )
        graph = get_graph()
        final_state = graph.invoke(
            initial_state,
            config=trace.graph_invoke_config(initial_state, run_name="internal_bot.ask_async"),
        )
        response = final_state.get("formatted_response") or {
            "status": "error",
            "reason": "No response generated.",
            "meta": {"confidence": 0.0},
        }
        response["session_id"] = session_name

        _store_result(pipeline_job_id, {"status": "complete", "response": response})
        progress.emit_complete(final_state, response)
        trace.request_complete(final_state, response)
        trace.flush_langsmith()

    except Exception as exc:
        frappe.log_error(
            message=frappe.get_traceback(),
            title="Internal Bot: pipeline_job graph invoke failed",
        )
        error_response = {
            "status": "error",
            "reason": "An internal error occurred. Please try again.",
            "meta": {"confidence": 0.0},
            "session_id": session_name,
        }
        _store_result(pipeline_job_id, {"status": "error", "response": error_response})
        progress.emit_error(initial_state, user=user)
        trace.request_error(initial_state, str(exc))
        trace.flush_langsmith()


def _store_result(job_id: str, result: dict) -> None:
    """Cache the final result so ask_status() can retrieve it."""
    try:
        frappe.cache().set_value(
            f"bot_result:{job_id}",
            frappe.as_json(result),
            expires_in_sec=300,  # 5 minutes
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Internal Bot: failed to store job result")
