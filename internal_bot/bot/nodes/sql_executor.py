"""
Node 6 — SQL Executor

Runs the validated SELECT query via frappe.db.sql (read-only).
Enforces the max_result_rows limit.
"""
import time

import frappe

from internal_bot.bot.services import sql_service
from internal_bot.bot.state import GraphState


def run(state: GraphState) -> dict:
	t0 = time.monotonic()
	node_name = "sql_executor"

	sql = state.get("validated_sql") or ""
	settings = state.get("_settings")
	max_rows = settings.max_result_rows if settings else 100

	try:
		rows = sql_service.execute_sql_readonly(sql, max_rows=max_rows)
		return _update(state, node_name, t0, {
			"sql_result_rows": rows,
			"sql_execution_error": "",
			"result_row_count": len(rows),
		})
	except Exception as exc:
		frappe.log_error(message=str(exc), title="SQLExecutor error")
		attempts = (state.get("sql_generation_attempts") or 0) + 1
		return _update(state, node_name, t0, {
			"sql_result_rows": [],
			"sql_execution_error": str(exc),
			"result_row_count": 0,
			"sql_generation_attempts": attempts,
			"retries": attempts,
		})


def _update(state: GraphState, node_name: str, t0: float, updates: dict) -> dict:
	elapsed = round((time.monotonic() - t0) * 1000, 2)
	trace = list(state.get("node_trace") or []) + [node_name]
	timing = dict(state.get("timing") or {})
	timing[node_name] = elapsed
	return {**updates, "node_trace": trace, "timing": timing}
