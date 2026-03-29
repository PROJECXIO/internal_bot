"""
LangGraph pipeline assembly for the Internal Bot.

Graph topology:
  intent_parser
      ↓ (conditional)
      ├─ [greeting / blocked / clarification_needed] → result_formatter
      └─ [query] → memory_loader
                       ↓
                  schema_discovery
                       ↓
                   cache_check
                       ↓ (conditional)
                       ├─ [cache_hit] → result_formatter
                       └─ [cache_miss] → sql_generator
                                              ↓
                                         sql_validator
                                              ↓ (conditional)
                                              ├─ [valid]   → sql_executor
                                              ├─ [retry]   → sql_generator  (up to 3x)
                                              └─ [give_up] → result_formatter
                                                                    ↓
                                                               analytics
                                                                    ↓
                                                                  END

The compiled graph is cached at the module level.
This is safe because the graph topology is static; only state data changes
per invocation.  (Frappe worker processes are per-site, so module-level
state is site-scoped.)
"""
from langgraph.graph import END, StateGraph

from internal_bot.bot.nodes import (
	analytics_node,
	cache_node,
	intent_parser,
	memory_loader,
	result_formatter,
	schema_discovery,
	sql_executor,
	sql_generator,
	sql_validator,
)
from internal_bot.bot.state import GraphState

_MAX_RETRIES = 3

# ──────────────────────────────────────────────────────────────────
# Routing functions (conditional edges)
# ──────────────────────────────────────────────────────────────────


def _route_after_intent(state: GraphState) -> str:
	intent = state.get("intent", "query")
	if intent in ("blocked", "clarification_needed", "greeting"):
		return "short_circuit"
	return "proceed"


def _route_after_cache(state: GraphState) -> str:
	return "cache_hit" if state.get("cache_hit") else "cache_miss"


def _route_after_validation(state: GraphState) -> str:
	if state.get("sql_is_valid"):
		return "valid"
	attempts = state.get("sql_generation_attempts") or 0
	if attempts < _MAX_RETRIES:
		return "retry"
	return "give_up"


# ──────────────────────────────────────────────────────────────────
# Graph builder
# ──────────────────────────────────────────────────────────────────


def _build_graph():
	g = StateGraph(GraphState)

	# Register nodes
	g.add_node("intent_parser", intent_parser.run)
	g.add_node("memory_loader", memory_loader.run)
	g.add_node("schema_discovery", schema_discovery.run)
	g.add_node("cache_check", cache_node.run)
	g.add_node("sql_generator", sql_generator.run)
	g.add_node("sql_validator", sql_validator.run)
	g.add_node("sql_executor", sql_executor.run)
	g.add_node("result_formatter", result_formatter.run)
	g.add_node("analytics", analytics_node.run)

	# Entry point
	g.set_entry_point("intent_parser")

	# intent_parser → branch on intent
	g.add_conditional_edges(
		"intent_parser",
		_route_after_intent,
		{
			"proceed": "memory_loader",
			"short_circuit": "result_formatter",
		},
	)

	# Linear: memory → schema → cache
	g.add_edge("memory_loader", "schema_discovery")
	g.add_edge("schema_discovery", "cache_check")

	# cache_check → branch on cache hit/miss
	g.add_conditional_edges(
		"cache_check",
		_route_after_cache,
		{
			"cache_hit": "result_formatter",
			"cache_miss": "sql_generator",
		},
	)

	# sql_generator → validator
	g.add_edge("sql_generator", "sql_validator")

	# sql_validator → branch on validity / retry / give_up
	g.add_conditional_edges(
		"sql_validator",
		_route_after_validation,
		{
			"valid": "sql_executor",
			"retry": "sql_generator",
			"give_up": "result_formatter",
		},
	)

	# sql_executor → formatter
	g.add_edge("sql_executor", "result_formatter")

	# All paths converge at result_formatter → analytics → END
	g.add_edge("result_formatter", "analytics")
	g.add_edge("analytics", END)

	return g.compile()


# ──────────────────────────────────────────────────────────────────
# Module-level compiled graph cache
# ──────────────────────────────────────────────────────────────────

_compiled_graph = None


def get_graph():
	"""Return the compiled LangGraph (builds once per worker process)."""
	global _compiled_graph
	if _compiled_graph is None:
		_compiled_graph = _build_graph()
	return _compiled_graph


def reset_graph():
	"""Force recompilation on next call (useful in tests)."""
	global _compiled_graph
	_compiled_graph = None
