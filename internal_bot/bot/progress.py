"""
Progress event emitter.

Emits safe user-facing progress labels via frappe.publish_realtime
(Socket.io → browser) during async pipeline execution.

Only called when state["_emit_progress"] is True (async path).
The sync ask() path never sets this flag, so zero overhead there.
"""
import frappe


def emit(state: dict, node_name: str, label: str) -> None:
    """
    Publish a bot_progress event to the requesting user's socket room.

    The event is routed to the user's room only — other users never see it.
    This function never raises: any failure is silently logged so it cannot
    interrupt the pipeline.
    """
    try:
        user = state.get("user") or frappe.session.user
        session_name = state.get("session_name") or ""
        job_id = state.get("_job_id") or ""
        attempt = state.get("query_generation_attempts") or 0

        frappe.publish_realtime(
            event="bot_progress",
            message={
                "job_id": job_id,
                "session_id": session_name,
                "node": node_name,
                "label": label,
                "attempt": attempt,
                "is_complete": False,
                "is_error": False,
                "response": None,
            },
            user=user,
        )
    except Exception:
        # Progress emission must never break the pipeline
        frappe.log_error(frappe.get_traceback(), "Internal Bot: progress emit failed")


def emit_complete(state: dict, response: dict) -> None:
    """Publish the final completion event carrying the full formatted response."""
    try:
        user = state.get("user") or frappe.session.user
        session_name = state.get("session_name") or ""
        job_id = state.get("_job_id") or ""

        frappe.publish_realtime(
            event="bot_progress",
            message={
                "job_id": job_id,
                "session_id": session_name,
                "node": "complete",
                "label": "",
                "attempt": 0,
                "is_complete": True,
                "is_error": False,
                "response": response,
            },
            user=user,
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Internal Bot: progress emit_complete failed")


def emit_error(state: dict, user: str = None) -> None:
    """Publish an error event with a safe user-facing message."""
    try:
        _user = user or state.get("user") or frappe.session.user
        session_name = state.get("session_name") or ""
        job_id = state.get("_job_id") or ""

        frappe.publish_realtime(
            event="bot_progress",
            message={
                "job_id": job_id,
                "session_id": session_name,
                "node": "error",
                "label": "Something went wrong",
                "attempt": 0,
                "is_complete": False,
                "is_error": True,
                "response": None,
            },
            user=_user,
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Internal Bot: progress emit_error failed")
