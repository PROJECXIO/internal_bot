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
	  success               — query ran and returned data
	  clarification_needed  — intent was ambiguous
	  blocked               — request touches restricted data
	  error                 — SQL gen/exec failed after retries
	"""
	intent = state.get("intent", "query")
	debug = state.get("debug", False)

	# ── Greeting ────────────────────────────────────────────────────
	if intent == "greeting":
		response = {
			"status": "greeting",
			"message": state.get("intent_reason", "Hello! How can I help you today?"),
			"meta": {"confidence": 1.0},
		}

	# ── Clarification ──────────────────────────────────────────────
	elif intent == "clarification_needed":
		response = {
			"status": "clarification_needed",
			"question": state.get("intent_reason", "Could you clarify your question?"),
			"options": state.get("clarification_options", []),
			"meta": {"confidence": 0.4},
		}

	# ── Blocked ─────────────────────────────────────────────────────
	elif intent == "blocked":
		response = {
			"status": "blocked",
			"reason": state.get("intent_reason", "This request touches restricted data."),
			"meta": {"confidence": 1.0},
		}

	# ── Query Error ─────────────────────────────────────────────────
	elif state.get("query_execution_error") or (
		not state.get("query_is_valid") and state.get("query_generation_attempts", 0) >= 3
	):
		error_msg = (
			state.get("query_execution_error")
			or state.get("query_invalid_reason", "Unknown error")
		)
		response = {
			"status": "error",
			"reason": "Could not generate a valid query. Please rephrase your question.",
			"meta": {"confidence": 0.0, "error_detail": error_msg},
		}

	# ── Success ──────────────────────────────────────────────────────
	else:
		rows = _serialize_rows(state.get("query_result_rows") or [])
		columns = list(rows[0].keys()) if rows else []
		title = _make_title(state.get("normalized_question") or state.get("raw_message", ""))
		preference = _detect_visualization_preference(state.get("normalized_question") or state.get("raw_message", ""))
		response_type, visualization, summary = _build_success_visualization(
			rows=rows,
			columns=columns,
			title=title,
			preference=preference,
		)

		response = {
			"status": "success",
			"response_type": response_type,
			"visualization": visualization,
			"summary": summary,
			"title": title,
			"columns": columns,
			"rows": rows,
			"meta": {
				"confidence": _estimate_confidence(state),
				"has_more": len(rows) >= (state.get("max_rows") or 100),
				"returned_rows": len(rows),
			},
		}

	# ── Debug extras ────────────────────────────────────────────────
	if debug:
		response["debug"] = {
			"normalized_question": state.get("normalized_question"),
			"discovered_entities": state.get("discovered_doctypes", []),
			"generated_intent": state.get("generated_intent"),
			"compiled_sql": state.get("compiled_sql"),
			"retries": state.get("query_generation_attempts", 0),
			"timing": state.get("timing", {}),
			"cache_hit": state.get("cache_hit", False),
			"provider": state.get("llm_provider"),
			"model": state.get("llm_model"),
			"node_trace": state.get("node_trace", []),
			"response_type": response.get("response_type"),
			"visualization_preference": preference if intent == "query" else "auto",
		}

	return response


def normalize_cached_response(cached_result: dict, state: "GraphState") -> dict:
	"""Upgrade cached success payloads to the current response contract."""
	response = dict(cached_result or {})
	if response.get("status") != "success":
		return response

	rows = _serialize_rows(response.get("rows") or [])
	columns = response.get("columns") or (list(rows[0].keys()) if rows else [])
	title = response.get("title") or _make_title(state.get("normalized_question") or state.get("raw_message", ""))
	preference = _detect_visualization_preference(state.get("normalized_question") or state.get("raw_message", ""))
	response_type, visualization, summary = _build_success_visualization(
		rows=rows,
		columns=columns,
		title=title,
		preference=preference,
	)

	response["response_type"] = response_type
	response["visualization"] = visualization
	response["summary"] = summary
	response["title"] = title
	response["columns"] = columns
	response["rows"] = rows
	response.setdefault(
		"meta",
		{
			"confidence": _estimate_confidence(state),
			"has_more": len(rows) >= (state.get("max_rows") or 100),
			"returned_rows": len(rows),
		},
	)
	return response


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_title(question: str) -> str:
	if not question:
		return "Query Result"
	# Capitalise first char, strip trailing punctuation
	title = question.strip().rstrip("?.")
	return title[:80] if len(title) > 80 else title


def _estimate_confidence(state: "GraphState") -> float:
	"""Heuristic confidence: penalise retries."""
	base = 0.95
	retries = state.get("query_generation_attempts", 0)
	base -= retries * 0.1
	return round(max(0.1, min(1.0, base)), 2)


def _serialize_rows(rows: list[dict]) -> list[dict]:
	"""Convert any non-JSON-serializable values (Decimal, date, etc.)."""
	result = []
	for row in rows:
		clean = {}
		for k, v in row.items():
			if isinstance(v, decimal.Decimal):
				clean[k] = float(v)
			elif isinstance(v, (datetime.date, datetime.datetime)):
				clean[k] = str(v)
			elif v is None:
				clean[k] = None
			else:
				clean[k] = v
		result.append(clean)
	return result


def _detect_visualization_preference(question: str) -> str:
	text = (question or "").strip().lower()
	if not text:
		return "auto"
	if "pie chart" in text or "pie graph" in text:
		return "pie"
	if "bar chart" in text or "bar graph" in text:
		return "bar"
	if "card" in text or "summary card" in text:
		return "card"
	if "chart" in text or "graph" in text:
		return "bar"
	if "summary" in text or "single value" in text or "metric" in text or "kpi" in text:
		return "card"
	return "auto"


def _build_success_visualization(rows: list[dict], columns: list[str], title: str, preference: str) -> tuple[str, dict | None, str]:
	if not rows:
		return "empty", None, "No results found."

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

	if len(rows) < 2 or len(rows) > 12 or len(columns) != 2:
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


def _should_use_pie_chart(preference: str, title: str, values: Sequence[float]) -> bool:
	if preference == "pie":
		return all(value >= 0 for value in values)

	if not all(value >= 0 for value in values):
		return False

	title_text = title.lower()
	return any(keyword in title_text for keyword in ("share", "distribution", "breakdown", "composition", "portion"))


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
