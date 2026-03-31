"""
Node 1 — Intent Parser

Classifies the user's message as one of:
  query               — a valid business data question
  clarification_needed — ambiguous, needs more info
  blocked             — touches restricted/sensitive data

Also produces a normalized (lowercased, punctuation-stripped) question
for consistent downstream processing and cache lookups.
"""
import json
import time

import frappe

from internal_bot.bot.state import GraphState
from internal_bot.bot import progress


_SENSITIVE_KEYWORDS = [
	"salary", "payroll", "leave", "attendance", "appraisal",
	"tax exemption", "employee advance", "expense claim",
	"personal", "private", "confidential","employee"
]

_INTENT_SYSTEM_PROMPT = """You are a query classifier for an internal ERP support chatbot.

Classify the user's question into exactly one of four intents:
  - "greeting": a conversational message that needs no data (hi, hello, how are you, thanks, bye, etc.)
  - "query": a valid, answerable ERP data question (sales, purchases, inventory, customers, etc.)
  - "clarification_needed": the question is ambiguous and needs more detail
  - "blocked": the question asks about sensitive HR, payroll, salary, personal employee data

Rules:
- Greetings, pleasantries, small-talk, or thanks → "greeting"
- Any question about salary, payslips, payroll, employee private data → "blocked"
- Vague one-word inputs like "help", "what" (not greetings) → "clarification_needed"
- Everything else → "query"

Respond in valid JSON only (no Markdown, no extra text):
{
  "intent": "greeting|query|clarification_needed|blocked",
  "normalized_question": "<cleaned lowercase version of the question>",
  "reason": "<friendly conversational reply if greeting, brief reason if blocked or clarification_needed, else empty string>",
  "clarification_options": ["option1", "option2"]  // only if clarification_needed
}"""


def run(state: GraphState) -> dict:
	t0 = time.monotonic()
	node_name = "intent_parser"
	if state.get("_emit_progress"):
		progress.emit(state, node_name, "Understanding your request")

	raw = (state.get("raw_message") or "").strip()
	llm_client = state.get("_llm_client")  # injected by graph entry

	# Fast-path: local blocked keyword check before hitting the LLM
	raw_lower = raw.lower()
	for kw in _SENSITIVE_KEYWORDS:
		if kw in raw_lower:
			return _update(state, node_name, t0, {
				"intent": "blocked",
				"intent_reason": "This request touches restricted HR/payroll data.",
				"normalized_question": _normalize(raw),
				"clarification_options": [],
			})

	# Fast-path: detect simple greetings locally to save an LLM call
	_GREETING_TOKENS = {"hi", "hello", "hey", "howdy", "greetings", "bye", "goodbye",
		"thanks", "thank you", "cheers", "good morning", "good afternoon",
		"good evening", "how are you", "what's up", "sup"}
	if raw_lower.strip("!., ") in _GREETING_TOKENS or raw_lower.strip("!., ").startswith(
		("hi ", "hello ", "hey ", "thanks ", "thank you")
	):
		return _update(state, node_name, t0, {
			"intent": "greeting",
			"intent_reason": "Hello! How can I help you today?",
			"normalized_question": _normalize(raw),
			"clarification_options": [],
		})

	# LLM classification
	if llm_client:
		try:
			response_text = llm_client.chat_completion(
				messages=[
					{"role": "system", "content": _INTENT_SYSTEM_PROMPT},
					{"role": "user", "content": raw},
				],
				temperature=0.0,
				max_tokens=300,
			)
			parsed = json.loads(_strip_fences(response_text))
			intent = parsed.get("intent", "query")
			normalized = parsed.get("normalized_question") or _normalize(raw)
			reason = parsed.get("reason", "")
			options = parsed.get("clarification_options", [])
		except Exception as exc:
			# LLM parse failure → fall back to treating as a query
			frappe.log_error(message=str(exc), title="IntentParser LLM error")
			intent = "query"
			normalized = _normalize(raw)
			reason = ""
			options = []
	else:
		# No LLM available (e.g. tests without a configured provider)
		intent = "query"
		normalized = _normalize(raw)
		reason = ""
		options = []

	return _update(state, node_name, t0, {
		"intent": intent,
		"intent_reason": reason,
		"normalized_question": normalized,
		"clarification_options": options,
	})


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _normalize(text: str) -> str:
	import re
	text = text.lower().strip()
	text = re.sub(r"[^\w\s]", " ", text)
	text = re.sub(r"\s+", " ", text)
	return text.strip()


def _strip_fences(text: str) -> str:
	import re
	m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
	return m.group(1).strip() if m else text.strip()


def _update(state: GraphState, node_name: str, t0: float, updates: dict) -> dict:
	elapsed = round((time.monotonic() - t0) * 1000, 2)
	trace = list(state.get("node_trace") or []) + [node_name]
	timing = dict(state.get("timing") or {})
	timing[node_name] = elapsed
	return {**updates, "node_trace": trace, "timing": timing}
