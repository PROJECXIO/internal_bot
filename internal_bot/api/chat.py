"""
POST /api/method/internal_bot.api.chat.ask

The single public API endpoint for the Internal Bot.

Request body (JSON):
  {
    "message":    "show sales today",
    "session_id": "optional – ignored in Phase 1 (one session per user)",
    "debug":      true
  }

Response: see API contract in the implementation plan.
"""
import os
import time
from pathlib import Path

import frappe
from dotenv import load_dotenv
from frappe import _

from internal_bot.bot.graph import get_graph
from internal_bot.bot.services.llm_client import get_llm_client

# Load LangSmith (and other) env vars from the app-level .env file.
# This runs once per worker process when the module is first imported.
_ENV_FILE = Path(__file__).parents[2] / ".env"
load_dotenv(_ENV_FILE, override=False)


@frappe.whitelist(methods=["POST"])
def ask(message: str, session_id: str = None, debug: bool = False):  # noqa: ARG001
	"""
	Main chat endpoint. Requires an authenticated Frappe session.
	session_id is accepted but ignored in Phase 1 — one session per user.
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

	# Get or create the single session for this user
	session_name = _get_or_create_session(user)

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
	initial_state = {
		"user": user,
		"raw_message": message.strip(),
		"session_name": session_name,
		"debug": bool(debug),
		"max_rows": settings.max_result_rows or 100,
		"start_time": time.monotonic(),
		"node_trace": [],
		"timing": {},
		"sql_generation_attempts": 0,
		"retries": 0,
		"cache_hit": False,
		"input_tokens": 0,
		"output_tokens": 0,
		"result_row_count": 0,
		# Inject shared objects into state so nodes don't need to re-instantiate
		"_llm_client": llm_client,
		"_settings": settings,
	}

	# Run the LangGraph pipeline
	try:
		graph = get_graph()
		final_state = graph.invoke(initial_state)
		return final_state.get("formatted_response") or {
			"status": "error",
			"reason": "No response generated.",
			"meta": {"confidence": 0.0},
		}
	except Exception as exc:
		frappe.log_error(message=frappe.get_traceback(), title="Internal Bot: graph invoke failed")
		return {
			"status": "error",
			"reason": "An internal error occurred. Please try again.",
			"meta": {"confidence": 0.0, "error_detail": str(exc)},
		}


# ──────────────────────────────────────────────────────────────────
# Session management
# ──────────────────────────────────────────────────────────────────


def _get_or_create_session(user: str) -> str:
	"""
	Return the existing AI Chat Session name for the user, or create one.
	Session name == user email (enforces one-session-per-user).
	"""
	if frappe.db.exists("AI Chat Session", user):
		return user

	doc = frappe.get_doc(
		{
			"doctype": "AI Chat Session",
			"name": user,  # explicit name — matches autoname "field:user"
			"user": user,
			"is_active": 1,
			"total_messages": 0,
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return user
