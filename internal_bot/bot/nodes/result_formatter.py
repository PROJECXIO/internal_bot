"""
Node 7 — Result Formatter

Builds the final structured JSON response dict and stores it in state.
Handles all four status codes: success, clarification_needed, blocked, error.
"""
import time

from internal_bot.bot.services.formatter import format_structured_response
from internal_bot.bot.services.language import localize_text
from internal_bot.bot.state import GraphState
from internal_bot.bot import progress, trace


def run(state: GraphState) -> dict:
	t0 = time.monotonic()
	node_name = "result_formatter"
	log_t0 = trace.node_start(state, node_name)
	if state.get("_emit_progress"):
		progress.emit(state, node_name, "Preparing response")
	response_language = state.get("response_language") or state.get("user_profile_language") or "en"

	# Clarification planner has a question to ask
	if state.get("clarification_question") and not state.get("ready_to_query"):
		formatted = {
			"status": "clarification_needed",
			"question": state["clarification_question"],
			"options": state.get("clarification_options") or [],
			"markdown": state["clarification_question"],
		}

	# No matching DocTypes were found — tell the user immediately
	elif not state.get("discovered_doctypes") and state.get("intent") == "query":
		candidates = state.get("schema_candidates") or []
		options = [candidate[0] for candidate in candidates[:5]]
		question_text = localize_text(
			"I found some possible matches. Did you mean one of these?",
			response_language,
			llm_client=state.get("_llm_client"),
		)[0] if options else localize_text(
			"I couldn't find matching data. Could you specify what type of document you're looking for?",
			response_language,
			llm_client=state.get("_llm_client"),
		)[0]
		formatted = {
			"status": "clarification_needed",
			"question": question_text,
			"options": options,
			"markdown": question_text,
		}
	else:
		formatted = format_structured_response(state)
	trace.detail(state, "Formatted status", formatted.get("status"))
	trace.detail(state, "Response type", formatted.get("response_type") or "n/a")

	return _update(
		state,
		node_name,
		t0,
		{
			"formatted_response": formatted,
			"response_type": formatted.get("response_type"),
			"visualization": formatted.get("visualization"),
			"summary": formatted.get("summary"),
			"answer_prefix": formatted.get("answer_prefix", ""),
			"answer_markdown": formatted.get("markdown", ""),
			"visualization_preference": formatted.get("debug", {}).get("visualization_preference"),
		},
		log_t0,
	)


def _update(state: GraphState, node_name: str, t0: float, updates: dict, log_t0: float) -> dict:
	elapsed = round((time.monotonic() - t0) * 1000, 2)
	trace = list(state.get("node_trace") or []) + [node_name]
	timing = dict(state.get("timing") or {})
	timing[node_name] = elapsed
	from internal_bot.bot import trace as bench_trace
	bench_trace.node_end(state, node_name, log_t0)
	return {**updates, "node_trace": trace, "timing": timing}
