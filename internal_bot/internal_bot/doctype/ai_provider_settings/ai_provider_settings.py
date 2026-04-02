import time

import frappe
from frappe.model.document import Document


class AIProviderSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from frappe.types import DF

	api_base: DF.Data | None
	api_key: DF.Password
	api_version: DF.Data | None
	blocked_doctypes: DF.SmallText | None
	cache_ttl_hours: DF.Int
	enable_cache: DF.Check
	enable_debug_context_window: DF.Check
	max_result_rows: DF.Int
	max_tokens: DF.Int
	memory_window: DF.Int
	model: DF.Data
	provider: DF.Literal["OpenAI", "Azure OpenAI", "Anthropic", "OpenRouter"]
	request_timeout: DF.Int
	summary_threshold: DF.Int
	temperature: DF.Float
	# end: auto-generated types

	def get_blocked_doctype_list(self) -> list:
		if not self.blocked_doctypes:
			return []
		return [d.strip() for d in self.blocked_doctypes.splitlines() if d.strip()]


@frappe.whitelist()
def quick_chat(message: str):
	"""Direct LLM call — no pipeline, no SQL. For quick manual testing."""
	from internal_bot.bot.services.llm_client import get_llm_client

	if not message or not message.strip():
		return {"success": False, "error": "Message is empty.", "reply": None}

	try:
		client = get_llm_client()
	except Exception as exc:
		return {"success": False, "error": str(exc), "reply": None}

	try:
		reply = client.chat_completion(
			messages=[{"role": "user", "content": message.strip()}],
		)
		return {
			"success": True,
			"reply": reply.strip(),
			"model": client.model,
			"input_tokens": getattr(client, "last_input_tokens", 0),
			"output_tokens": getattr(client, "last_output_tokens", 0),
		}
	except Exception as exc:
		return {"success": False, "error": str(exc), "reply": None, "model": client.model}


@frappe.whitelist()
def test_connection():
	"""Send a minimal ping to the configured LLM provider and return latency."""
	from internal_bot.bot.services.llm_client import get_llm_client

	try:
		client = get_llm_client()
	except Exception as exc:
		return {"success": False, "message": f"Could not build client: {exc}", "model": None, "latency_ms": None}

	try:
		t0 = time.monotonic()
		reply = client.chat_completion(
			messages=[{"role": "user", "content": "Reply with the single word: pong"}],
			temperature=0.0,
			max_tokens=10,
		)
		latency_ms = round((time.monotonic() - t0) * 1000)
		return {
			"success": True,
			"message": reply.strip(),
			"model": client.model,
			"latency_ms": latency_ms,
		}
	except Exception as exc:
		return {"success": False, "message": str(exc), "model": client.model, "latency_ms": None}


@frappe.whitelist()
def get_chat_debug_settings():
	"""Return frontend-safe debug settings for AI Chat."""
	settings = frappe.get_doc("AI Provider Settings")
	return {
		"enable_debug_context_window": bool(settings.enable_debug_context_window),
	}
