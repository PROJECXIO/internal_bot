"""
Builds the structured JSON response returned to the frontend.
"""
from collections.abc import Sequence
import datetime
import decimal
import math
import re
from typing import TYPE_CHECKING, Any

from internal_bot.bot.services.language import localize_text

if TYPE_CHECKING:
	from internal_bot.bot.state import GraphState


_DEBUG_HISTORY_LIMIT = 3
_DEBUG_HISTORY_CONTENT_LIMIT = 1000
_DEBUG_CONTEXT_TEXT_LIMIT = 2500


def format_structured_response(state: "GraphState") -> dict:
	"""
	Convert the final graph state into the API response contract.

	Status values:
	  success               - query ran and returned data
	  clarification_needed  - intent was ambiguous
	  blocked               - request touches restricted data
	  error                 - SQL gen/exec failed after retries
	"""
	intent = state.get("intent", "query")
	debug = state.get("debug", False)
	preference = state.get("visualization_preference") or "auto"
	response_language = state.get("response_language") or state.get("user_profile_language") or "en"

	if intent == "greeting":
		greeting_default = _localized_copy(state, "greeting_default", response_language)
		response = {
			"status": "greeting",
			"message": state.get("intent_reason", greeting_default),
			"markdown": state.get("answer_markdown")
			or state.get("intent_reason")
			or greeting_default,
			"meta": {"confidence": 1.0, "confidence_label": "high"},
		}

	elif intent == "clarification_needed":
		clarify_default = _localized_copy(state, "clarify_question_default", response_language)
		response = {
			"status": "clarification_needed",
			"question": state.get("intent_reason", clarify_default),
			"options": state.get("clarification_options", []),
			"markdown": state.get("answer_markdown")
			or state.get("intent_reason")
			or clarify_default,
			"meta": {"confidence": 0.4, "confidence_label": "low"},
		}

	elif intent == "blocked":
		blocked_default = _localized_copy(state, "blocked_default", response_language)
		response = {
			"status": "blocked",
			"reason": state.get("intent_reason", blocked_default),
			"markdown": state.get("answer_markdown")
			or state.get("intent_reason")
			or blocked_default,
			"meta": {"confidence": 1.0, "confidence_label": "high"},
		}

	elif state.get("query_execution_error") or (
		not state.get("query_is_valid") and state.get("query_generation_attempts", 0) >= 3
	):
		error_msg = (
			state.get("query_execution_error")
			or state.get("query_invalid_reason", "Unknown error")
		)
		reason = _localized_copy(state, "query_error_default", response_language)
		response = {
			"status": "error",
			"reason": reason,
			"markdown": state.get("answer_markdown") or reason,
			"meta": {"confidence": 0.0, "confidence_label": "very_low", "error_detail": error_msg},
		}

	else:
		response = build_success_payload(state)
		response["status"] = "success"
		confidence = _estimate_confidence(state)
		response["meta"] = {
			"confidence": confidence,
			"confidence_label": _confidence_label(confidence),
			"has_more": len(response["rows"]) >= (state.get("max_rows") or 100),
			"returned_rows": len(response["rows"]),
		}

	if debug:
		response["debug"] = {
			"normalized_question": state.get("normalized_question"),
			"discovered_entities": state.get("discovered_doctypes", []),
			"schema_confidence": state.get("schema_confidence"),
			"schema_decision": state.get("schema_decision"),
			"schema_candidates": state.get("schema_candidates", []),
			"presentation_plan": state.get("presentation_plan"),
			"pre_query_visualization_preference": state.get("pre_query_visualization_preference"),
			"query_shape": state.get("query_shape"),
			"generated_intent": state.get("generated_intent"),
			"compiled_sql": state.get("compiled_sql"),
			"retries": state.get("query_generation_attempts", 0),
			"timing": state.get("timing", {}),
			"provider": state.get("llm_provider"),
			"model": state.get("llm_model"),
			"node_trace": state.get("node_trace", []),
			"response_type": response.get("response_type"),
			"visualization_preference": preference if intent == "query" else "auto",
			"cache_hit": state.get("cache_hit", False),
		}
		if _should_include_debug_context_window(state):
			response["debug"]["context_window"] = _build_context_window(state)
			response["debug"]["token_usage"] = _build_token_usage(state)

	return response


def build_success_payload(state: "GraphState") -> dict:
	rows = _serialize_rows(state.get("query_result_rows") or [])
	columns = list(rows[0].keys()) if rows else []
	title = _make_title(state.get("normalized_question") or state.get("raw_message", ""))
	preference = state.get("visualization_preference") or "auto"

	if _should_force_text_explanation(state, preference):
		markdown = state.get("answer_markdown") or ""
		summary = strip_markdown_to_text(markdown) or _summarize_table(rows, columns)
		return {
			"response_type": "plain_text",
			"visualization": None,
			"answer_prefix": state.get("answer_prefix") or "",
			"summary": summary,
			"markdown": markdown,
			"title": title,
			"columns": columns,
			"rows": rows,
		}

	response_type, visualization, summary = _build_success_visualization(
		state=state,
		rows=rows,
		columns=columns,
		title=title,
		preference=preference,
	)
	return {
		"response_type": response_type,
		"visualization": visualization,
		"answer_prefix": state.get("answer_prefix") or "",
		"summary": summary,
		"markdown": state.get("answer_markdown") or "",
		"title": title,
		"columns": columns,
		"rows": rows,
	}


def _should_force_text_explanation(state: "GraphState", preference: str) -> bool:
	if preference != "text":
		return False
	if not state.get("follow_up_to_previous_result"):
		return False

	last_response = state.get("last_assistant_response") or {}
	return last_response.get("response_type") in {
		"bar_chart", "pie_chart", "donut_chart", "line_chart", "area_chart",
		"stacked_bar_chart", "heatmap_chart", "metric_card", "table",
	}


def normalize_cached_response(cached_response: dict, state: "GraphState | dict | None" = None) -> dict:
	state = state or {}
	response = dict(cached_response or {})
	status = response.get("status") or "success"
	response["status"] = status

	if status != "success":
		response["markdown"] = response.get("markdown") or _markdown_from_response(response)
		return response

	legacy_state = {
		**state,
		"query_result_rows": response.get("rows") or state.get("query_result_rows") or [],
		"normalized_question": state.get("normalized_question")
		or response.get("title")
		or state.get("raw_message", ""),
		"raw_message": state.get("raw_message")
		or response.get("title")
		or state.get("normalized_question", ""),
		"answer_prefix": response.get("answer_prefix") or state.get("answer_prefix") or "",
		"answer_markdown": response.get("markdown") or state.get("answer_markdown") or "",
		"visualization_preference": state.get("visualization_preference") or "auto",
		"max_rows": state.get("max_rows") or len(response.get("rows") or []),
	}
	payload = build_success_payload(legacy_state)

	if response.get("response_type") == "table" and payload["response_type"] == "plain_text":
		response["response_type"] = payload["response_type"]
		response["visualization"] = payload["visualization"]
		response["summary"] = payload["summary"]
	elif not response.get("response_type"):
		response["response_type"] = payload["response_type"]

	if "visualization" not in response:
		response["visualization"] = payload["visualization"]
	if not response.get("summary"):
		response["summary"] = payload["summary"]
	if not response.get("title"):
		response["title"] = payload["title"]
	if "columns" not in response:
		response["columns"] = payload["columns"]
	if "rows" not in response:
		response["rows"] = payload["rows"]

	response["markdown"] = response.get("markdown") or payload.get("markdown") or ""
	response["answer_prefix"] = response.get("answer_prefix") or payload.get("answer_prefix") or ""
	return response


def strip_markdown_to_text(value: str) -> str:
	text = (value or "").strip()
	if not text:
		return ""

	text = re.sub(r"```(?:[\w+-]+)?\s*([\s\S]*?)```", r"\1", text)
	text = re.sub(r"`([^`]+)`", r"\1", text)
	text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
	text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
	text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
	text = re.sub(r"^\s*>\s?", "", text, flags=re.MULTILINE)
	text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
	text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
	text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
	text = re.sub(r"\*([^*]+)\*", r"\1", text)
	text = re.sub(r"__([^_]+)__", r"\1", text)
	text = re.sub(r"_([^_]+)_", r"\1", text)
	text = re.sub(r"\n{3,}", "\n\n", text)
	return text.strip()


def _markdown_from_response(response: dict) -> str:
	status = response.get("status")
	if status == "greeting":
		return response.get("markdown") or response.get("message") or ""
	if status == "clarification_needed":
		return response.get("markdown") or response.get("question") or ""
	if status in {"blocked", "error"}:
		return response.get("markdown") or response.get("reason") or ""
	return response.get("markdown") or ""


def _should_include_debug_context_window(state: "GraphState") -> bool:
	settings = state.get("_settings")
	return bool(getattr(settings, "enable_debug_context_window", False))


def _build_context_window(state: "GraphState") -> dict:
	full_history = [
		{
			"role": message.get("role", ""),
			"content": _truncate_debug_text(
				message.get("content", ""),
				limit=_DEBUG_HISTORY_CONTENT_LIMIT,
			),
		}
		for message in (state.get("chat_history") or [])
		if message.get("content")
	]
	history = full_history[-_DEBUG_HISTORY_LIMIT:]
	return {
		"history": history,
		"memory_summary": _truncate_debug_text(state.get("memory_summary") or ""),
		"last_result_context": _truncate_debug_text(state.get("last_assistant_context_text") or ""),
		"schema_context": _truncate_debug_text(state.get("schema_context") or ""),
		"question_context": {
			"raw_message": state.get("raw_message") or "",
			"normalized_question": state.get("normalized_question") or "",
			"follow_up_to_previous_result": bool(state.get("follow_up_to_previous_result")),
			"last_user_question": state.get("last_user_question") or "",
			"last_non_follow_up_user_question": state.get("last_non_follow_up_user_question") or "",
			"discovered_doctypes": state.get("discovered_doctypes") or [],
			"visualization_preference": state.get("visualization_preference") or "auto",
		},
	}


def _truncate_debug_text(value: str, limit: int = _DEBUG_CONTEXT_TEXT_LIMIT) -> str:
	if not value:
		return ""
	text = str(value)
	if len(text) <= limit:
		return text
	return text[: limit - 1].rstrip() + "…"


def _build_token_usage(state: "GraphState") -> dict:
	input_tokens = int(state.get("input_tokens") or 0)
	output_tokens = int(state.get("output_tokens") or 0)
	return {
		"input_tokens": input_tokens,
		"output_tokens": output_tokens,
		"total_tokens": input_tokens + output_tokens,
	}


def _make_title(question: str) -> str:
	if not question:
		return "Query Result"
	title = question.strip().rstrip("?.")
	return title[:80] if len(title) > 80 else title


def _estimate_confidence(state: "GraphState") -> float:
	base = 0.95

	# Schema quality
	decision = state.get("schema_decision", "")
	if decision == "ambiguous":
		base -= 0.15
	elif decision == "low_confidence":
		base -= 0.25
	elif decision == "no_match":
		base -= 0.40

	# Query retries
	retries = state.get("query_generation_attempts", 0)
	base -= retries * 0.10

	# Empty results
	rows = state.get("query_result_rows") or []
	if not rows:
		base -= 0.20

	# Follow-up context penalty
	if state.get("follow_up_to_previous_result"):
		base -= 0.05

	return round(max(0.05, min(1.0, base)), 2)


def _confidence_label(score: float) -> str:
	if score >= 0.85:
		return "high"
	if score >= 0.60:
		return "medium"
	if score >= 0.35:
		return "low"
	return "very_low"


def _serialize_rows(rows: list[dict]) -> list[dict]:
	result = []
	for row in rows:
		clean = {}
		for key, value in row.items():
			if isinstance(value, decimal.Decimal):
				clean[key] = float(value)
			elif isinstance(value, (datetime.date, datetime.datetime)):
				clean[key] = str(value)
			elif value is None:
				clean[key] = None
			else:
				clean[key] = value
		result.append(clean)
	return result


def _build_success_visualization(
	state: "GraphState",
	rows: list[dict],
	columns: list[str],
	title: str,
	preference: str,
) -> tuple[str, dict | None, str]:
	if not rows:
		return "empty", None, _localized_copy(
			state,
			"empty_results",
			state.get("response_language") or state.get("user_profile_language") or "en",
		)

	if preference == "text":
		plain_summary = _build_plain_summary(rows, columns)
		if plain_summary:
			return "plain_text", None, plain_summary
		return "table", None, _summarize_table(rows, columns)

	plain_answer = _build_plain_answer(rows, columns)
	if plain_answer:
		return "plain_text", None, plain_answer

	metric_payload = _build_metric_visualization(rows, columns, title)
	if metric_payload and preference in {"card", "auto"}:
		return "metric_card", metric_payload, _summarize_metric(metric_payload)

	chart_payload = _build_chart_visualization(rows, columns, title, preference)
	if chart_payload:
		return chart_payload["response_type"], chart_payload["visualization"], chart_payload["summary"]

	plain_summary = _build_plain_summary(rows, columns)
	if plain_summary:
		return "plain_text", None, plain_summary

	return "table", None, _summarize_table(rows, columns)


def _localized_copy(state: "GraphState", key: str, language_code: str, **kwargs) -> str:
	copy_by_key = {
		"greeting_default": "Hello! How can I help you today?",
		"clarify_question_default": "Could you clarify your question?",
		"blocked_default": "This request touches restricted data.",
		"query_error_default": "Could not generate a valid query. Please rephrase your question.",
		"empty_results": "I couldn't find any matching data for that request.",
	}
	return localize_text(
		copy_by_key[key],
		language_code,
		llm_client=state.get("_llm_client"),
		**kwargs,
	)[0]


def _build_plain_answer(rows: list[dict], columns: list[str]) -> str | None:
	if len(rows) != 1 or len(columns) != 1:
		return None

	value = rows[0].get(columns[0])
	if value in (None, "") or _is_numeric_value(value):
		return None

	return str(value)


def _build_metric_visualization(rows: list[dict], columns: list[str], title: str) -> dict | None:
	if len(rows) != 1 or not columns:
		return None

	row = rows[0]
	numeric_columns = [column for column in columns if _is_numeric_value(row.get(column))]
	if len(numeric_columns) != 1:
		return None

	value_key = numeric_columns[0]
	context_columns = [column for column in columns if column != value_key and row.get(column) not in (None, "")]
	if len(context_columns) > 1:
		return None

	value = row.get(value_key)
	context = ""
	if context_columns:
		context = f"{context_columns[0].replace('_', ' ').title()}: {row.get(context_columns[0])}"

	return {
		"kind": "metric",
		"label": value_key.replace("_", " ").title() or title,
		"value": value,
		"formatted_value": _format_metric_value(value),
		"context": context,
	}


def _build_chart_visualization(rows: list[dict], columns: list[str], title: str, preference: str) -> dict | None:
	if preference not in {"bar", "pie", "donut", "line", "area", "stacked_bar", "heatmap", "auto"}:
		return None

	heatmap_payload = _build_heatmap_visualization(rows, columns, title, preference)
	if heatmap_payload:
		return heatmap_payload

	if len(columns) < 2:
		return None
	if len(rows) < 2 and preference not in {"bar", "line", "area"}:
		return None

	grouped_payload = _build_grouped_chart_visualization(rows, columns, title, preference)
	if grouped_payload:
		return grouped_payload

	if len(rows) > 12 and preference not in {"line", "area"}:
		return None

	if len(columns) != 2:
		return None

	label_key, value_key = _pick_chart_axes(rows, columns)
	if not label_key or not value_key:
		return None

	categories = []
	values = []
	for row in rows:
		label = row.get(label_key)
		value = row.get(value_key)
		if label in (None, "") or not _is_numeric_value(value):
			return None
		categories.append(str(label))
		values.append(float(value))

	if all(value == 0 for value in values):
		return None

	response_type = "bar_chart"
	kind = "bar"
	if _should_use_area_chart(preference, label_key, rows, value_key):
		response_type = "area_chart"
		kind = "area"
	elif _should_use_line_chart(preference, label_key, rows):
		response_type = "line_chart"
		kind = "line"
	elif _should_use_pie_chart(preference, title, values):
		if preference == "pie":
			response_type = "pie_chart"
			kind = "pie"
		else:
			response_type = "donut_chart"
			kind = "donut"
	elif preference == "donut" and all(value >= 0 for value in values):
		response_type = "donut_chart"
		kind = "donut"

	visualization = {
		"kind": kind,
		"label_key": label_key,
		"value_key": value_key,
		"layout": _detect_bar_layout(title),
		"series": [{"name": value_key.replace("_", " ").title(), "data": values}],
		"categories": categories,
		"show_table_toggle": True,
	}
	if kind in ("pie", "donut"):
		visualization["series"] = values

	return {
		"response_type": response_type,
		"visualization": visualization,
		"summary": _summarize_chart(categories, values, value_key, kind),
	}


def _build_heatmap_visualization(rows: list[dict], columns: list[str], title: str, preference: str) -> dict | None:
	if preference != "heatmap":
		return None
	if len(columns) != 3:
		return None

	numeric_keys = [column for column in columns if _is_measure_column(rows, column)]
	if len(numeric_keys) != 1:
		return None

	value_key = numeric_keys[0]
	dimension_keys = [column for column in columns if column != value_key]
	if len(dimension_keys) != 2:
		return None

	y_key, x_key = _pick_heatmap_axes(rows, dimension_keys)
	x_labels: list[str] = []
	y_labels: list[str] = []
	values_by_y_and_x: dict[str, dict[str, float]] = {}

	for row in rows:
		x_value = row.get(x_key)
		y_value = row.get(y_key)
		metric_value = row.get(value_key)
		if x_value in (None, "") or y_value in (None, "") or not _is_numeric_value(metric_value):
			return None

		x_label = str(x_value)
		y_label = str(y_value)
		if x_label not in x_labels:
			x_labels.append(x_label)
		if y_label not in y_labels:
			y_labels.append(y_label)

		y_values = values_by_y_and_x.setdefault(y_label, {})
		y_values[x_label] = y_values.get(x_label, 0.0) + float(metric_value)

	if not x_labels or not y_labels:
		return None

	series = [
		{
			"name": y_label,
			"data": [
				{"x": x_label, "y": values_by_y_and_x.get(y_label, {}).get(x_label, 0.0)}
				for x_label in x_labels
			],
		}
		for y_label in y_labels
	]

	if not any(any(point["y"] != 0 for point in item["data"]) for item in series):
		return None

	return {
		"response_type": "heatmap_chart",
		"visualization": {
			"kind": "heatmap",
			"x_key": x_key,
			"y_key": y_key,
			"value_key": value_key,
			"series": series,
			"categories": x_labels,
			"y_categories": y_labels,
			"show_table_toggle": True,
		},
		"summary": _summarize_heatmap(x_key, y_key, value_key, series),
	}


def _build_grouped_chart_visualization(rows: list[dict], columns: list[str], title: str, preference: str) -> dict | None:
	if len(columns) < 3 or len(columns) > 6:
		return None
	if preference not in {"bar", "line", "stacked_bar"} and not _should_auto_use_grouped_chart(title):
		return None

	time_comparison_grouped_chart = _build_time_comparison_grouped_chart(rows, columns, title, preference)
	if time_comparison_grouped_chart:
		return time_comparison_grouped_chart

	year_month_category_chart = _build_year_month_category_grouped_chart(rows, columns, title, preference)
	if year_month_category_chart:
		return year_month_category_chart

	long_form_grouped_chart = _build_long_form_grouped_chart(rows, columns, title, preference)
	if long_form_grouped_chart:
		return long_form_grouped_chart

	label_key = next((column for column in columns if not _is_measure_column(rows, column)), None)
	if not label_key:
		return None

	numeric_keys = [column for column in columns if column != label_key and _is_measure_column(rows, column)]
	label_columns = [column for column in columns if column not in numeric_keys]
	# Allow multiple label columns (e.g. item_code + item_name + qty + amount):
	# use the first label column as the chart axis; extras show in table toggle.
	if len(numeric_keys) < 2 or len(label_columns) < 1:
		return None

	# If there's a secondary label column (e.g. item_name alongside item_code),
	# combine them into a richer display label: "SKU007 – Television"
	secondary_label_keys = [col for col in label_columns if col != label_key]
	use_combined_label = len(secondary_label_keys) == 1

	categories = []
	series = []
	for metric_key in numeric_keys:
		series.append({
			"name": metric_key.replace("_", " ").title(),
			"data": [],
		})

	for row in rows:
		label = row.get(label_key)
		if label in (None, ""):
			return None

		if use_combined_label:
			secondary = row.get(secondary_label_keys[0])
			if secondary not in (None, ""):
				label = f"{label} – {secondary}"
		categories.append(str(label))
		for index, metric_key in enumerate(numeric_keys):
			value = row.get(metric_key)
			if not _is_numeric_value(value):
				return None
			series[index]["data"].append(float(value))

	if not any(any(value != 0 for value in metric["data"]) for metric in series):
		return None

	kind, response_type = _pick_grouped_kind(preference, label_key, rows, len(series), len(categories))
	return {
		"response_type": response_type,
		"visualization": {
			"kind": kind,
			"layout": _detect_bar_layout(title),
			"label_key": label_key,
			"value_keys": numeric_keys,
			"series": series,
			"categories": categories,
			"show_table_toggle": True,
		},
		"summary": _summarize_grouped_chart(categories, numeric_keys, series),
	}


def _build_long_form_grouped_chart(rows: list[dict], columns: list[str], title: str, preference: str = "auto") -> dict | None:
	if len(columns) != 3:
		return None

	numeric_keys = [column for column in columns if _is_measure_column(rows, column)]
	if len(numeric_keys) != 1:
		return None

	value_key = numeric_keys[0]
	dimension_keys = [column for column in columns if column != value_key]
	if len(dimension_keys) != 2:
		return None

	label_key, series_key = _pick_long_form_grouping_keys(rows, dimension_keys, title)
	categories: list[str] = []
	series_names: list[str] = []
	values_by_series_and_category: dict[str, dict[str, float]] = {}

	for row in rows:
		category = row.get(label_key)
		series_name = row.get(series_key)
		value = row.get(value_key)
		if category in (None, "") or series_name in (None, "") or not _is_numeric_value(value):
			return None

		category_label = str(category)
		series_label = str(series_name)
		if category_label not in categories:
			categories.append(category_label)
		if series_label not in series_names:
			series_names.append(series_label)

		series_values = values_by_series_and_category.setdefault(series_label, {})
		series_values[category_label] = series_values.get(category_label, 0.0) + float(value)

	categories, values_by_series_and_category = _bucket_top_n_categories(
		categories, values_by_series_and_category, series_names,
	)
	series_names, values_by_series_and_category = _bucket_top_n_series(
		series_names, values_by_series_and_category, categories,
	)

	series = [
		{
			"name": series_name,
			"data": [values_by_series_and_category.get(series_name, {}).get(category, 0.0) for category in categories],
		}
		for series_name in series_names
	]
	if not any(any(value != 0 for value in metric["data"]) for metric in series):
		return None

	kind, response_type = _pick_grouped_kind(
		preference,
		label_key,
		rows,
		len(series),
		len(categories),
	)
	return {
		"response_type": response_type,
		"visualization": {
			"kind": kind,
			"layout": _detect_bar_layout(title),
			"label_key": label_key,
			"series_key": series_key,
			"value_key": value_key,
			"series": series,
			"categories": categories,
			"show_table_toggle": True,
		},
		"summary": _summarize_long_form_grouped_chart(categories, series_names, series, series_key),
	}


def _build_time_comparison_grouped_chart(rows: list[dict], columns: list[str], title: str, preference: str = "auto") -> dict | None:
	if len(columns) != 4:
		return None

	numeric_keys = [column for column in columns if _is_measure_column(rows, column)]
	if len(numeric_keys) != 1:
		return None

	value_key = numeric_keys[0]
	dimension_keys = [column for column in columns if column != value_key]
	if set(dimension_keys) != {"YEAR(posting_date)", "MONTH(posting_date)", "DAY(posting_date)"}:
		return None

	categories: list[str] = []
	series_names: list[str] = []
	values_by_year_and_day: dict[str, dict[str, float]] = {}

	for row in rows:
		year = row.get("YEAR(posting_date)")
		month = row.get("MONTH(posting_date)")
		day = row.get("DAY(posting_date)")
		value = row.get(value_key)
		if not all(_is_numeric_value(part) for part in (year, month, day, value)):
			return None

		category = f"{int(month):02d}-{int(day):02d}"
		series_name = str(int(year))
		if category not in categories:
			categories.append(category)
		if series_name not in series_names:
			series_names.append(series_name)

		series_values = values_by_year_and_day.setdefault(series_name, {})
		series_values[category] = series_values.get(category, 0.0) + float(value)

	series = [
		{
			"name": series_name,
			"data": [values_by_year_and_day.get(series_name, {}).get(category, 0.0) for category in categories],
		}
		for series_name in series_names
	]
	if not any(any(value != 0 for value in metric["data"]) for metric in series):
		return None

	kind, response_type = _pick_grouped_kind(preference, "month_day", rows, len(series), len(categories))
	return {
		"response_type": response_type,
		"visualization": {
			"kind": kind,
			"layout": _detect_bar_layout(title),
			"label_key": "month_day",
			"series_key": "YEAR(posting_date)",
			"value_key": value_key,
			"series": series,
			"categories": categories,
			"show_table_toggle": True,
		},
		"summary": _summarize_long_form_grouped_chart(categories, series_names, series, "YEAR(posting_date)"),
	}


_MONTH_SHORT = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
				7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}


def _build_year_month_category_grouped_chart(
	rows: list[dict], columns: list[str], title: str, preference: str
) -> dict | None:
	"""Handle 4-column shape: YEAR(posting_date) + MONTH(posting_date) + category + metric.

	Builds a grouped chart where x-axis = month-year periods, series = category values.
	"""
	if len(columns) != 4:
		return None

	numeric_keys = [c for c in columns if _is_measure_column(rows, c)]
	if len(numeric_keys) != 1:
		return None

	value_key = numeric_keys[0]
	dimension_keys = [c for c in columns if c != value_key]

	year_key = next((k for k in dimension_keys if k.upper().startswith("YEAR(")), None)
	month_key = next((k for k in dimension_keys if k.upper().startswith("MONTH(")), None)
	if not year_key or not month_key:
		return None

	category_dim = next((k for k in dimension_keys if k != year_key and k != month_key), None)
	if not category_dim:
		return None

	categories: list[str] = []
	series_names: list[str] = []
	values_by_series_and_category: dict[str, dict[str, float]] = {}

	for row in rows:
		year = row.get(year_key)
		month = row.get(month_key)
		series_name = row.get(category_dim)
		value = row.get(value_key)

		if year is None or month is None or series_name in (None, "") or not _is_numeric_value(value):
			return None

		time_label = f"{_MONTH_SHORT.get(int(month), str(int(month)))} {int(year)}"
		series_label = str(series_name)

		if time_label not in categories:
			categories.append(time_label)
		if series_label not in series_names:
			series_names.append(series_label)

		series_values = values_by_series_and_category.setdefault(series_label, {})
		series_values[time_label] = series_values.get(time_label, 0.0) + float(value)

	categories, values_by_series_and_category = _bucket_top_n_categories(
		categories, values_by_series_and_category, series_names,
	)
	series_names, values_by_series_and_category = _bucket_top_n_series(
		series_names, values_by_series_and_category, categories,
	)

	series = [
		{
			"name": name,
			"data": [values_by_series_and_category.get(name, {}).get(cat, 0.0) for cat in categories],
		}
		for name in series_names
	]

	if not any(any(v != 0 for v in s["data"]) for s in series):
		return None

	kind, response_type = _pick_grouped_kind(preference, "time", rows, len(series), len(categories))
	return {
		"response_type": response_type,
		"visualization": {
			"kind": kind,
			"layout": "vertical",
			"label_key": "time",
			"series_key": category_dim,
			"value_key": value_key,
			"series": series,
			"categories": categories,
			"show_table_toggle": True,
		},
		"summary": _summarize_long_form_grouped_chart(categories, series_names, series, category_dim),
	}


def _build_plain_summary(rows: list[dict], columns: list[str]) -> str | None:
	if len(rows) != 1 or len(columns) > 2:
		return None

	row = rows[0]
	parts = []
	for column in columns:
		value = row.get(column)
		if value in (None, ""):
			continue
		label = column.replace("_", " ").title()
		if _is_numeric_value(value):
			parts.append(f"{label}: {_format_metric_value(value)}")
		else:
			parts.append(str(value) if len(columns) == 1 else f"{label}: {value}")

	if not parts:
		return None

	return " | ".join(parts)


def _pick_chart_axes(rows: list[dict], columns: list[str]) -> tuple[str | None, str | None]:
	first, second = columns
	first_numeric = all(_is_numeric_value(row.get(first)) for row in rows)
	second_numeric = all(_is_numeric_value(row.get(second)) for row in rows)

	if first_numeric and not second_numeric:
		return second, first
	if second_numeric and not first_numeric:
		return first, second
	if first_numeric and second_numeric:
		# Both columns are numeric — use heuristics to pick label vs value.
		# SQL dimension functions (MONTH, YEAR, DAY, QUARTER, WEEK) produce
		# integers but are meant as category labels, not measure values.
		first_is_dimension = _is_dimension_column_name(first)
		second_is_dimension = _is_dimension_column_name(second)
		if first_is_dimension and not second_is_dimension:
			return first, second
		if second_is_dimension and not first_is_dimension:
			return second, first
		# If neither or both look like dimensions, pick the one with fewer
		# distinct values as the label axis.
		first_distinct = len({row.get(first) for row in rows})
		second_distinct = len({row.get(second) for row in rows})
		if first_distinct <= second_distinct:
			return first, second
		return second, first
	return None, None


def _is_dimension_column_name(column: str) -> bool:
	"""Return True if the column name looks like a SQL dimension function."""
	name = (column or "").upper().strip()
	return bool(re.match(r"^(YEAR_MONTH|MONTH|YEAR|DAY|QUARTER|WEEK|DAYOFWEEK|HOUR)\s*\(", name))


def _is_measure_column(rows: list[dict], column: str) -> bool:
	"""Return True if the column holds numeric measure values (not a dimension function)."""
	return _is_numeric_column(rows, column) and not _is_dimension_column_name(column)


def _is_numeric_column(rows: list[dict], column: str) -> bool:
	values = [row.get(column) for row in rows]
	return bool(values) and all(_is_numeric_value(value) for value in values)


def _detect_bar_layout(title: str) -> str:
	title_text = (title or "").lower()
	if "horizontal" in title_text or "grouped bar" in title_text:
		return "horizontal"
	return "vertical"


_TOP_N_SERIES = 6
_OTHERS_LABEL = "Others"


def _bucket_top_n_series(
	series_names: list[str],
	values_by_series: dict[str, dict[str, float]],
	categories: list[str],
	top_n: int = _TOP_N_SERIES,
) -> tuple[list[str], dict[str, dict[str, float]]]:
	"""Keep the top-N series by total value and merge the rest into 'Others'."""
	if len(series_names) <= top_n:
		return series_names, values_by_series

	totals = {
		name: sum(values_by_series.get(name, {}).get(cat, 0.0) for cat in categories)
		for name in series_names
	}
	ranked = sorted(series_names, key=lambda n: totals[n], reverse=True)
	top_names = ranked[:top_n]
	rest_names = ranked[top_n:]

	if not rest_names:
		return top_names, values_by_series

	others_values: dict[str, float] = {}
	for name in rest_names:
		for cat in categories:
			others_values[cat] = others_values.get(cat, 0.0) + values_by_series.get(name, {}).get(cat, 0.0)

	new_values = {name: values_by_series[name] for name in top_names}
	new_values[_OTHERS_LABEL] = others_values
	return top_names + [_OTHERS_LABEL], new_values


def _bucket_top_n_categories(
	categories: list[str],
	values_by_series: dict[str, dict[str, float]],
	series_names: list[str],
	top_n: int = 12,
) -> tuple[list[str], dict[str, dict[str, float]]]:
	"""Keep the top-N categories by total value and merge the rest into 'Others'."""
	if len(categories) <= top_n:
		return categories, values_by_series

	totals = {
		cat: sum(values_by_series.get(name, {}).get(cat, 0.0) for name in series_names)
		for cat in categories
	}
	ranked = sorted(categories, key=lambda c: totals[c], reverse=True)
	top_cats = ranked[:top_n]
	rest_cats = ranked[top_n:]

	if not rest_cats:
		return top_cats, values_by_series

	new_values: dict[str, dict[str, float]] = {}
	for name in series_names:
		series_data = values_by_series.get(name, {})
		new_series: dict[str, float] = {cat: series_data.get(cat, 0.0) for cat in top_cats}
		new_series[_OTHERS_LABEL] = sum(series_data.get(cat, 0.0) for cat in rest_cats)
		new_values[name] = new_series

	return top_cats + [_OTHERS_LABEL], new_values


def _pick_long_form_grouping_keys(rows: list[dict], dimension_keys: list[str], title: str) -> tuple[str, str]:
	title_text = (title or "").lower()
	if any(keyword in title_text for keyword in ("per day", "by day", "daily", "per date", "by date")):
		date_key = next((column for column in dimension_keys if _is_date_like_column(rows, column)), None)
		if date_key:
			other_key = next(column for column in dimension_keys if column != date_key)
			return date_key, other_key

	year_month_key = next((column for column in dimension_keys if column.upper().startswith("YEAR_MONTH(")), None)
	if year_month_key:
		other_key = next(column for column in dimension_keys if column != year_month_key)
		return year_month_key, other_key

	# For YEAR+MONTH dimension pairs, use MONTH as label (x-axis) and YEAR as
	# series (legend) so year-over-year comparison reads naturally.
	year_key = next((k for k in dimension_keys if k.upper().startswith("YEAR(")), None)
	if year_key:
		other_key = next(k for k in dimension_keys if k != year_key)
		return other_key, year_key

	return dimension_keys[0], dimension_keys[1]


def _pick_heatmap_axes(rows: list[dict], dimension_keys: list[str]) -> tuple[str, str]:
	customer_key = next((column for column in dimension_keys if _is_customer_column(column)), None)
	item_key = next((column for column in dimension_keys if _is_item_column(column)), None)
	if customer_key and item_key:
		return customer_key, item_key

	date_key = next((column for column in dimension_keys if _is_date_like_column(rows, column)), None)
	if date_key:
		other_key = next(column for column in dimension_keys if column != date_key)
		return other_key, date_key

	return dimension_keys[0], dimension_keys[1]


def _is_customer_column(column: str) -> bool:
	name = (column or "").lower()
	return any(part in name for part in ("customer", "client", "party"))


def _is_item_column(column: str) -> bool:
	name = (column or "").lower()
	return any(part in name for part in ("item", "sku", "product", "stock"))


def _is_date_like_column(rows: list[dict], column: str) -> bool:
	column_name = (column or "").lower()
	if "date" in column_name or "year_month" in column_name:
		return True

	pattern = re.compile(r"^\d{4}-\d{2}(?:-\d{2})?$")
	values = [row.get(column) for row in rows]
	non_empty_values = [value for value in values if value not in (None, "")]
	return bool(non_empty_values) and all(isinstance(value, str) and pattern.match(value) for value in non_empty_values)


def _should_auto_use_grouped_chart(title: str) -> bool:
	title_text = (title or "").lower()
	return any(
		keyword in title_text
		for keyword in (
			"grouped",
			"compare",
			"comparison",
			"versus",
			" vs ",
			"chart",
			"graph",
			# Arabic comparison keywords
			"قارن",
			"مقارنة",
			"مقارنه",
			"بالمقارنة",
		)
	)


def _should_use_line_chart(preference: str, label_key: str, rows: list[dict]) -> bool:
	if preference == "line":
		return True
	if preference != "auto":
		return False
	if len(rows) <= 4:
		return False
	return _is_dimension_column_name(label_key) or _is_date_like_column(rows, label_key)


def _should_use_area_chart(preference: str, label_key: str, rows: list[dict], value_key: str) -> bool:
	if preference == "area":
		return True
	if preference != "auto":
		return False
	if len(rows) <= 4:
		return False
	if not (_is_dimension_column_name(label_key) or _is_date_like_column(rows, label_key)):
		return False

	value_name = (value_key or "").lower()
	return any(
		hint in value_name
		for hint in ("total", "amount", "revenue", "sales")
	)


def _should_use_stacked_bar(preference: str, series_count: int, category_count: int) -> bool:
	if preference == "stacked_bar":
		return True
	if preference != "auto":
		return False
	return series_count >= 3 and category_count <= 8


def _should_use_grouped_line(preference: str, label_key: str, rows: list[dict]) -> bool:
	if preference == "line":
		return True
	if preference != "auto":
		return False
	label_name = (label_key or "").lower()
	return (
		_is_dimension_column_name(label_key)
		or _is_date_like_column(rows, label_key)
		or label_name in {"month_day"}
	)


def _pick_grouped_kind(
	preference: str,
	label_key: str,
	rows: list[dict],
	series_count: int,
	category_count: int,
) -> tuple[str, str]:
	if _should_use_grouped_line(preference, label_key, rows):
		return "grouped_line", "line_chart"
	if _should_use_stacked_bar(preference, series_count, category_count):
		return "stacked_bar", "stacked_bar_chart"
	return "grouped_bar", "bar_chart"


def _should_use_pie_chart(preference: str, title: str, values: Sequence[float]) -> bool:
	if preference == "pie":
		return all(value >= 0 for value in values)

	if not all(value >= 0 for value in values):
		return False

	title_text = title.lower()
	if any(
		keyword in title_text
		for keyword in (
			"top",
			"highest",
			"lowest",
			"rank",
			"ranking",
			"compare",
			"comparison",
			"versus",
			" vs ",
		)
	):
		return False

	return any(
		keyword in title_text
		for keyword in (
			"share",
			"distribution",
			"composition",
			"portion",
			"percent",
			"percentage",
			"contribution",
			"mix",
			"split",
			"breakdown",
			"proportion",
			"نسبة",
			"توزيع",
			"حصة",
			"نسب",
		)
	)


def _summarize_metric(payload: dict) -> str:
	context = f" {payload['context']}" if payload.get("context") else ""
	return f"{payload['label']}: {payload['formatted_value']}{context}".strip()


def _summarize_chart(categories: Sequence[str], values: Sequence[float], value_key: str, kind: str) -> str:
	max_index = max(range(len(values)), key=lambda idx: values[idx])
	leader = categories[max_index]
	leader_value = _format_metric_value(values[max_index])
	if kind in {"pie", "donut"}:
		return f"{leader} has the largest share at {leader_value} {value_key.replace('_', ' ')}."
	return f"{leader} is highest at {leader_value} {value_key.replace('_', ' ')}."


def _summarize_grouped_chart(categories: Sequence[str], value_keys: Sequence[str], series: Sequence[dict]) -> str:
	category_totals = []
	for category_index, category in enumerate(categories):
		total = sum(float(metric["data"][category_index]) for metric in series)
		category_totals.append((category, total))

	leader, leader_total = max(category_totals, key=lambda item: item[1])
	return (
		f"{leader} is highest overall at {_format_metric_value(leader_total)} across "
		f"{len(value_keys)} metrics."
	)


def _summarize_long_form_grouped_chart(
	categories: Sequence[str],
	series_names: Sequence[str],
	series: Sequence[dict],
	series_key: str,
) -> str:
	category_totals = []
	for category_index, category in enumerate(categories):
		total = sum(float(metric["data"][category_index]) for metric in series)
		category_totals.append((category, total))

	leader, leader_total = max(category_totals, key=lambda item: item[1])
	series_label = _humanize_column_label(series_key)
	return (
		f"{leader} is highest overall at {_format_metric_value(leader_total)} across "
		f"{len(series_names)} {series_label} groups."
	)


def _summarize_heatmap(x_key: str, y_key: str, value_key: str, series: Sequence[dict]) -> str:
	max_point = None
	max_series = ""
	for row in series:
		for point in row.get("data", []):
			value = point.get("y")
			if not _is_numeric_value(value):
				continue
			if max_point is None or value > max_point.get("y"):
				max_point = point
				max_series = row.get("name", "")

	if not max_point:
		return f"Heatmap by {_humanize_column_label(y_key)} and {_humanize_column_label(x_key)}."

	return (
		f"{max_series} × {max_point.get('x')} is highest at "
		f"{_format_metric_value(max_point.get('y'))} {_humanize_column_label(value_key)}."
	)


def _summarize_table(rows: list[dict], columns: list[str]) -> str:
	row_count = len(rows)
	column_count = len(columns)
	return f"Returned {row_count} row{'s' if row_count != 1 else ''} across {column_count} column{'s' if column_count != 1 else ''}."


def _is_numeric_value(value: Any) -> bool:
	return isinstance(value, (int, float, decimal.Decimal)) and not isinstance(value, bool) and math.isfinite(float(value))


def _format_metric_value(value: Any) -> str:
	if not _is_numeric_value(value):
		return str(value)

	number = float(value)
	if number.is_integer():
		return f"{int(number):,}"

	return f"{number:,.2f}".rstrip("0").rstrip(".")


def _humanize_column_label(column: str) -> str:
	label = re.sub(r"^[A-Z]+\((.+)\)$", r"\1", column or "")
	return label.replace("_", " ").strip().lower() or "series"
