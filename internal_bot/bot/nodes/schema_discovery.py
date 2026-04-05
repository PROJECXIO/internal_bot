"""
Node 3 — Schema Discovery

Hybrid schema retrieval using multilingual normalization, aliases,
lexical overlap, and optional embeddings.
"""
import time

import frappe

from internal_bot.bot.services import schema as schema_svc
from internal_bot.bot.services import hybrid_scorer, schema_corpus
from internal_bot.bot.services.text_normalizer import normalize_text, remove_stop_words, tokenize
from internal_bot.bot.state import GraphState
from internal_bot.bot import progress, trace


def run(state: GraphState) -> dict:
    t0 = time.monotonic()
    node_name = "schema_discovery"
    log_t0 = trace.node_start(state, node_name)
    if state.get("_emit_progress"):
        progress.emit(state, node_name, "Looking at relevant data")

    user = state.get("user") or frappe.session.user
    question = state.get("normalized_question") or state.get("raw_message", "")
    llm_client = state.get("_llm_client")
    settings = state.get("_settings")
    blocked = set(settings.get_blocked_doctype_list() if settings else [])
    normalized_question = normalize_text(question)
    query_tokens = remove_stop_words(tokenize(normalized_question))
    trace.detail(state, "Normalized question", normalized_question)
    trace.detail(state, "Query tokens", query_tokens)

    if not query_tokens and not state.get("follow_up_to_previous_result"):
        return _update(state, node_name, t0, {
            "discovered_doctypes": [],
            "schema_context": "",
            "schema_confidence": 0.0,
            "schema_decision": "no_match",
            "schema_candidates": [],
        }, log_t0)

    corpus = schema_corpus.get_corpus(blocked)
    if llm_client:
        corpus = schema_corpus.compute_and_cache_embeddings(corpus, llm_client)

    query_embedding = None
    if llm_client:
        embedding_result = llm_client.create_embeddings([question])
        if embedding_result and isinstance(embedding_result, list):
            first_embedding = embedding_result[0] if embedding_result else None
            if isinstance(first_embedding, list):
                query_embedding = first_embedding

    candidates = hybrid_scorer.rank_candidates(
        query=question,
        corpus=corpus,
        user=user,
        blocked=blocked,
        query_embedding=query_embedding,
        preferred_doctypes=state.get("last_discovered_doctypes") or [],
        follow_up_to_previous_result=bool(state.get("follow_up_to_previous_result")),
    )
    decision, selected_candidates = hybrid_scorer.classify_confidence(candidates)
    previous_doctypes = set(state.get("last_discovered_doctypes") or [])
    if previous_doctypes and decision in ("ambiguous", "low_confidence"):
        preferred = next(
            (candidate for candidate in selected_candidates if candidate.doctype_name in previous_doctypes),
            None,
        )
        if preferred:
            selected_candidates = [preferred]
            decision = "clear_winner"
            trace.detail(state, "Preferring previous doctype", preferred.doctype_name)

    discovered_names = [candidate.doctype_name for candidate in selected_candidates]
    trace.detail(state, "Schema decision", decision)
    trace.detail(
        state,
        "Schema candidates",
        [f"{candidate.doctype_name}:{candidate.final_score}" for candidate in candidates[:5]],
    )

    # Enrich each discovered DocType with permission-filtered fields and links
    enriched = []
    for name in discovered_names[:5]:
        try:
            # Gate 2: get_doctype_fields with user strips permlevel-restricted fields
            fields = schema_svc.get_doctype_fields(name, user=user)
            links = schema_svc.get_doctype_links(name)
        except Exception:
            fields, links = [], []

        enriched.append({
            "name": name,
            "fields": fields,
            "links": links,
        })

    schema_ctx = schema_svc.build_schema_context(enriched)
    schema_confidence = round(selected_candidates[0].final_score, 4) if selected_candidates else 0.0
    schema_candidates = [
        (candidate.doctype_name, round(candidate.final_score, 4))
        for candidate in candidates[:5]
    ]

    return _update(state, node_name, t0, {
        "discovered_doctypes": discovered_names,
        "schema_context": schema_ctx,
        "schema_confidence": schema_confidence,
        "schema_decision": decision,
        "schema_candidates": schema_candidates,
    }, log_t0)


def _update(state: GraphState, node_name: str, t0: float, updates: dict, log_t0: float) -> dict:
    elapsed = round((time.monotonic() - t0) * 1000, 2)
    trace = list(state.get("node_trace") or []) + [node_name]
    timing = dict(state.get("timing") or {})
    timing[node_name] = elapsed
    from internal_bot.bot import trace as bench_trace
    bench_trace.node_end(state, node_name, log_t0)
    return {**updates, "node_trace": trace, "timing": timing}
