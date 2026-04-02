"""
Node 2 — Memory Loader

Loads the user's chat history (last N messages) and rolling summary
from the AI Chat Session.
"""
import time

from internal_bot.bot.services import memory as memory_svc
from internal_bot.bot.state import GraphState
from internal_bot.bot import progress, trace


def run(state: GraphState) -> dict:
	t0 = time.monotonic()
	node_name = "memory_loader"
	log_t0 = trace.node_start(state, node_name)
	if state.get("_emit_progress"):
		progress.emit(state, node_name, "Loading conversation history")

	settings = state.get("_settings")
	window_size = settings.memory_window if settings else 10

	mem = memory_svc.load_chat_memory(
		session_name=state["session_name"],
		window_size=window_size,
	)
	trace.detail(state, "Loaded history messages", len(mem["messages"]))

	return _update(state, node_name, t0, {
		"chat_history": mem["messages"],
		"memory_summary": mem["summary"],
		"last_user_question": mem.get("last_user_question") or "",
		"last_non_follow_up_user_question": mem.get("last_non_follow_up_user_question") or "",
		"last_assistant_response": mem.get("last_assistant_response") or {},
		"last_assistant_context_text": mem.get("last_assistant_context_text") or "",
		"last_discovered_doctypes": mem.get("last_discovered_doctypes") or [],
	}, log_t0)


def _update(state: GraphState, node_name: str, t0: float, updates: dict, log_t0: float) -> dict:
	elapsed = round((time.monotonic() - t0) * 1000, 2)
	trace = list(state.get("node_trace") or []) + [node_name]
	timing = dict(state.get("timing") or {})
	timing[node_name] = elapsed
	from internal_bot.bot import trace as bench_trace
	bench_trace.node_end(state, node_name, log_t0)
	return {**updates, "node_trace": trace, "timing": timing}
