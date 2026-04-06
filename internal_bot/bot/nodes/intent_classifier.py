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
import re
import time

import frappe

from internal_bot.bot.state import GraphState
from internal_bot.bot.services.language import (
	language_name_for_prompt,
	localize_text,
	resolve_response_language,
)
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
one like "Sales Invoice", "All dates", "This month", or "2024" — is an ANSWER to that question
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
  "detected_language": "<ISO language code such as en, ar, fr; use empty string if unclear>",
  "reason": "<friendly reply if greeting, brief reason if blocked or clarification_needed, else empty string; write it in detected_language when that language is clear>",
  "clarification_options": []
}"""

_FOLLOW_UP_PATTERNS = (
	r"\b(analy[sz]e|analysis|explain|interpret|summari[sz]e|break down)\b",
	r"\b(this|that|these|those)\s+(data|result|results|chart|table|numbers)\b",
	r"\b(more|further|deeper)\b",
)

_REFINEMENT_FOLLOW_UP_PATTERNS = (
	r"\btop\b",
	r"\bbottom\b",
	r"\bhighest\b",
	r"\blow(est)?\b",
	r"\bmost\b",
	r"\bleast\b",
	r"\bfirst\b",
	r"\bsecond\b",
	r"\bthird\b",
	r"\bthree\b",
	r"\bitem(s)?\b",
	r"\bcustomer(s)?\b",
	r"\bsupplier(s)?\b",
	r"\bimpact(ed)?\b",
	r"\beffect(ed)?\b",
	r"\bsignificant(ly)?\b",
)

_CLARIFICATION_CORRECTION_PREFIXES = (
	"no i mean",
	"i mean",
	"actually",
	"rather",
	"لا قصدي",
	"لا اقصد",
	"لا اقصد ان",
	"قصدي",
	"اقصد",
	"اقصد ان",
	"يعني",
	"المقصود",
)


def run(state: GraphState) -> dict:
	t0 = time.monotonic()
	node_name = "intent_classifier"
	log_t0 = trace.node_start(state, node_name)
	if state.get("_emit_progress"):
		progress.emit(state, node_name, "Understanding your request")

	raw = (state.get("raw_message") or "").strip()
	llm_client = state.get("_llm_client")  # injected by graph entry
	trace.detail(state, "Question", raw)

	clarification_answer = _build_clarification_answer_query(state, raw)
	response_language, response_language_source = resolve_response_language(
		raw,
		user_profile_language=state.get("user_profile_language"),
	)
	if clarification_answer:
		trace.detail(state, "Clarification answer detected", clarification_answer)
		return _update(state, node_name, t0, {
			"intent": "query",
			"intent_reason": "",
			"normalized_question": clarification_answer,
			"clarification_options": [],
			"response_language": response_language,
			"response_language_source": response_language_source,
			# Keep clarification answers in the same query thread so schema
			# discovery can boost the prior DocType context if available.
			"follow_up_to_previous_result": True,
		}, log_t0)

	follow_up_normalized = _build_follow_up_question(state, raw)
	if follow_up_normalized:
		trace.detail(state, "Follow-up detected", follow_up_normalized)
		return _update(state, node_name, t0, {
			"intent": "query",
			"intent_reason": "",
			"normalized_question": follow_up_normalized,
			"clarification_options": [],
			"response_language": response_language,
			"response_language_source": response_language_source,
			"follow_up_to_previous_result": True,
		}, log_t0)

	# Fast-path: local blocked keyword check before hitting the LLM
	raw_lower = raw.lower()
	for kw in _SENSITIVE_KEYWORDS:
		if kw in raw_lower:
			trace.detail(state, "Blocked keyword matched", kw)
			blocked_reason, _, _ = localize_text(
				"This request touches restricted HR/payroll data.",
				response_language,
				llm_client=llm_client,
				trace_context=trace.llm_trace_context(state, node_name, "localize_blocked_reason"),
			)
			return _update(state, node_name, t0, {
				"intent": "blocked",
				"intent_reason": blocked_reason,
				"normalized_question": _normalize(raw),
				"clarification_options": [],
				"response_language": response_language,
				"response_language_source": response_language_source,
			}, log_t0)

	# Let the LLM decide greeting vs query so mixed messages like
	# "hi tell me number of sales invoice" are not short-circuited.
	if llm_client:
		try:
			# Include recent history so the LLM recognises clarification answers
			history = (state.get("chat_history") or [])[-4:]
			messages = [{"role": "system", "content": _INTENT_SYSTEM_PROMPT}]
			if state.get("current_date") or state.get("current_day_name") or state.get("current_year"):
				messages.append(
					{
						"role": "system",
						"content": (
							"Current request date context:\n"
							f"- Date: {state.get('current_date') or ''}\n"
							f"- Day: {state.get('current_day_name') or ''}\n"
							f"- Year: {state.get('current_year') or ''}"
						),
					}
				)
			messages.append(
				{
					"role": "system",
					"content": (
						"Language handling:\n"
						f"- Prefer replying in the user's language when clear.\n"
						f"- Current fallback language: {language_name_for_prompt(state.get('user_profile_language') or 'en')}.\n"
						"- Set detected_language to an ISO language code like en, ar, or fr.\n"
						"- If the message language is unclear, set detected_language to an empty string."
					),
				}
			)
			messages.extend({"role": m["role"], "content": m["content"]} for m in history)
			if state.get("last_assistant_context_text"):
				messages.append(
					{
						"role": "system",
						"content": "Last structured result context:\n" + state["last_assistant_context_text"],
					}
				)
			messages.append({"role": "user", "content": raw})

			response_text = llm_client.chat_completion(
				messages=messages,
				temperature=0.0,
				max_tokens=300,
				**trace.llm_trace_context(state, node_name, "classify_intent"),
			)
			input_tokens = (state.get("input_tokens") or 0) + (
				getattr(llm_client, "last_input_tokens", 0) or 0
			)
			output_tokens = (state.get("output_tokens") or 0) + (
				getattr(llm_client, "last_output_tokens", 0) or 0
			)
			parsed = json.loads(_strip_fences(response_text))
			intent = parsed.get("intent", "query")
			normalized = parsed.get("normalized_question") or _normalize(raw)
			detected_language = parsed.get("detected_language") or ""
			response_language, response_language_source = resolve_response_language(
				raw,
				detected_language=detected_language,
				user_profile_language=state.get("user_profile_language"),
			)
			reason = parsed.get("reason", "")
			options = parsed.get("clarification_options", [])
			trace.detail(state, "LLM intent", intent)
			trace.detail(state, "Response language", response_language)
		except Exception as exc:
			# LLM parse failure → fall back to treating as a query
			frappe.log_error(message=str(exc), title="IntentParser LLM error")
			intent = "query"
			normalized = _normalize(raw)
			reason = ""
			options = []
			response_language, response_language_source = resolve_response_language(
				raw,
				user_profile_language=state.get("user_profile_language"),
			)
			input_tokens = (state.get("input_tokens") or 0) + (
				getattr(llm_client, "last_input_tokens", 0) or 0
			)
			output_tokens = (state.get("output_tokens") or 0) + (
				getattr(llm_client, "last_output_tokens", 0) or 0
			)
			trace.detail(state, "LLM classification failed, falling back to query", str(exc))
	else:
		# No LLM available (e.g. tests without a configured provider)
		intent = "query"
		normalized = _normalize(raw)
		reason = ""
		options = []
		response_language, response_language_source = resolve_response_language(
			raw,
			user_profile_language=state.get("user_profile_language"),
		)
		input_tokens = state.get("input_tokens") or 0
		output_tokens = state.get("output_tokens") or 0
		trace.detail(state, "No LLM client, defaulting intent", intent)

	return _update(state, node_name, t0, {
		"intent": intent,
		"intent_reason": _personalize_greeting(
			reason,
			state.get("user"),
			response_language,
			llm_client=llm_client,
		) if intent == "greeting" else reason,
		"normalized_question": normalized,
		"clarification_options": options,
		"follow_up_to_previous_result": False,
		"response_language": response_language,
		"response_language_source": response_language_source,
		"input_tokens": input_tokens,
		"output_tokens": output_tokens,
		"llm_provider": getattr(llm_client, "provider", ""),
		"llm_model": getattr(llm_client, "model", ""),
	}, log_t0)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _normalize(text: str) -> str:
	text = text.lower().strip()
	text = re.sub(r"[^\w\s]", " ", text)
	text = re.sub(r"\s+", " ", text)
	return text.strip()


def _build_clarification_answer_query(state: GraphState, raw: str) -> str:
	raw_normalized = _normalize(raw)
	if not raw_normalized or not _assistant_just_asked_for_clarification(state):
		return ""

	cleaned = _strip_clarification_prefix(raw_normalized)
	if not cleaned:
		return ""

	has_explicit_correction = cleaned != raw_normalized
	is_short_answer = len(cleaned.split()) <= 4
	matches_option = _matches_clarification_option(cleaned, state)
	if not (has_explicit_correction or is_short_answer or matches_option):
		return ""

	base_question = (
		state.get("last_non_follow_up_user_question")
		or state.get("last_user_question")
		or ""
	).strip()
	if not base_question:
		return cleaned

	# Option selections and other short clarification answers need the prior
	# question context to stay queryable.
	if (
		not has_explicit_correction
		and (matches_option or len(cleaned.split()) <= 4)
		and cleaned not in base_question
	):
		return f"{base_question} {cleaned}".strip()

	return cleaned


def _assistant_just_asked_for_clarification(state: GraphState) -> bool:
	last_assistant = state.get("last_assistant_response") or {}
	if last_assistant.get("status") == "clarification_needed":
		return True
	if last_assistant.get("question") or last_assistant.get("options"):
		return True

	history = state.get("chat_history") or []
	if not history:
		return False

	last_message = history[-1]
	if last_message.get("role") != "assistant":
		return False

	content = (last_message.get("content") or "").strip()
	return "?" in content or "؟" in content


def _strip_clarification_prefix(normalized_text: str) -> str:
	cleaned = normalized_text.strip()
	changed = True
	while changed and cleaned:
		changed = False
		for prefix in _CLARIFICATION_CORRECTION_PREFIXES:
			if cleaned.startswith(prefix + " "):
				cleaned = cleaned[len(prefix) :].strip()
				changed = True
				break
			if cleaned == prefix:
				cleaned = ""
				changed = True
				break
	return cleaned


def _matches_clarification_option(normalized_text: str, state: GraphState) -> bool:
	last_assistant = state.get("last_assistant_response") or {}
	options = last_assistant.get("options") or []
	normalized_options = {_normalize(option) for option in options if option}
	return normalized_text in normalized_options


def _build_follow_up_question(state: GraphState, raw: str) -> str:
	raw_normalized = _normalize(raw)
	if not raw_normalized:
		return ""

	last_assistant = state.get("last_assistant_response") or {}
	last_title = (last_assistant.get("title") or "").strip()
	last_question = (
		state.get("last_non_follow_up_user_question")
		or state.get("last_user_question")
		or ""
	).strip()
	base_question = last_question or _normalize(last_title)
	if not base_question:
		return ""

	if _looks_like_follow_up(raw_normalized):
		return f"analyze more the results for {base_question}"

	if _looks_like_contextual_refinement(raw_normalized, state):
		return f"{raw_normalized} based on {base_question}"

	return ""


def _looks_like_follow_up(normalized_text: str) -> bool:
	return any(re.search(pattern, normalized_text) for pattern in _FOLLOW_UP_PATTERNS)


def _looks_like_contextual_refinement(normalized_text: str, state: GraphState) -> bool:
	last_assistant = state.get("last_assistant_response") or {}
	if not last_assistant:
		return False

	words = normalized_text.split()
	if len(words) > 8:
		return False

	return any(re.search(pattern, normalized_text) for pattern in _REFINEMENT_FOLLOW_UP_PATTERNS)


def _strip_fences(text: str) -> str:
	import re
	m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
	return m.group(1).strip() if m else text.strip()


def _personalize_greeting(
	reason: str,
	user: str | None,
	response_language: str,
	llm_client=None,
) -> str:
	message = (
		reason
		or localize_text(
			"Hello! How can I help you today?",
			response_language,
			llm_client=llm_client,
		)[0]
	).strip()
	if not user or user == "Guest":
		return message

	name = _get_user_display_name(user)
	if not name:
		return message

	if name.casefold() in message.casefold():
		return message

	if not reason:
		return localize_text(
			f"Hello {name}! How can I help you today?",
			response_language,
			llm_client=llm_client,
		)[0]

	if "hello" in message.casefold():
		return re.sub(r"hello\b", f"Hello {name}", message, count=1, flags=re.IGNORECASE)

	return f"{message} {name}".strip()


def _get_user_display_name(user: str) -> str:
	try:
		full_name = (frappe.db.get_value("User", user, "full_name") or "").strip()
		if full_name:
			return full_name.split()[0]
	except Exception:
		return ""
	return ""


def _update(state: GraphState, node_name: str, t0: float, updates: dict, log_t0: float) -> dict:
	elapsed = round((time.monotonic() - t0) * 1000, 2)
	trace = list(state.get("node_trace") or []) + [node_name]
	timing = dict(state.get("timing") or {})
	timing[node_name] = elapsed
	from internal_bot.bot import trace as bench_trace
	bench_trace.node_end(state, node_name, log_t0)
	return {**updates, "node_trace": trace, "timing": timing}
