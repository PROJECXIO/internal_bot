"""
Node 2 — Memory Loader

Loads the user's chat history (last N messages) and rolling summary
from the AI Chat Session.
"""
import time

from internal_bot.bot.services import memory as memory_svc
from internal_bot.bot.state import GraphState


def run(state: GraphState) -> dict:
	t0 = time.monotonic()
	node_name = "memory_loader"

	settings = state.get("_settings")
	window_size = settings.memory_window if settings else 10

	mem = memory_svc.load_chat_memory(
		session_name=state["session_name"],
		window_size=window_size,
	)

	return _update(state, node_name, t0, {
		"chat_history": mem["messages"],
		"memory_summary": mem["summary"],
	})


def _update(state: GraphState, node_name: str, t0: float, updates: dict) -> dict:
	elapsed = round((time.monotonic() - t0) * 1000, 2)
	trace = list(state.get("node_trace") or []) + [node_name]
	timing = dict(state.get("timing") or {})
	timing[node_name] = elapsed
	return {**updates, "node_trace": trace, "timing": timing}
