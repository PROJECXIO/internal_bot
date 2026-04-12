"""
Phase 0 baseline runner for the current Internal Bot pipeline.

How to run from the bench root:
	bench --site <site> execute internal_bot.tests.run_baseline.run

Optional examples:
	bench --site <site> execute internal_bot.tests.run_baseline.run --kwargs "{'user': 'Administrator'}"
	bench --site <site> execute internal_bot.tests.run_baseline.run --kwargs "{'fixture_name': 'golden_queries.json'}"

Bench/site context:
	This runner expects an initialized Frappe site context. It is intended to be
	called through `bench --site ... execute ...`, not plain `python`, because the
	bot needs Frappe DocTypes, user/session state, provider settings, permissions,
	and site data.

Pipeline/API behavior:
	The runner uses internal Python imports and invokes the current LangGraph
	pipeline directly. It does not call the whitelisted HTTP API. Direct graph
	invocation keeps the production pipeline unchanged while allowing this harness
	to capture final graph state fields that the public API response does not
	always expose.

Assumptions:
	- `AI Provider Settings` is configured for the selected site.
	- The selected user exists and can read the DocTypes being tested.
	- ERPNext/sample data may differ by site; row counts and result values are
	  expected to reflect the local site.
	- The runner deletes and recreates only `AI Chat Session` records whose names
	  start with `PHASE0-BASELINE-` so repeated runs do not inherit stale memory.
"""

from __future__ import annotations

import contextlib
import datetime
import decimal
import io
import json
import math
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

import frappe

from internal_bot.bot import trace
from internal_bot.bot.graph import get_graph, reset_graph
from internal_bot.bot.services.language import get_user_profile_language
from internal_bot.bot.services.llm_client import get_llm_client


APP_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
DEFAULT_FIXTURE = FIXTURE_DIR / "baseline_queries.json"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "output"
SESSION_PREFIX = "PHASE0-BASELINE-"
REPORT_FILE = "baseline_report.json"
SUMMARY_FILE = "baseline_summary.json"


def run(
	fixture_name: str | None = None,
	output_dir: str | None = None,
	user: str = "Administrator",
	reset_sessions: bool = True,
	include_trace_output: bool = True,
) -> dict:
	"""Run the selected baseline fixture and write report/summary JSON files."""
	fixture_path = _resolve_fixture_path(fixture_name)
	output_path = Path(output_dir).expanduser().resolve() if output_dir else DEFAULT_OUTPUT_DIR
	output_path.mkdir(parents=True, exist_ok=True)

	queries = _load_queries(fixture_path)
	queries = _expand_dependencies(queries, fixture_path)
	_prepare_user(user)
	if reset_sessions:
		_reset_baseline_sessions()

	settings, settings_error = _load_settings()
	llm_client, llm_error = _load_llm_client()

	results = []
	for index, query in enumerate(queries, start=1):
		result = _run_query(
			query=query,
			index=index,
			total=len(queries),
			user=user,
			settings=settings,
			llm_client=llm_client,
			startup_error=settings_error or llm_error,
			include_trace_output=include_trace_output,
		)
		results.append(result)
		_print_progress(result, index, len(queries))

	report = {
		"fixture": _display_path(fixture_path),
		"output_files": {
			"report": _display_path(output_path / REPORT_FILE),
			"summary": _display_path(output_path / SUMMARY_FILE),
		},
		"session_prefix": SESSION_PREFIX,
		"user": user,
		"results": results,
	}
	summary = _build_summary(results)

	_write_json(output_path / REPORT_FILE, report)
	_write_json(output_path / SUMMARY_FILE, summary)
	frappe.db.commit()

	return {
		"report": str(output_path / REPORT_FILE),
		"summary": str(output_path / SUMMARY_FILE),
		"summary_data": summary,
	}


def _resolve_fixture_path(fixture_name: str | None) -> Path:
	if not fixture_name:
		return DEFAULT_FIXTURE

	path = Path(fixture_name).expanduser()
	if not path.is_absolute():
		path = FIXTURE_DIR / path
	return path.resolve()


def _display_path(path: Path) -> str:
	try:
		return str(path.resolve().relative_to(APP_ROOT))
	except ValueError:
		return str(path.resolve())


def _load_queries(fixture_path: Path) -> list[dict]:
	with fixture_path.open(encoding="utf-8") as handle:
		queries = json.load(handle)
	if not isinstance(queries, list):
		raise ValueError(f"Fixture must contain a JSON array: {fixture_path}")
	return queries


def _expand_dependencies(queries: list[dict], fixture_path: Path) -> list[dict]:
	"""Include dependency queries from the baseline fixture when a smaller fixture references them."""
	seen = {query.get("id") for query in queries}
	dependencies = [query.get("depends_on") for query in queries if query.get("depends_on")]
	missing = [dependency for dependency in dependencies if dependency not in seen]
	if not missing or fixture_path.name == "baseline_queries.json":
		return queries

	baseline_by_id = {
		query.get("id"): query
		for query in _load_queries(DEFAULT_FIXTURE)
		if query.get("id")
	}
	expanded = []
	added = set()
	for query in queries:
		dependency = query.get("depends_on")
		if dependency and dependency not in seen and dependency in baseline_by_id and dependency not in added:
			expanded.append({**baseline_by_id[dependency], "dependency_seed": True})
			added.add(dependency)
		expanded.append(query)
	return expanded


def _prepare_user(user: str) -> None:
	if not frappe.db.exists("User", user):
		raise ValueError(f"Baseline user does not exist: {user}")
	frappe.set_user(user)
	frappe.session.user = user


def _reset_baseline_sessions() -> None:
	session_names = frappe.get_all(
		"AI Chat Session",
		filters={"name": ["like", f"{SESSION_PREFIX}%"]},
		pluck="name",
	)
	if not session_names:
		return

	frappe.db.delete("AI Chat Message", {"session": ["in", session_names]})
	if frappe.db.exists("DocType", "AI Bot Analytics"):
		frappe.db.delete("AI Bot Analytics", {"session": ["in", session_names]})
	frappe.db.delete("AI Chat Session", {"name": ["in", session_names]})
	frappe.db.commit()
	reset_graph()


def _load_settings() -> tuple[Any | None, str]:
	try:
		settings = frappe.get_doc("AI Provider Settings")
		return settings, ""
	except Exception as exc:
		return None, f"AI Provider Settings could not be loaded: {exc}"


def _load_llm_client() -> tuple[Any | None, str]:
	try:
		return get_llm_client(), ""
	except Exception as exc:
		return None, f"LLM client could not be initialized: {exc}"


def _run_query(
	query: dict,
	index: int,
	total: int,
	user: str,
	settings: Any | None,
	llm_client: Any | None,
	startup_error: str,
	include_trace_output: bool,
) -> dict:
	started = time.monotonic()
	if startup_error:
		return _error_result(query, startup_error, started)

	session_name = _ensure_session(_session_name_for_query(query), user)
	state = _build_initial_state(
		query=query,
		user=user,
		session_name=session_name,
		settings=settings,
		llm_client=llm_client,
	)

	stdout_buffer = io.StringIO()
	stderr_buffer = io.StringIO()
	try:
		with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
			trace.request_start(
				state,
				[
					f"Baseline query {index}/{total}: {query.get('id')}",
					f"Question: \"{query.get('message', '').strip()}\"",
					f"Session: {session_name}",
					"Invoking graph...",
				],
			)
			final_state = get_graph().invoke(
				state,
				config=trace.graph_invoke_config(state, run_name="internal_bot.phase_0_baseline"),
			)
			response = final_state.get("formatted_response") or {
				"status": "error",
				"reason": "No response generated.",
				"meta": {"confidence": 0.0},
			}
			trace.request_complete(final_state, response)
			trace.flush_langsmith()
	except Exception as exc:
		with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
			trace.request_error(state, str(exc))
			trace.flush_langsmith()
		return _exception_result(
			query=query,
			state=state,
			exc=exc,
			started=started,
			stdout_value=stdout_buffer.getvalue(),
			stderr_value=stderr_buffer.getvalue(),
			include_trace_output=include_trace_output,
		)

	return _state_result(
		query=query,
		state=final_state,
		response=response,
		started=started,
		stdout_value=stdout_buffer.getvalue(),
		stderr_value=stderr_buffer.getvalue(),
		include_trace_output=include_trace_output,
	)


def _build_initial_state(
	query: dict,
	user: str,
	session_name: str,
	settings: Any,
	llm_client: Any,
) -> dict:
	current_dt = frappe.utils.get_datetime()
	return {
		"user": user,
		"raw_message": (query.get("message") or "").strip(),
		"session_name": session_name,
		"debug": True,
		"max_rows": getattr(settings, "max_result_rows", None) or 100,
		"current_date": str(current_dt.date()),
		"current_day_name": current_dt.strftime("%A"),
		"current_year": current_dt.year,
		"user_profile_language": get_user_profile_language(user),
		"start_time": time.monotonic(),
		"node_trace": [],
		"timing": {},
		"query_generation_attempts": 0,
		"retries": 0,
		"cache_hit": False,
		"input_tokens": 0,
		"output_tokens": 0,
		"result_row_count": 0,
		"answer_markdown": "",
		"_llm_client": llm_client,
		"_settings": settings,
	}


def _ensure_session(session_name: str, user: str) -> str:
	if frappe.db.exists("AI Chat Session", session_name):
		return session_name

	doc = frappe.get_doc(
		{
			"doctype": "AI Chat Session",
			"name": session_name,
			"user": user,
			"is_active": 1,
			"total_messages": 0,
		}
	)
	doc.flags.name_set = True
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return session_name


def _session_name_for_query(query: dict) -> str:
	conversation_id = query.get("conversation_id") or query.get("id") or "query"
	safe_key = re.sub(r"[^A-Za-z0-9_-]+", "-", str(conversation_id)).strip("-")
	return f"{SESSION_PREFIX}{safe_key}"


def _state_result(
	query: dict,
	state: dict,
	response: dict,
	started: float,
	stdout_value: str,
	stderr_value: str,
	include_trace_output: bool,
) -> dict:
	debug = response.get("debug") or {}
	status = response.get("status") or "error"
	error_detail = _error_detail_from_state_or_response(state, response)
	result = {
		"id": query.get("id"),
		"category": query.get("category"),
		"language": query.get("language"),
		"message": query.get("message"),
		"expected_status": query.get("expected_status"),
		"status": status,
		"status_matches_expected": status == query.get("expected_status"),
		"dependency_seed": bool(query.get("dependency_seed")),
		"normalized_question": state.get("normalized_question") or debug.get("normalized_question"),
		"intent": state.get("intent"),
		"schema_decision": state.get("schema_decision") or debug.get("schema_decision"),
		"discovered_doctypes": state.get("discovered_doctypes") or debug.get("discovered_entities") or [],
		"generated_intent": state.get("generated_intent") or debug.get("generated_intent"),
		"compiled_sql": state.get("compiled_sql") or debug.get("compiled_sql"),
		"response_type": response.get("response_type") or state.get("response_type") or debug.get("response_type"),
		"returned_rows": _returned_rows(state, response),
		"retries": int(state.get("query_generation_attempts") or debug.get("retries") or 0),
		"timing": _round_timing(state.get("timing") or debug.get("timing") or {}),
		"wall_time_ms": round((time.monotonic() - started) * 1000, 2),
		"error_detail": error_detail,
		"node_trace": state.get("node_trace") or debug.get("node_trace") or [],
		"response": _json_safe(_response_without_debug(response)),
		"debug": _json_safe(debug),
	}
	if include_trace_output:
		result["trace_output"] = _sanitize_trace_output(stdout_value)
	if stderr_value.strip():
		result["stderr"] = _sanitize_trace_output(stderr_value)
	return _json_safe(result)


def _exception_result(
	query: dict,
	state: dict,
	exc: Exception,
	started: float,
	stdout_value: str,
	stderr_value: str,
	include_trace_output: bool,
) -> dict:
	result = {
		"id": query.get("id"),
		"category": query.get("category"),
		"language": query.get("language"),
		"message": query.get("message"),
		"expected_status": query.get("expected_status"),
		"status": "exception",
		"status_matches_expected": query.get("expected_status") == "exception",
		"dependency_seed": bool(query.get("dependency_seed")),
		"normalized_question": state.get("normalized_question"),
		"intent": state.get("intent"),
		"schema_decision": state.get("schema_decision"),
		"discovered_doctypes": state.get("discovered_doctypes") or [],
		"generated_intent": state.get("generated_intent"),
		"compiled_sql": state.get("compiled_sql"),
		"response_type": state.get("response_type"),
		"returned_rows": len(state.get("query_result_rows") or []),
		"retries": int(state.get("query_generation_attempts") or 0),
		"timing": _round_timing(state.get("timing") or {}),
		"wall_time_ms": round((time.monotonic() - started) * 1000, 2),
		"error_detail": str(exc),
		"node_trace": state.get("node_trace") or [],
		"response": {},
		"debug": {},
	}
	if include_trace_output:
		result["trace_output"] = _sanitize_trace_output(stdout_value)
	if stderr_value.strip():
		result["stderr"] = _sanitize_trace_output(stderr_value)
	return _json_safe(result)


def _error_result(query: dict, error_detail: str, started: float) -> dict:
	return {
		"id": query.get("id"),
		"category": query.get("category"),
		"language": query.get("language"),
		"message": query.get("message"),
		"expected_status": query.get("expected_status"),
		"status": "error",
		"status_matches_expected": query.get("expected_status") == "error",
		"dependency_seed": bool(query.get("dependency_seed")),
		"normalized_question": None,
		"intent": None,
		"schema_decision": None,
		"discovered_doctypes": [],
		"generated_intent": None,
		"compiled_sql": None,
		"response_type": None,
		"returned_rows": 0,
		"retries": 0,
		"timing": {},
		"wall_time_ms": round((time.monotonic() - started) * 1000, 2),
		"error_detail": error_detail,
		"node_trace": [],
		"response": {},
		"debug": {},
	}


def _response_without_debug(response: dict) -> dict:
	clean = dict(response or {})
	clean.pop("debug", None)
	clean.pop("session_id", None)
	return clean


def _error_detail_from_state_or_response(state: dict, response: dict) -> str:
	meta = response.get("meta") or {}
	return (
		state.get("query_execution_error")
		or state.get("query_invalid_reason")
		or meta.get("error_detail")
		or response.get("reason")
		or ""
	)


def _returned_rows(state: dict, response: dict) -> int:
	meta = response.get("meta") or {}
	if meta.get("returned_rows") is not None:
		return int(meta.get("returned_rows") or 0)
	if response.get("rows") is not None:
		return len(response.get("rows") or [])
	return len(state.get("query_result_rows") or [])


def _round_timing(timing: dict) -> dict:
	return {
		str(key): round(float(value), 2)
		for key, value in sorted((timing or {}).items())
		if isinstance(value, int | float)
	}


def _sanitize_trace_output(value: str) -> list[str]:
	lines = []
	for raw_line in (value or "").splitlines():
		line = re.sub(r"^\[[^\]]+\]", "[session]", raw_line.rstrip())
		line = re.sub(r"\b\d+(?:\.\d+)?ms\b", "<ms>", line)
		line = re.sub(r"\b\d+(?:\.\d+)?s\b", "<s>", line)
		lines.append(line)
	return lines


def _build_summary(results: list[dict]) -> dict:
	visible_results = [result for result in results if not result.get("dependency_seed")]
	status_counts = Counter(result.get("status") or "unknown" for result in visible_results)
	retry_values = [int(result.get("retries") or 0) for result in visible_results]
	timing_values = [float(result.get("wall_time_ms") or 0) for result in visible_results if result.get("wall_time_ms") is not None]
	no_row_ids = [
		result.get("id")
		for result in visible_results
		if result.get("status") == "success" and int(result.get("returned_rows") or 0) == 0
	]
	failing = [
		result
		for result in visible_results
		if result.get("status") in {"error", "exception"} or not result.get("status_matches_expected")
	]
	failing_categories = Counter(result.get("category") or "unknown" for result in failing)
	return {
		"total_queries": len(visible_results),
		"success_count": status_counts.get("success", 0),
		"clarification_count": status_counts.get("clarification_needed", 0),
		"blocked_count": status_counts.get("blocked", 0),
		"greeting_count": status_counts.get("greeting", 0),
		"error_count": status_counts.get("error", 0) + status_counts.get("exception", 0),
		"average_retries": round(sum(retry_values) / len(retry_values), 2) if retry_values else 0.0,
		"average_timing_ms": round(sum(timing_values) / len(timing_values), 2) if timing_values else None,
		"queries_with_no_rows": no_row_ids,
		"status_counts": dict(sorted(status_counts.items())),
		"status_mismatches": [
			{
				"id": result.get("id"),
				"category": result.get("category"),
				"expected_status": result.get("expected_status"),
				"actual_status": result.get("status"),
			}
			for result in visible_results
			if not result.get("status_matches_expected")
		],
		"top_failing_categories": [
			{"category": category, "count": count}
			for category, count in failing_categories.most_common()
		],
	}


def _print_progress(result: dict, index: int, total: int) -> None:
	query_id = result.get("id") or "unknown"
	status = result.get("status") or "unknown"
	rows = result.get("returned_rows")
	print(f"[{index}/{total}] {query_id}: {status} ({rows} row(s))")


def _write_json(path: Path, value: Any) -> None:
	with path.open("w", encoding="utf-8") as handle:
		json.dump(_json_safe(value), handle, ensure_ascii=False, indent=2, sort_keys=True)
		handle.write("\n")


def _json_safe(value: Any) -> Any:
	if isinstance(value, dict):
		return {str(key): _json_safe(item) for key, item in value.items()}
	if isinstance(value, (list, tuple)):
		return [_json_safe(item) for item in value]
	if isinstance(value, set):
		return sorted(_json_safe(item) for item in value)
	if isinstance(value, decimal.Decimal):
		return int(value) if value == value.to_integral_value() else float(value)
	if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
		return value.isoformat()
	if isinstance(value, float):
		if math.isnan(value) or math.isinf(value):
			return str(value)
		return value
	if isinstance(value, bytes):
		return value.decode("utf-8", errors="replace")
	if value is None or isinstance(value, (str, int, bool)):
		return value
	return str(value)
