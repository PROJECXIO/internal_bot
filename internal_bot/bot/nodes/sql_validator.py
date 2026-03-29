"""
Node 5 — SQL Validator

Validates the generated SQL for safety.
- Blocks non-SELECT statements
- Blocks blocked keywords (INSERT, UPDATE, DELETE, etc.)
- Blocks blocked DocType tables

On failure, increments sql_generation_attempts (up to 3).
The graph's conditional edge decides whether to retry (→ sql_generator)
or give up (→ result_formatter with error).
"""
import time

from internal_bot.bot.services import sql_service
from internal_bot.bot.state import GraphState

MAX_RETRIES = 3


def run(state: GraphState) -> dict:
	t0 = time.monotonic()
	node_name = "sql_validator"

	sql = state.get("generated_sql") or ""
	settings = state.get("_settings")
	blocked = settings.get_blocked_doctype_list() if settings else []

	is_valid, reason = sql_service.validate_sql(sql, blocked)

	attempts = (state.get("sql_generation_attempts") or 0)
	if not is_valid:
		attempts += 1

	updates = {
		"sql_is_valid": is_valid,
		"sql_invalid_reason": reason if not is_valid else "",
		"validated_sql": sql if is_valid else "",
		"sql_generation_attempts": attempts,
		"retries": attempts,
	}

	return _update(state, node_name, t0, updates)


def _update(state: GraphState, node_name: str, t0: float, updates: dict) -> dict:
	elapsed = round((time.monotonic() - t0) * 1000, 2)
	trace = list(state.get("node_trace") or []) + [node_name]
	timing = dict(state.get("timing") or {})
	timing[node_name] = elapsed
	return {**updates, "node_trace": trace, "timing": timing}
