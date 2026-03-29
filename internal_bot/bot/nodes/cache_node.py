"""
Node 8 — Cache Check (positioned before SQL generation in graph order)

Looks up the AI Query Cache for an existing answer to the normalized question.
On a hit, populates cached_result and sets cache_hit=True so the graph
can skip SQL generation and jump directly to the result formatter.
"""
import time

from internal_bot.bot.services import cache_service
from internal_bot.bot.state import GraphState


def run(state: GraphState) -> dict:
	t0 = time.monotonic()
	node_name = "cache_check"

	settings = state.get("_settings")
	enable_cache = settings.enable_cache if settings else True

	if not enable_cache:
		return _update(state, node_name, t0, {"cache_hit": False, "cached_result": None})

	normalized = state.get("normalized_question") or ""
	if not normalized:
		return _update(state, node_name, t0, {"cache_hit": False, "cached_result": None})

	query_hash = cache_service.make_query_hash(normalized)
	cached = cache_service.lookup_query_cache(query_hash)

	if cached:
		return _update(state, node_name, t0, {
			"cache_hit": True,
			"cached_result": cached,
			# Expose for analytics
			"_cache_query_hash": query_hash,
		})

	return _update(state, node_name, t0, {
		"cache_hit": False,
		"cached_result": None,
		"_cache_query_hash": query_hash,
	})


def _update(state: GraphState, node_name: str, t0: float, updates: dict) -> dict:
	elapsed = round((time.monotonic() - t0) * 1000, 2)
	trace = list(state.get("node_trace") or []) + [node_name]
	timing = dict(state.get("timing") or {})
	timing[node_name] = elapsed
	return {**updates, "node_trace": trace, "timing": timing}
