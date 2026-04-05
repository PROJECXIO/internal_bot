"""
POST /api/method/internal_bot.api.chat.ask

The single public API endpoint for the Internal Bot.

Request body (JSON):
  {
    "message":    "show sales today",
    "session_id": "optional – AI Chat Session name",
    "debug":      true
  }

Response: see API contract in the implementation plan.
"""
import os
import time
import uuid
from pathlib import Path

import frappe
from dotenv import load_dotenv
from frappe import _

from internal_bot.bot.graph import get_graph
from internal_bot.bot.services.formatter import normalize_cached_response
from internal_bot.bot.services.llm_client import get_llm_client
from internal_bot.bot import trace

# Load LangSmith (and other) env vars from the app-level .env file.
# This runs once per worker process when the module is first imported.
_ENV_FILE = Path(__file__).parents[2] / ".env"
load_dotenv(_ENV_FILE, override=False)


@frappe.whitelist(methods=["POST"])
def ask(message: str, session_id: str = None, debug: bool = False):
	"""
	Main chat endpoint. Requires an authenticated Frappe session.
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("You must be logged in to use the chat."), frappe.AuthenticationError)

	if not message or not message.strip():
		return {
			"status": "error",
			"reason": "Message cannot be empty.",
			"meta": {"confidence": 0.0},
		}

	session_name = _get_or_create_session(user, session_id=session_id)

	# Load provider settings (raises if not configured)
	try:
		settings = frappe.get_doc("AI Provider Settings")
	except Exception:
		return {
			"status": "error",
			"reason": "AI Provider is not configured. Please ask your system administrator.",
			"meta": {"confidence": 0.0},
		}

	# Build LLM client
	try:
		llm_client = get_llm_client()
	except Exception as exc:
		frappe.log_error(message=str(exc), title="Internal Bot: LLM client init failed")
		return {
			"status": "error",
			"reason": "Could not initialise the AI provider. Please check your settings.",
			"meta": {"confidence": 0.0},
		}

	# Build initial state
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
		"start_time": time.monotonic(),
		"node_trace": [],
		"timing": {},
		"query_generation_attempts": 0,
		"retries": 0,
		"cache_hit": False,
		"input_tokens": 0,
		"output_tokens": 0,
		"result_row_count": 0,
		"answer_markdown": "",
		# Inject shared objects into state so nodes don't need to re-instantiate
		"_llm_client": llm_client,
		"_settings": settings,
	}

	# Run the LangGraph pipeline
	try:
		trace.request_start(
			initial_state,
			[
				f'Question: "{message.strip()}"',
				f"Session: {session_name}",
				"Invoking graph...",
			],
		)
		graph = get_graph()
		final_state = graph.invoke(
			initial_state,
			config=trace.graph_invoke_config(initial_state, run_name="internal_bot.ask"),
		)
		response = final_state.get("formatted_response") or {
			"status": "error",
			"reason": "No response generated.",
			"meta": {"confidence": 0.0},
		}
		response["session_id"] = session_name
		trace.request_complete(final_state, response)
		trace.flush_langsmith()
		return response
	except Exception as exc:
		frappe.log_error(message=frappe.get_traceback(), title="Internal Bot: graph invoke failed")
		trace.request_error(initial_state, str(exc))
		trace.flush_langsmith()
		return {
			"status": "error",
			"reason": "An internal error occurred. Please try again.",
			"meta": {"confidence": 0.0, "error_detail": str(exc)},
			"session_id": session_name,
		}


# ──────────────────────────────────────────────────────────────────
# Async chat endpoints
# ──────────────────────────────────────────────────────────────────


@frappe.whitelist(methods=["POST"])
def ask_async(message: str, session_id: str = None, debug: bool = False):
    """
    Async chat endpoint. Returns immediately with a job_id.

    The pipeline runs in a background RQ worker. Progress events are
    pushed to the browser via frappe.publish_realtime (Socket.io).
    The final response arrives as a bot_progress event with is_complete=True.

    Use ask_status(job_id) as a polling fallback if Socket.io is unavailable.
    """
    user = frappe.session.user
    if not user or user == "Guest":
        frappe.throw(_("You must be logged in to use the chat."), frappe.AuthenticationError)

    if not message or not message.strip():
        return {
            "status": "error",
            "reason": "Message cannot be empty.",
        }

    session_name = _get_or_create_session(user, session_id=session_id)
    job_id = str(uuid.uuid4())

    frappe.enqueue(
        "internal_bot.bot.pipeline_job.run_pipeline_job",
        queue="default",
        timeout=120,
        job_id=job_id,          # sets RQ's own job ID for deduplication/lookup
        user=user,
        message=message.strip(),
        session_name=session_name,
        pipeline_job_id=job_id,  # forwarded to run_pipeline_job() for progress/cache keys
        debug=bool(debug),
    )

    return {
        "status": "queued",
        "job_id": job_id,
        "session_id": session_name,
    }


@frappe.whitelist()
def ask_status(job_id: str):
    """
    Polling fallback for ask_async(). Returns the job result if available.

    Use this when Socket.io events cannot be received (e.g. proxy that blocks
    WebSocket upgrades). Poll at ~2s intervals until status != 'running'.
    """
    user = frappe.session.user
    if not user or user == "Guest":
        frappe.throw(_("You must be logged in to use the chat."), frappe.AuthenticationError)

    if not job_id:
        return {"status": "error", "reason": "job_id is required"}

    try:
        raw = frappe.cache().get_value(f"bot_result:{job_id}")
    except Exception:
        raw = None

    if not raw:
        return {"status": "running", "response": None}

    try:
        result = frappe.parse_json(raw)
        return result
    except Exception:
        return {"status": "error", "reason": "Failed to parse job result"}


# ──────────────────────────────────────────────────────────────────
# Session management
# ──────────────────────────────────────────────────────────────────


@frappe.whitelist(methods=["POST"])
def create_session() -> dict:
	"""Create and return a new chat session for the current user."""
	user = _require_authenticated_user()
	doc = frappe.get_doc(
		{
			"doctype": "AI Chat Session",
			"user": user,
			"is_active": 1,
			"total_messages": 0,
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"session_id": doc.name, "session": _serialize_session(doc.name)}


@frappe.whitelist()
def list_sessions() -> dict:
	"""List chat sessions for the current user, newest first."""
	user = _require_authenticated_user()
	sessions = frappe.get_all(
		"AI Chat Session",
		filters={"user": user},
		fields=["name", "creation", "modified", "total_messages", "is_active"],
		order_by="modified desc",
	)
	return {
		"sessions": [_serialize_session(session["name"], session_doc=session) for session in sessions],
		"active_session_id": sessions[0]["name"] if sessions else None,
	}


@frappe.whitelist()
def get_session_history(session_id: str = None) -> dict:
	"""Return the active session id and full renderable message history."""
	user = _require_authenticated_user()
	session_name = _get_or_create_session(user, session_id=session_id)
	messages = frappe.get_all(
		"AI Chat Message",
		filters={"session": session_name, "user": user},
		fields=["role", "status", "content", "structured_response", "creation"],
		order_by="creation asc",
	)
	return {
		"session_id": session_name,
		"messages": [_deserialize_message(message) for message in messages],
	}


@frappe.whitelist(methods=["POST"])
def delete_session(session_id: str) -> dict:
	"""Permanently delete a chat session and its messages for the current user."""
	user = _require_authenticated_user()

	if not session_id or not frappe.db.exists("AI Chat Session", {"name": session_id, "user": user}):
		frappe.throw(_("Chat session not found."), frappe.DoesNotExistError)

	frappe.db.delete("AI Chat Message", {"session": session_id})
	frappe.db.delete("AI Chat Session", {"name": session_id, "user": user})
	frappe.db.commit()

	return {
		"ok": True,
		"deleted_session_id": session_id,
	}


def _get_or_create_session(user: str, session_id: str | None = None) -> str:
	"""
	Return the requested AI Chat Session for the user, or create one.
	"""
	if session_id:
		if not frappe.db.exists("AI Chat Session", {"name": session_id, "user": user}):
			frappe.throw(_("Chat session not found."), frappe.DoesNotExistError)
		return session_id

	existing = frappe.get_all(
		"AI Chat Session",
		filters={"user": user},
		fields=["name"],
		order_by="modified desc",
		limit=1,
	)
	if existing:
		return existing[0]["name"]

	doc = frappe.get_doc(
		{
			"doctype": "AI Chat Session",
			"user": user,
			"is_active": 1,
			"total_messages": 0,
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name


def _require_authenticated_user() -> str:
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("You must be logged in to use the chat."), frappe.AuthenticationError)
	return user


def _serialize_session(session_name: str, session_doc: dict | None = None) -> dict:
	session = session_doc or frappe.db.get_value(
		"AI Chat Session",
		session_name,
		["name", "creation", "modified", "total_messages", "is_active"],
		as_dict=True,
	)
	preview_rows = frappe.get_all(
		"AI Chat Message",
		{"session": session_name},
		["content", "role"],
		order_by="creation desc",
		limit=1,
	)
	preview = preview_rows[0] if preview_rows else None
	return {
		"session_id": session["name"],
		"creation": session.get("creation"),
		"modified": session.get("modified"),
		"total_messages": session.get("total_messages") or 0,
		"is_active": session.get("is_active") or 0,
		"preview": (preview.get("content") if preview else "") or "",
		"preview_role": (preview.get("role") if preview else "") or "",
	}


def _deserialize_message(message: dict) -> dict:
	if message.get("role") == "assistant" and message.get("structured_response"):
		try:
			payload = frappe.parse_json(message["structured_response"])
			payload = normalize_cached_response(
				payload,
				{
					"raw_message": message.get("content") or "",
					"normalized_question": payload.get("title") or "",
					"query_result_rows": payload.get("rows") or [],
					"answer_markdown": payload.get("markdown") or "",
				},
			)
			payload["role"] = "assistant"
			payload["content"] = payload.get("content") or message.get("content") or ""
			return payload
		except Exception:
			pass

	return {
		"role": message.get("role"),
		"status": message.get("status"),
		"content": message.get("content") or "",
	}
