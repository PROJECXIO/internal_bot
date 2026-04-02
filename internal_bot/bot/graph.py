"""
LangGraph pipeline assembly for the Internal Bot.

Graph topology:
  memory_loader   ← loads chat history first so intent_classifier has context
      ↓
  intent_classifier
      ↓ (conditional)
      ├─ [greeting / blocked / clarification_needed] → result_formatter
      └─ [query] → schema_discovery   ← permission gates 1 & 2 applied here
                       ↓ (conditional)
                       ├─ [no_schema]           → result_formatter
                       ├─ [needs_clarification] → clarification_planner
                       │                              ↓ (conditional)
                       │                              ├─ [ready] → query_planner
                       │                              └─ [ask]   → result_formatter
                       └─ [schema_found]         → query_planner
                                                       ↓ (conditional, self-loop on retry)
                                                       ├─ [success]  → visualization_planner
                                                       │                  ↓
                                                       │             answer_composer
                                                       │                  ↓
                                                       │               analytics
                                                       ├─ [retry]    → query_planner (up to 3x)
                                                       └─ [give_up]  → result_formatter
                                                                             ↓
                                                                        analytics
                                                                             ↓
                                                                           END

The compiled graph is cached at the module level (safe: topology is static).
"""
from langgraph.graph import END, StateGraph

from internal_bot.bot.nodes import (
    answer_composer,
    analytics_node,
    clarification_planner,
    intent_classifier,
    memory_loader,
    query_planner,
    result_formatter,
    schema_discovery,
    visualization_planner,
)
from internal_bot.bot.state import GraphState
from internal_bot.bot import trace

_MAX_RETRIES = 3

# ──────────────────────────────────────────────────────────────────
# Routing functions (conditional edges)
# ──────────────────────────────────────────────────────────────────


def _route_after_intent(state: GraphState) -> str:
    intent = state.get("intent", "query")
    if intent in ("blocked", "clarification_needed", "greeting"):
        trace.route(state, "result_formatter")
        return "short_circuit"
    trace.route(state, "schema_discovery")
    return "proceed"


_PERIOD_PLACEHOLDERS = ("for a period", "for some period", "during a period", "for the period")


def _route_after_schema(state: GraphState) -> str:
    discovered = state.get("discovered_doctypes") or []
    if not discovered:
        trace.route(state, "result_formatter")
        return "no_schema"
    if len(discovered) > 1:
        trace.route(state, "clarification_planner")
        return "needs_clarification"
    # Single DocType resolved, but check if the question has a vague period
    # placeholder that needs clarification before querying.
    question = (state.get("normalized_question") or "").lower()
    if any(p in question for p in _PERIOD_PLACEHOLDERS):
        trace.route(state, "clarification_planner")
        return "needs_clarification"
    trace.route(state, "query_planner")
    return "schema_found"


def _route_after_clarification(state: GraphState) -> str:
    if state.get("ready_to_query"):
        trace.route(state, "query_planner")
        return "ready"
    trace.route(state, "result_formatter")
    return "ask"


def _route_after_planning(state: GraphState) -> str:
    if state.get("query_is_valid"):
        trace.route(state, "visualization_planner")
        return "success"
    attempts = state.get("query_generation_attempts") or 0
    if attempts < _MAX_RETRIES:
        trace.route(state, "query_planner")
        return "retry"
    trace.route(state, "result_formatter")
    return "give_up"


# ──────────────────────────────────────────────────────────────────
# Graph builder
# ──────────────────────────────────────────────────────────────────


def _build_graph():
    g = StateGraph(GraphState)

    # Register nodes
    g.add_node("intent_classifier", intent_classifier.run)
    g.add_node("memory_loader", memory_loader.run)
    g.add_node("schema_discovery", schema_discovery.run)
    g.add_node("clarification_planner", clarification_planner.run)
    g.add_node("query_planner", query_planner.run)
    g.add_node("visualization_planner", visualization_planner.run)
    g.add_node("answer_composer", answer_composer.run)
    g.add_node("result_formatter", result_formatter.run)
    g.add_node("analytics", analytics_node.run)

    # Entry point: load memory first so intent_classifier has conversation context
    g.set_entry_point("memory_loader")

    # memory_loader → intent_classifier (now has chat_history available)
    g.add_edge("memory_loader", "intent_classifier")

    # intent_classifier → branch on intent
    g.add_conditional_edges(
        "intent_classifier",
        _route_after_intent,
        {
            "proceed": "schema_discovery",
            "short_circuit": "result_formatter",
        },
    )

    # schema_discovery → no match, ambiguous (multi), or clear (single)
    g.add_conditional_edges(
        "schema_discovery",
        _route_after_schema,
        {
            "no_schema": "result_formatter",
            "needs_clarification": "clarification_planner",
            "schema_found": "query_planner",
        },
    )

    # clarification_planner → ask user or proceed to query
    g.add_conditional_edges(
        "clarification_planner",
        _route_after_clarification,
        {
            "ready": "query_planner",
            "ask": "result_formatter",
        },
    )

    # query_planner → branch on success / retry (self-loop) / give_up
    g.add_conditional_edges(
        "query_planner",
        _route_after_planning,
        {
            "success": "visualization_planner",
            "retry": "query_planner",
            "give_up": "result_formatter",
        },
    )

    g.add_edge("visualization_planner", "answer_composer")
    g.add_edge("answer_composer", "analytics")

    # Non-success paths converge at result_formatter → analytics → END
    g.add_edge("result_formatter", "analytics")
    g.add_edge("analytics", END)

    return g.compile(name="internal_bot_graph")


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
