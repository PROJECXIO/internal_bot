"""
Builds the structured JSON response returned to the frontend.
"""
from collections.abc import Sequence
import datetime
import decimal
import math
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
	from internal_bot.bot.state import GraphState


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

	if intent == "greeting":
		response = {
			"status": "greeting",
			"message": state.get("intent_reason", "Hello! How can I help you today?"),
			"markdown": state.get("answer_markdown")
			or state.get("intent_reason")
			or "Hello! How can I help you today?",
			"meta": {"confidence": 1.0},
		}

	elif intent == "clarification_needed":
		response = {
			"status": "clarification_needed",
			"question": state.get("intent_reason", "Could you clarify your question?"),
			"options": state.get("clarification_options", []),
			"markdown": state.get("answer_markdown")
			or state.get("intent_reason")
			or "Could you clarify your question?",
			"meta": {"confidence": 0.4},
		}

	elif intent == "blocked":
		response = {
			"status": "blocked",
			"reason": state.get("intent_reason", "This request touches restricted data."),
			"markdown": state.get("answer_markdown")
			or state.get("intent_reason")
			or "This request touches restricted data.",
			"meta": {"confidence": 1.0},
		}

	elif state.get("query_execution_error") or (
		not state.get("query_is_valid") and state.get("query_generation_attempts", 0) >= 3
	):
		error_msg = (
			state.get("query_execution_error")
			or state.get("query_invalid_reason", "Unknown error")
		)
		reason = "Could not generate a valid query. Please rephrase your question."
		response = {
			"status": "error",
			"reason": reason,
			"markdown": state.get("answer_markdown") or reason,
			"meta": {"confidence": 0.0, "error_detail": error_msg},
		}

	else:
		response = build_success_payload(state)
		response["status"] = "success"
		response["meta"] = {
			"confidence": _estimate_confidence(state),
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
	return last_response.get("response_type") in {"bar_chart", "pie_chart", "metric_card", "table"}


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
	history = [
		{
			"role": message.get("role", ""),
			"content": message.get("content", ""),
		}
		for message in (state.get("chat_history") or [])
		if message.get("content")
	]
	return {
		"history": history,
		"memory_summary": state.get("memory_summary") or "",
		"last_result_context": state.get("last_assistant_context_text") or "",
		"schema_context": state.get("schema_context") or "",
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
	retries = state.get("query_generation_attempts", 0)
	base -= retries * 0.1
	return round(max(0.1, min(1.0, base)), 2)


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
	rows: list[dict],
	columns: list[str],
	title: str,
	preference: str,
) -> tuple[str, dict | None, str]:
	if not rows:
		return "empty", None, "No results found."

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
	if preference not in {"bar", "pie", "auto"}:
		return None

	if len(rows) < 2 or len(columns) < 2:
		return None

	grouped_payload = _build_grouped_chart_visualization(rows, columns, title, preference)
	if grouped_payload:
		return grouped_payload

	if len(rows) > 12:
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
	if _should_use_pie_chart(preference, title, values):
		response_type = "pie_chart"
		kind = "pie"

	visualization = {
		"kind": kind,
		"label_key": label_key,
		"value_key": value_key,
		"layout": _detect_bar_layout(title),
		"series": [{"name": value_key.replace("_", " ").title(), "data": values}],
		"categories": categories,
		"show_table_toggle": True,
	}
	if kind == "pie":
		visualization["series"] = values

	return {
		"response_type": response_type,
		"visualization": visualization,
		"summary": _summarize_chart(categories, values, value_key, kind),
	}


def _build_grouped_chart_visualization(rows: list[dict], columns: list[str], title: str, preference: str) -> dict | None:
	if len(columns) < 3 or len(columns) > 6:
		return None
	if preference != "bar" and not _should_auto_use_grouped_chart(title):
		return None

	long_form_grouped_chart = _build_long_form_grouped_chart(rows, columns, title)
	if long_form_grouped_chart:
		return long_form_grouped_chart

	label_key = next((column for column in columns if not _is_numeric_column(rows, column)), None)
	if not label_key:
		return None

	numeric_keys = [column for column in columns if column != label_key and _is_numeric_column(rows, column)]
	label_columns = [column for column in columns if column not in numeric_keys]
	if len(numeric_keys) < 2 or len(label_columns) != 1:
		return None

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

		categories.append(str(label))
		for index, metric_key in enumerate(numeric_keys):
			value = row.get(metric_key)
			if not _is_numeric_value(value):
				return None
			series[index]["data"].append(float(value))

	if not any(any(value != 0 for value in metric["data"]) for metric in series):
		return None

	return {
		"response_type": "bar_chart",
		"visualization": {
			"kind": "grouped_bar",
			"layout": _detect_bar_layout(title),
			"label_key": label_key,
			"value_keys": numeric_keys,
			"series": series,
			"categories": categories,
			"show_table_toggle": True,
		},
		"summary": _summarize_grouped_chart(categories, numeric_keys, series),
	}


def _build_long_form_grouped_chart(rows: list[dict], columns: list[str], title: str) -> dict | None:
	if len(columns) != 3:
		return None

	numeric_keys = [column for column in columns if _is_numeric_column(rows, column)]
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

	series = [
		{
			"name": series_name,
			"data": [values_by_series_and_category.get(series_name, {}).get(category, 0.0) for category in categories],
		}
		for series_name in series_names
	]
	if not any(any(value != 0 for value in metric["data"]) for metric in series):
		return None

	return {
		"response_type": "bar_chart",
		"visualization": {
			"kind": "grouped_bar",
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
	return None, None


def _is_numeric_column(rows: list[dict], column: str) -> bool:
	values = [row.get(column) for row in rows]
	return bool(values) and all(_is_numeric_value(value) for value in values)


def _detect_bar_layout(title: str) -> str:
	title_text = (title or "").lower()
	if "horizontal" in title_text or "grouped bar" in title_text:
		return "horizontal"
	return "vertical"


def _pick_long_form_grouping_keys(rows: list[dict], dimension_keys: list[str], title: str) -> tuple[str, str]:
	title_text = (title or "").lower()
	if any(keyword in title_text for keyword in ("per day", "by day", "daily", "per date", "by date")):
		date_key = next((column for column in dimension_keys if _is_date_like_column(rows, column)), None)
		if date_key:
			other_key = next(column for column in dimension_keys if column != date_key)
			return date_key, other_key

	return dimension_keys[0], dimension_keys[1]


def _is_date_like_column(rows: list[dict], column: str) -> bool:
	column_name = (column or "").lower()
	if "date" in column_name:
		return True

	pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
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
		)
	)


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
		)
	)


def _summarize_metric(payload: dict) -> str:
	context = f" {payload['context']}" if payload.get("context") else ""
	return f"{payload['label']}: {payload['formatted_value']}{context}".strip()


def _summarize_chart(categories: Sequence[str], values: Sequence[float], value_key: str, kind: str) -> str:
	max_index = max(range(len(values)), key=lambda idx: values[idx])
	leader = categories[max_index]
	leader_value = _format_metric_value(values[max_index])
	if kind == "pie":
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
