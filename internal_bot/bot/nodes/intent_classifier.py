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
from internal_bot.bot import progress, trace


_SENSITIVE_KEYWORDS = [
	"salary", "payroll", "leave", "attendance", "appraisal",
	"tax exemption", "employee advance", "expense claim",
	"personal", "private", "confidential","employee"
]

_INTENT_SYSTEM_PROMPT = """You are a query classifier for an internal ERP support chatbot.

Classify the user's message into exactly one of four intents:
  - "greeting": a conversational message that needs no data (hi, hello, thanks, bye, etc.)
  - "query": a valid, answerable ERP data question, OR a short answer to a previous clarification question
  - "clarification_needed": the message is ambiguous with NO preceding clarification question
  - "blocked": the question asks about sensitive HR, payroll, salary, personal employee data

## IMPORTANT — conversation context rule:
If the conversation history shows the assistant just asked a clarification question
(e.g. "Which document?", "For which period?"), then the user's reply — even a short
one like "Sales Invoice", "This month", or "2024" — is an ANSWER to that question
and MUST be classified as "query". Never classify a direct answer to a clarification
question as "clarification_needed".

## Other rules:
- Greetings, pleasantries, small-talk, or thanks → "greeting"
- Any question about salary, payslips, payroll, employee private data → "blocked"
- Vague message with no conversation context → "clarification_needed"
- Everything else → "query"

Respond in valid JSON only (no Markdown, no extra text):
{
  "intent": "greeting|query|clarification_needed|blocked",
  "normalized_question": "<cleaned lowercase version of the full question, incorporating context from history if this is a clarification answer>",
  "reason": "<friendly reply if greeting, brief reason if blocked or clarification_needed, else empty string>",
  "clarification_options": []
}"""


def run(state: GraphState) -> dict:
	t0 = time.monotonic()
	node_name = "intent_classifier"
	log_t0 = trace.node_start(state, node_name)
	if state.get("_emit_progress"):
		progress.emit(state, node_name, "Understanding your request")

	raw = (state.get("raw_message") or "").strip()
	llm_client = state.get("_llm_client")  # injected by graph entry
	trace.detail(state, "Question", raw)

	# Fast-path: local blocked keyword check before hitting the LLM
	raw_lower = raw.lower()
	for kw in _SENSITIVE_KEYWORDS:
		if kw in raw_lower:
			trace.detail(state, "Blocked keyword matched", kw)
			return _update(state, node_name, t0, {
				"intent": "blocked",
				"intent_reason": "This request touches restricted HR/payroll data.",
				"normalized_question": _normalize(raw),
				"clarification_options": [],
			}, log_t0)

	# Let the LLM decide greeting vs query so mixed messages like
	# "hi tell me number of sales invoice" are not short-circuited.
	if llm_client:
		try:
			# Include recent history so the LLM recognises clarification answers
			history = (state.get("chat_history") or [])[-4:]
			messages = [{"role": "system", "content": _INTENT_SYSTEM_PROMPT}]
			messages.extend({"role": m["role"], "content": m["content"]} for m in history)
			messages.append({"role": "user", "content": raw})

			response_text = llm_client.chat_completion(
				messages=messages,
				temperature=0.0,
				max_tokens=300,
			)
			parsed = json.loads(_strip_fences(response_text))
			intent = parsed.get("intent", "query")
			normalized = parsed.get("normalized_question") or _normalize(raw)
			reason = parsed.get("reason", "")
			options = parsed.get("clarification_options", [])
			trace.detail(state, "LLM intent", intent)
		except Exception as exc:
			# LLM parse failure → fall back to treating as a query
			frappe.log_error(message=str(exc), title="IntentParser LLM error")
			intent = "query"
			normalized = _normalize(raw)
			reason = ""
			options = []
			trace.detail(state, "LLM classification failed, falling back to query", str(exc))
	else:
		# No LLM available (e.g. tests without a configured provider)
		intent = "query"
		normalized = _normalize(raw)
		reason = ""
		options = []
		trace.detail(state, "No LLM client, defaulting intent", intent)

	return _update(state, node_name, t0, {
		"intent": intent,
		"intent_reason": reason,
		"normalized_question": normalized,
		"clarification_options": options,
	}, log_t0)


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


def _update(state: GraphState, node_name: str, t0: float, updates: dict, log_t0: float) -> dict:
	elapsed = round((time.monotonic() - t0) * 1000, 2)
	trace = list(state.get("node_trace") or []) + [node_name]
	timing = dict(state.get("timing") or {})
	timing[node_name] = elapsed
	from internal_bot.bot import trace as bench_trace
	bench_trace.node_end(state, node_name, log_t0)
	return {**updates, "node_trace": trace, "timing": timing}
