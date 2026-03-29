"""
Builds the structured JSON response returned to the frontend.
"""
import json
import math
from typing import TYPE_CHECKING

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

	# ── SQL Error ───────────────────────────────────────────────────
	elif state.get("sql_execution_error") or (
		not state.get("sql_is_valid") and state.get("sql_generation_attempts", 0) >= 3
	):
		error_msg = state.get("sql_execution_error") or state.get("sql_invalid_reason", "Unknown error")
		response = {
			"status": "error",
			"reason": "Could not generate a valid query. Please rephrase your question.",
			"meta": {"confidence": 0.0, "error_detail": error_msg},
		}

	# ── Success ──────────────────────────────────────────────────────
	else:
		rows = state.get("sql_result_rows") or []
		columns = list(rows[0].keys()) if rows else []

		response = {
			"status": "success",
			"response_type": "table" if rows else "empty",
			"title": _make_title(state.get("normalized_question") or state.get("raw_message", "")),
			"columns": columns,
			"rows": _serialize_rows(rows),
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
			"generated_sql": state.get("generated_sql"),
			"validated_sql": state.get("validated_sql"),
			"retries": state.get("sql_generation_attempts", 0),
			"timing": state.get("timing", {}),
			"cache_hit": state.get("cache_hit", False),
			"provider": state.get("llm_provider"),
			"model": state.get("llm_model"),
			"node_trace": state.get("node_trace", []),
		}

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
	"""Heuristic confidence: penalise retries and cache misses."""
	base = 0.95
	retries = state.get("sql_generation_attempts", 0)
	base -= retries * 0.1
	return round(max(0.1, min(1.0, base)), 2)


def _serialize_rows(rows: list[dict]) -> list[dict]:
	"""Convert any non-JSON-serializable values (Decimal, date, etc.)."""
	import decimal
	import datetime

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
