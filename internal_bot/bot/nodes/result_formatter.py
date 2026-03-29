"""
Node 7 — Result Formatter

Builds the final structured JSON response dict and stores it in state.
Handles all four status codes: success, clarification_needed, blocked, error.
Cache hits are passed through here with the cached_result already populated.
"""
import time

from internal_bot.bot.services.formatter import format_structured_response
from internal_bot.bot.state import GraphState


def run(state: GraphState) -> dict:
	t0 = time.monotonic()
	node_name = "result_formatter"

	# If this is a cache hit, the cached_result is the response
	if state.get("cache_hit") and state.get("cached_result"):
		response = dict(state["cached_result"])
		# Re-attach debug fields if requested
		if state.get("debug"):
			response["debug"] = {
				"normalized_question": state.get("normalized_question"),
				"discovered_entities": state.get("discovered_doctypes", []),
				"generated_sql": None,
				"validated_sql": None,
				"retries": 0,
				"timing": state.get("timing", {}),
				"cache_hit": True,
				"provider": state.get("llm_provider"),
				"model": state.get("llm_model"),
				"node_trace": list(state.get("node_trace") or []) + [node_name],
			}
		formatted = response
	else:
		formatted = format_structured_response(state)

	return _update(state, node_name, t0, {"formatted_response": formatted})


def _update(state: GraphState, node_name: str, t0: float, updates: dict) -> dict:
	elapsed = round((time.monotonic() - t0) * 1000, 2)
	trace = list(state.get("node_trace") or []) + [node_name]
	timing = dict(state.get("timing") or {})
	timing[node_name] = elapsed
	return {**updates, "node_trace": trace, "timing": timing}
