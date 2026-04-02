"""
Node: Answer Composer

Creates markdown answer copy after the query result shape and visualization
choice are already known.
"""
import json
import math
import re
import time
import datetime
import decimal
from statistics import median

import frappe

from internal_bot.bot.services.formatter import format_structured_response
from internal_bot.bot.state import GraphState
from internal_bot.bot import progress, trace

_SYSTEM_PROMPT = """\
You write concise markdown answers for an ERP analytics assistant.

Rules:
- Return markdown only.
- No HTML.
- No code fences.
- Use short, direct phrasing.
- For response_type "plain_text", answer the question directly in markdown.
- For response_type "metric_card", "bar_chart", "pie_chart", and "table", write a quick brief that fits above the visualization.
- Prefer one short paragraph, or 2-3 short bullets when that is clearer.
- Use strong markdown emphasis for important business facts:
  - Bold important dates like **2026-04-02**.
  - Bold important numbers and currency values like **229,000** or **$12,500**.
  - Bold key labels, metric names, and period names like **Grand Total**, **This Month**, and **Last Month**.
- When comparing periods or categories, make the contrast easy to scan with bullets.
- Lead with the most important takeaway first.
- Keep the answer clean and readable, not decorative.
- Do not mention SQL, internal processing, or implementation details.
- If this is a follow-up analysis request about a previous result, do not repeat chart instructions or mention visualization.
- In follow-up analysis, explain the pattern, contrast, or takeaway behind the numbers in plain markdown prose or bullets.
- If `analysis_mode` is true, analyze the data instead of just restating it.
- In `analysis_mode`, focus on business takeaways such as:
  - concentration or outliers
  - highest vs lowest values
  - trend or spread across dates/categories
  - notable clusters, gaps, or anomalies
- In `analysis_mode`, avoid row-by-row narration unless the dataset is tiny and that is the clearest way to explain the insight.
- In `analysis_mode`, prefer 2-4 insight bullets grounded in the data.
- If the data is too limited for a strong conclusion, say that briefly instead of inventing a pattern.

Examples:
- Good comparison brief:
  - **2025-09-16** recorded the highest **Grand Total** at **229,000**.
  - **This Month** is outperforming **Last Month** on total sales.
- Good metric answer:
  - The **Total Sales** value is **125,000**.
- Good analysis answer:
  - **2025-09-16** is a clear outlier at **229,000**, contributing more than half of the returned total.
  - The remaining days are much lower, which suggests sales are concentrated in a small number of peaks rather than distributed evenly.
"""


def run(state: GraphState) -> dict:
	t0 = time.monotonic()
	node_name = "answer_composer"
	log_t0 = trace.node_start(state, node_name)
	if state.get("_emit_progress"):
		progress.emit(state, node_name, "Writing answer")

	llm_client = state.get("_llm_client")
	if not llm_client:
		return _update(state, node_name, t0, _finalize_success_state(state, {"answer_markdown": ""}), log_t0)

	try:
		rows = state.get("query_result_rows") or []
		analysis_mode = _is_analysis_request(state)
		data_rows = _serialize_rows(rows[:25] if analysis_mode else rows[:3])
		user_content = json.dumps(
			{
				"question": state.get("normalized_question") or state.get("raw_message", ""),
				"analysis_mode": analysis_mode,
				"response_type": state.get("response_type"),
				"title": state.get("normalized_question") or state.get("raw_message", ""),
				"columns": list(rows[0].keys()) if rows else [],
				"row_count": len(rows),
				"data_rows": data_rows,
				"visualization_choice": state.get("visualization_preference") or "auto",
				"answer_prefix": state.get("answer_prefix") or "",
				"summary": state.get("summary") or "",
				"follow_up_to_previous_result": bool(state.get("follow_up_to_previous_result")),
				"analysis_hints": _build_analysis_hints(rows),
			},
			ensure_ascii=True,
		)
	except Exception as exc:
		frappe.log_error(str(exc), "AnswerComposer payload build error")
		return _update(state, node_name, t0, _finalize_success_state(state, {"answer_markdown": ""}), log_t0)

	messages = [
		{"role": "system", "content": _SYSTEM_PROMPT},
		{"role": "user", "content": user_content},
	]

	try:
		raw = llm_client.chat_completion(
			messages,
			temperature=0.1,
			max_tokens=220,
			**trace.llm_trace_context(state, node_name, "compose_answer"),
		)
		input_tokens = (state.get("input_tokens") or 0) + (
			getattr(llm_client, "last_input_tokens", 0) or 0
		)
		output_tokens = (state.get("output_tokens") or 0) + (
			getattr(llm_client, "last_output_tokens", 0) or 0
		)
		answer_markdown = _clean_markdown(raw)
		if analysis_mode and not answer_markdown:
			answer_markdown = _build_analysis_fallback(rows)
		trace.detail(state, "Answer markdown", answer_markdown[:120] if answer_markdown else "")

		return _update(
			state,
			node_name,
			t0,
			_finalize_success_state(state, {
				"answer_markdown": answer_markdown,
				"input_tokens": input_tokens,
				"output_tokens": output_tokens,
				"llm_provider": getattr(llm_client, "provider", ""),
				"llm_model": getattr(llm_client, "model", ""),
			}),
			log_t0,
		)
	except Exception as exc:
		frappe.log_error(str(exc), "AnswerComposer LLM error")
		return _update(
			state,
			node_name,
			t0,
			_finalize_success_state(state, {
				"answer_markdown": _build_analysis_fallback(state.get("query_result_rows") or [])
				if _is_analysis_request(state) else "",
				"input_tokens": (state.get("input_tokens") or 0) + (
					getattr(llm_client, "last_input_tokens", 0) or 0
				),
				"output_tokens": (state.get("output_tokens") or 0) + (
					getattr(llm_client, "last_output_tokens", 0) or 0
				),
				"llm_provider": getattr(llm_client, "provider", ""),
				"llm_model": getattr(llm_client, "model", ""),
			}),
			log_t0,
		)


def _clean_markdown(raw: str) -> str:
	text = (raw or "").strip()
	if not text:
		return ""

	match = re.search(r"```(?:markdown)?\s*([\s\S]*?)```", text, re.IGNORECASE)
	if match:
		text = match.group(1).strip()

	return text


def _is_analysis_request(state: GraphState) -> bool:
	question = (state.get("normalized_question") or state.get("raw_message") or "").lower()
	if not question:
		return False

	return any(
		re.search(pattern, question)
		for pattern in (
			r"\banaly[sz]e\b",
			r"\banalysis\b",
			r"\bexplain\b",
			r"\binterpret\b",
			r"\bbreak down\b",
			r"\bdeeper\b",
			r"\bfurther\b",
			r"\binsight(s)?\b",
			r"\bwhat does this mean\b",
		)
	)


def _serialize_rows(rows: list[dict]) -> list[dict]:
	result = []
	for row in rows:
		clean = {}
		for key, value in row.items():
			if isinstance(value, decimal.Decimal):
				float_value = float(value)
				clean[key] = float_value if math.isfinite(float_value) else str(value)
			elif isinstance(value, (datetime.date, datetime.datetime)):
				clean[key] = str(value)
			elif value is None:
				clean[key] = None
			else:
				clean[key] = value
		result.append(clean)
	return result


def _build_analysis_hints(rows: list[dict]) -> dict:
	if not rows:
		return {}

	columns = list(rows[0].keys())
	if len(columns) != 2:
		return {}

	value_column = next((column for column in columns if _is_numeric_column(rows, column)), None)
	if not value_column:
		return {}

	label_column = next((column for column in columns if column != value_column), None)
	if not label_column:
		return {}

	values = [float(row.get(value_column)) for row in rows if _is_numeric_value(row.get(value_column))]
	if len(values) < 2:
		return {}

	max_row = max(rows, key=lambda row: float(row.get(value_column) or 0))
	min_row = min(rows, key=lambda row: float(row.get(value_column) or 0))
	total = sum(values)
	mean = total / len(values)
	median_value = median(values)
	top_share = round((float(max_row.get(value_column) or 0) / total) * 100, 1) if total else 0

	return {
		"label_column": label_column,
		"value_column": value_column,
		"total": round(total, 2),
		"average": round(mean, 2),
		"median": round(median_value, 2),
		"max_label": max_row.get(label_column),
		"max_value": max_row.get(value_column),
		"min_label": min_row.get(label_column),
		"min_value": min_row.get(value_column),
		"top_share_percent": top_share,
	}


def _build_analysis_fallback(rows: list[dict]) -> str:
	hints = _build_analysis_hints(rows)
	if not hints:
		return ""

	value_column = hints["value_column"].replace("_", " ")
	max_value = _format_number(hints["max_value"])
	min_value = _format_number(hints["min_value"])
	total = _format_number(hints["total"])
	average = _format_number(hints["average"])
	median_value = _format_number(hints["median"])

	lines = [
		f"- **{hints['max_label']}** is the highest point at **{max_value}** for **{value_column}**.",
		f"- The returned total is **{total}**, with an average of **{average}** and a median of **{median_value}**, which helps show whether the result is evenly distributed or skewed.",
	]

	if hints["top_share_percent"] >= 35:
		lines.append(
			f"- **{hints['max_label']}** alone contributes about **{hints['top_share_percent']}%** of the returned total, so the pattern is concentrated rather than evenly spread."
		)
	else:
		lines.append(
			f"- The lowest point is **{hints['min_label']}** at **{min_value}**, which gives a useful contrast against the peak."
		)

	min_frequency = _count_numeric_value(rows, hints["value_column"], hints["min_value"])
	if min_frequency > 1:
		lines.append(
			f"- The low end repeats: **{min_value}** appears **{min_frequency}** times, which suggests a cluster of weaker periods rather than a single isolated dip."
		)

	return "\n".join(lines[:4])


def _is_numeric_column(rows: list[dict], column: str) -> bool:
	values = [row.get(column) for row in rows if row.get(column) not in (None, "")]
	if not values:
		return False
	return all(_is_numeric_value(value) for value in values)


def _is_numeric_value(value) -> bool:
	return isinstance(value, (int, float, decimal.Decimal)) and not isinstance(value, bool)


def _count_numeric_value(rows: list[dict], column: str, target) -> int:
	try:
		target_number = float(target)
	except (TypeError, ValueError):
		return 0

	count = 0
	for row in rows:
		value = row.get(column)
		if _is_numeric_value(value) and float(value) == target_number:
			count += 1
	return count


def _format_number(value) -> str:
	if not _is_numeric_value(value):
		return str(value)

	number = float(value)
	if number.is_integer():
		return f"{int(number):,}"

	return f"{number:,.2f}".rstrip("0").rstrip(".")


def _finalize_success_state(state: GraphState, updates: dict) -> dict:
	merged_state = {**state, **updates}
	formatted = format_structured_response(merged_state)
	return {
		**updates,
		"formatted_response": formatted,
		"response_type": formatted.get("response_type"),
		"visualization": formatted.get("visualization"),
		"summary": formatted.get("summary"),
		"answer_prefix": formatted.get("answer_prefix", ""),
		"answer_markdown": formatted.get("markdown", updates.get("answer_markdown", "")),
		"visualization_preference": merged_state.get("visualization_preference") or "auto",
	}


def _update(state: GraphState, node_name: str, t0: float, updates: dict, log_t0: float) -> dict:
	elapsed = round((time.monotonic() - t0) * 1000, 2)
	node_trace = list(state.get("node_trace") or []) + [node_name]
	timing = dict(state.get("timing") or {})
	timing[node_name] = elapsed
	from internal_bot.bot import trace as bench_trace
	bench_trace.node_end(state, node_name, log_t0)
	updated_state = {**updates, "node_trace": node_trace, "timing": timing}

	return updated_state
