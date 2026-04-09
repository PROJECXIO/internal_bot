import re

import frappe


_LANGUAGE_ALIASES = {
	"ar": "ar",
	"arabic": "ar",
	"العربية": "ar",
	"arabic language": "ar",
	"en": "en",
	"english": "en",
	"english us": "en",
	"english uk": "en",
}

_STANDARD_PERIOD_OPTIONS = {
	"all dates",
	"this month",
	"last month",
	"this year",
	"last year",
	"last 30 days",
	"custom range",
}

_TRANSLATION_SYSTEM_PROMPT = """You translate short ERP assistant messages.

Rules:
- Return only the translated text.
- Preserve ERP DocType names such as Sales Invoice, Sales Order, and Quotation.
- Keep the tone concise and professional.
- Do not add explanations or quotes.
"""


def normalize_language_code(value: str | None) -> str:
	raw = (value or "").strip()
	if not raw:
		return ""

	lower = raw.lower().replace("_", "-")
	if lower in _LANGUAGE_ALIASES:
		return _LANGUAGE_ALIASES[lower]

	match = re.match(r"^([a-z]{2,3})(?:-[a-z0-9]+)?$", lower)
	if match:
		return match.group(1)

	return ""


def language_name_for_prompt(language_code: str | None) -> str:
	code = normalize_language_code(language_code) or (language_code or "").strip().lower()
	if code == "ar":
		return "Arabic"
	if code == "en":
		return "English"
	if code:
		return f"language code '{code}'"
	return "English"


def get_user_profile_language(user: str | None) -> str:
	if not user or user == "Guest":
		return ""

	try:
		user_language = frappe.db.get_value("User", user, "language")
		if not user_language:
			return ""

		language_code = frappe.db.get_value("Language", user_language, "language_code")
		return normalize_language_code(language_code or user_language)
	except Exception:
		return ""


def detect_message_language(text: str | None) -> str:
	value = (text or "").strip()
	if not value:
		return ""

	arabic_count = len(re.findall(r"[\u0600-\u06FF]", value))
	latin_count = len(re.findall(r"[A-Za-z]", value))

	if arabic_count and not latin_count:
		return "ar"
	if latin_count and not arabic_count:
		return "en"
	return ""


def resolve_response_language(
	raw_message: str | None,
	detected_language: str | None = None,
	user_profile_language: str | None = None,
) -> tuple[str, str]:
	message_language = normalize_language_code(detected_language) or detect_message_language(raw_message)
	if message_language:
		return message_language, "message"

	profile_language = normalize_language_code(user_profile_language)
	if profile_language:
		return profile_language, "profile"

	return "en", "default"


def localize_text(
	text: str | None,
	target_language: str | None,
	llm_client=None,
	trace_context: dict | None = None,
) -> tuple[str, int, int]:
	value = (text or "").strip()
	language = normalize_language_code(target_language) or "en"
	if not value or language == "en":
		return value, 0, 0
	if detect_message_language(value) == language:
		return value, 0, 0
	if llm_client is None:
		return value, 0, 0

	messages = [
		{"role": "system", "content": _TRANSLATION_SYSTEM_PROMPT},
		{
			"role": "user",
			"content": (
				f"Target language: {language_name_for_prompt(language)}\n"
				f"Text: {value}"
			),
		},
	]
	try:
		translated = (llm_client.chat_completion(
			messages,
			temperature=0.0,
			max_tokens=120,
			**(trace_context or {}),
		) or "").strip()
		if not translated:
			return value, 0, 0
		return (
			translated,
			getattr(llm_client, "last_input_tokens", 0) or 0,
			getattr(llm_client, "last_output_tokens", 0) or 0,
		)
	except Exception:
		return value, 0, 0


def localize_period_options(
	options: list[str] | None,
	language_code: str | None,
	llm_client=None,
	trace_context: dict | None = None,
) -> tuple[list[str], int, int]:
	entries = list(options or [])
	language = normalize_language_code(language_code) or "en"
	if language == "en":
		return entries, 0, 0
	if not entries:
		return [], 0, 0
	if any((option or "").strip().lower() not in _STANDARD_PERIOD_OPTIONS for option in entries):
		return entries, 0, 0

	localized: list[str] = []
	input_tokens = 0
	output_tokens = 0
	for option in entries:
		translated, in_tokens, out_tokens = localize_text(
			option,
			language,
			llm_client=llm_client,
			trace_context=trace_context,
		)
		localized.append(translated or option)
		input_tokens += in_tokens
		output_tokens += out_tokens

	return localized, input_tokens, output_tokens
