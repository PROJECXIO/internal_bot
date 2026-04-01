"""
Node 7 — Result Formatter

Builds the final structured JSON response dict and stores it in state.
Handles all four status codes: success, clarification_needed, blocked, error.
"""
import time

from internal_bot.bot.services.formatter import format_structured_response
from internal_bot.bot.state import GraphState
from internal_bot.bot import progress


def run(state: GraphState) -> dict:
	t0 = time.monotonic()
	node_name = "result_formatter"
	if state.get("_emit_progress"):
		progress.emit(state, node_name, "Preparing response")

	# No matching DocTypes were found — tell the user immediately
	if not state.get("discovered_doctypes") and state.get("intent") == "query":
		formatted = {
			"status": "clarification_needed",
			"question": (
				"I couldn't find any relevant data for your question. "
				"Could you rephrase it or be more specific about what you're looking for?"
			),
		}
	else:
		formatted = format_structured_response(state)

	return _update(
		state,
		node_name,
		t0,
		{
			"formatted_response": formatted,
			"response_type": formatted.get("response_type"),
			"visualization": formatted.get("visualization"),
			"summary": formatted.get("summary"),
			"visualization_preference": formatted.get("debug", {}).get("visualization_preference"),
		},
	)


def _update(state: GraphState, node_name: str, t0: float, updates: dict) -> dict:
	elapsed = round((time.monotonic() - t0) * 1000, 2)
	trace = list(state.get("node_trace") or []) + [node_name]
	timing = dict(state.get("timing") or {})
	timing[node_name] = elapsed
	return {**updates, "node_trace": trace, "timing": timing}
