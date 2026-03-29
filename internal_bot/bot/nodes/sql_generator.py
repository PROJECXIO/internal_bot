"""
Node 4 — SQL Generator

Calls the LLM to generate a SELECT SQL statement based on:
- Normalized question
- Schema context from Node 3
- Chat history and memory summary from Node 2
- Previous error (if this is a retry)
"""
import time

import frappe

from internal_bot.bot.services import sql_service
from internal_bot.bot.state import GraphState


def run(state: GraphState) -> dict:
	t0 = time.monotonic()
	node_name = "sql_generator"

	llm_client = state.get("_llm_client")
	if not llm_client:
		return _update(state, node_name, t0, {
			"generated_sql": "",
			"sql_generation_error": "No LLM client configured",
		})

	# Build memory context string
	memory_parts = []
	if state.get("memory_summary"):
		memory_parts.append(f"Previous context summary:\n{state['memory_summary']}")
	history = state.get("chat_history") or []
	if history:
		history_text = "\n".join(
			f"{m['role'].upper()}: {m['content']}" for m in history[-6:]  # last 3 exchanges
		)
		memory_parts.append(f"Recent messages:\n{history_text}")
	memory_context = "\n\n".join(memory_parts)

	attempt = state.get("sql_generation_attempts") or 0
	previous_error = (
		state.get("sql_execution_error")
		or state.get("sql_invalid_reason")
		or state.get("sql_generation_error")
		or None
	)

	try:
		sql = sql_service.generate_sql(
			question=state.get("normalized_question") or state.get("raw_message", ""),
			schema_context=state.get("schema_context") or "",
			memory_context=memory_context,
			llm_client=llm_client,
			attempt=attempt,
			previous_error=previous_error,
		)

		# Capture token usage from llm_client
		input_tokens = (state.get("input_tokens") or 0) + (getattr(llm_client, "last_input_tokens", 0) or 0)
		output_tokens = (state.get("output_tokens") or 0) + (getattr(llm_client, "last_output_tokens", 0) or 0)

		return _update(state, node_name, t0, {
			"generated_sql": sql,
			"sql_generation_error": "",
			"input_tokens": input_tokens,
			"output_tokens": output_tokens,
			"llm_provider": getattr(llm_client, "provider", ""),
			"llm_model": getattr(llm_client, "model", ""),
		})
	except Exception as exc:
		frappe.log_error(message=str(exc), title="SQLGenerator LLM error")
		return _update(state, node_name, t0, {
			"generated_sql": "",
			"sql_generation_error": str(exc),
		})


def _update(state: GraphState, node_name: str, t0: float, updates: dict) -> dict:
	elapsed = round((time.monotonic() - t0) * 1000, 2)
	trace = list(state.get("node_trace") or []) + [node_name]
	timing = dict(state.get("timing") or {})
	timing[node_name] = elapsed
	return {**updates, "node_trace": trace, "timing": timing}
