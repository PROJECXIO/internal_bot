import json
import re
from typing import TYPE_CHECKING

import frappe
import frappe.utils

if TYPE_CHECKING:
	from internal_bot.bot.services.llm_client import LLMClient


_FOLLOW_UP_PATTERNS = (
	r"\b(analy[sz]e|analysis|explain|interpret|summari[sz]e|break down)\b",
	r"\b(this|that|these|those)\s+(data|result|results|chart|table|numbers)\b",
	r"\b(more|further|deeper)\b",
)


def load_chat_memory(session_name: str, window_size: int) -> dict:
	"""Return last N messages and the current rolling summary for the session."""
	session = frappe.get_doc("AI Chat Session", session_name)

	recent_messages = frappe.get_all(
		"AI Chat Message",
		filters={"session": session_name, "role": ["in", ["user", "assistant"]]},
		fields=["role", "content", "creation", "structured_response", "discovered_entities", "normalized_question"],
		order_by="creation desc",
		limit=window_size,
	)
	messages = list(reversed(recent_messages))
	last_user_question = ""
	last_non_follow_up_user_question = ""
	last_assistant_response = {}
	last_assistant_context_text = ""
	last_discovered_doctypes = []

	for msg in reversed(messages):
		if msg.role == "assistant" and not last_assistant_response:
			if msg.structured_response:
				try:
					last_assistant_response = frappe.parse_json(msg.structured_response) or {}
				except Exception:
					last_assistant_response = {}
			last_assistant_context_text = _build_response_context_text(last_assistant_response)
			if msg.discovered_entities:
				try:
					last_discovered_doctypes = frappe.parse_json(msg.discovered_entities) or []
				except Exception:
					last_discovered_doctypes = []
		elif msg.role == "user" and not last_user_question:
			last_user_question = msg.normalized_question or msg.content or ""
		if msg.role == "user" and not last_non_follow_up_user_question:
			candidate = msg.normalized_question or msg.content or ""
			if candidate and not _looks_like_follow_up(candidate):
				last_non_follow_up_user_question = candidate

	return {
		"messages": [{"role": m.role, "content": m.content} for m in messages],
		"summary": session.memory_summary or "",
		"total_messages": session.total_messages or 0,
		"last_user_question": last_user_question,
		"last_non_follow_up_user_question": last_non_follow_up_user_question or last_user_question,
		"last_assistant_response": last_assistant_response,
		"last_assistant_context_text": last_assistant_context_text,
		"last_discovered_doctypes": last_discovered_doctypes,
	}


def save_message(
	session_name: str,
	role: str,
	content: str,
	status: str = "success",
	**debug_fields,
) -> str:
	"""Insert an AI Chat Message and increment total_messages on the session."""
	user = frappe.session.user

	msg = frappe.get_doc(
		{
			"doctype": "AI Chat Message",
			"session": session_name,
			"user": user,
			"role": role,
			"content": content,
			"status": status,
			"normalized_question": debug_fields.get("normalized_question"),
			"structured_response": debug_fields.get("structured_response"),
			"discovered_entities": debug_fields.get("discovered_entities"),
			"generated_sql": debug_fields.get("generated_sql"),
			"validated_sql": debug_fields.get("validated_sql"),
			"cache_hit": debug_fields.get("cache_hit", 0),
			"retries": debug_fields.get("retries", 0),
			"response_time_ms": debug_fields.get("response_time_ms"),
			"llm_provider": debug_fields.get("llm_provider"),
			"llm_model": debug_fields.get("llm_model"),
			"node_trace": json.dumps(debug_fields.get("node_trace", [])),
			"error_detail": debug_fields.get("error_detail"),
		}
	)
	msg.insert(ignore_permissions=True)

	# Increment total_messages on the session using db_set to avoid full save overhead.
	# update_modified=True so the session bubbles to the top of the sidebar list.
	frappe.db.set_value(
		"AI Chat Session",
		session_name,
		"total_messages",
		(frappe.db.get_value("AI Chat Session", session_name, "total_messages") or 0) + 1,
	)

	return msg.name


def maybe_update_summary(
	session_name: str,
	threshold: int,
	llm_client: "LLMClient",
	trace_metadata: dict | None = None,
	trace_tags: list[str] | None = None,
) -> bool:
	"""
	Re-generate the rolling summary if total_messages >= threshold and enough
	messages have accumulated since the last summary.
	Returns True if the summary was updated.
	"""
	session = frappe.get_doc("AI Chat Session", session_name)
	total = session.total_messages or 0

	if total < threshold:
		return False

	# Only re-summarise when at least threshold/2 new messages arrived since last time
	last_summarized = session.last_summarized_at
	if last_summarized:
		messages_since = frappe.db.count(
			"AI Chat Message",
			filters={"session": session_name, "creation": [">", last_summarized]},
		)
		if messages_since < max(threshold // 2, 5):
			return False

	# Fetch all messages for summarization (up to 100 most recent)
	all_msgs = frappe.get_all(
		"AI Chat Message",
		filters={"session": session_name, "role": ["in", ["user", "assistant"]]},
		fields=["role", "content"],
		order_by="creation asc",
		limit=100,
	)

	if not all_msgs:
		return False

	history_text = "\n".join(f"{m.role.upper()}: {m.content}" for m in all_msgs)
	existing_summary = session.memory_summary or ""

	prompt_messages = [
		{
			"role": "system",
			"content": (
				"You are a conversation summarizer. Produce a concise summary (max 300 words) "
				"of the following chat history. Focus on what data was queried and key results. "
				"If there is an existing summary, incorporate it."
			),
		},
		{
			"role": "user",
			"content": (
				f"Existing summary:\n{existing_summary}\n\nNew conversation:\n{history_text}\n\n"
				"Produce an updated summary:"
			),
		},
	]

	new_summary = llm_client.chat_completion(
		prompt_messages,
		temperature=0.0,
		max_tokens=500,
		trace_metadata=trace_metadata,
		trace_tags=trace_tags,
	)

	frappe.db.set_value(
		"AI Chat Session",
		session_name,
		{
			"memory_summary": new_summary,
			"last_summarized_at": frappe.utils.now_datetime(),
		},
	)
	return True


def _looks_like_follow_up(text: str) -> bool:
	normalized = re.sub(r"\s+", " ", (text or "").lower()).strip()
	return any(re.search(pattern, normalized) for pattern in _FOLLOW_UP_PATTERNS)


def _build_response_context_text(response: dict) -> str:
	if not response:
		return ""

	parts = []
	title = response.get("title")
	if title:
		parts.append(f"Title: {title}")

	summary = response.get("summary")
	if summary:
		parts.append(f"Summary: {summary}")

	columns = response.get("columns") or []
	if columns:
		parts.append(f"Columns: {columns}")

	rows = response.get("rows") or []
	if rows:
		parts.append(f"Rows (up to 10): {rows[:10]}")

	markdown = response.get("markdown")
	if markdown:
		parts.append(f"Narrative: {markdown}")

	return "\n".join(parts)
