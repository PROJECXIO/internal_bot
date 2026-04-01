"""
Node 3 — Schema Discovery

Extracts keywords from the normalized question, discovers relevant
DocTypes (permission-gated), fetches their permitted fields and links,
and builds a Markdown schema context string for the query planner.

Permission gates applied here:
  Gate 1 — DocType access: only DocTypes the user can read are surfaced.
  Gate 2 — Field visibility: only fields the user can see are included.

Sample rows are intentionally excluded (they could expose real data to the LLM).
"""
import re
import time

import frappe

from internal_bot.bot.services import schema as schema_svc
from internal_bot.bot.state import GraphState
from internal_bot.bot import progress


# Common ERP stop words to ignore during keyword extraction
_STOP_WORDS = {
    "show", "me", "all", "the", "a", "an", "of", "in", "for", "and",
    "or", "is", "are", "was", "were", "what", "how", "many", "total",
    "list", "give", "get", "find", "fetch", "today", "yesterday",
    "last", "this", "month", "year", "week", "date", "time", "by",
    "from", "to", "with", "on", "at", "between", "latest", "recent",
    "per", "each", "every", "day", "days", "count", "number", "num",
}


def run(state: GraphState) -> dict:
    t0 = time.monotonic()
    node_name = "schema_discovery"
    if state.get("_emit_progress"):
        progress.emit(state, node_name, "Looking at relevant data")

    user = state.get("user") or frappe.session.user
    question = state.get("normalized_question") or state.get("raw_message", "")
    settings = state.get("_settings")
    blocked = settings.get_blocked_doctype_list() if settings else []

    keywords = _extract_keywords(question)

    if not keywords:
        return _update(state, node_name, t0, {
            "discovered_doctypes": [],
            "schema_context": "",
        })

    # Gate 1: discover_permitted_doctypes filters by frappe.has_permission
    discovered_rows = schema_svc.discover_permitted_doctypes(keywords, user, blocked)
    # Re-rank by match quality so the most relevant DocType isn't cut off by the cap
    discovered_rows = _rank_by_relevance(discovered_rows, keywords)
    discovered_names = [r["name"] for r in discovered_rows]

    # Enrich each discovered DocType with permission-filtered fields and links
    enriched = []
    for row in discovered_rows[:5]:  # cap at 5 DocTypes to keep prompt size manageable
        name = row["name"]
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

    return _update(state, node_name, t0, {
        "discovered_doctypes": discovered_names,
        "schema_context": schema_ctx,
    })


def _rank_by_relevance(rows: list, keywords: list) -> list:
    """
    Sort discovered DocTypes so the closest keyword match comes first.
    Score = length of the longest keyword that appears in the lowercased name.
    A longer keyword match (e.g. bigram "sales invoice") is more specific than
    a short unigram match (e.g. "invoice"), so it ranks higher.
    """
    def score(row):
        name_lower = row["name"].lower()
        return max((len(kw) for kw in keywords if kw in name_lower), default=0)

    return sorted(rows, key=score, reverse=True)


def _extract_keywords(question: str) -> list:
    """Extract meaningful noun-like tokens from the question."""
    words = re.findall(r"[a-z]+", question.lower())
    keywords = [w for w in words if w not in _STOP_WORDS and len(w) > 2]
    # Also add 2-gram combinations (e.g. "sales invoice", "purchase order")
    bigrams = [f"{keywords[i]} {keywords[i+1]}" for i in range(len(keywords) - 1)]
    return list(dict.fromkeys(keywords + bigrams))  # deduplicate, preserve order


def _update(state: GraphState, node_name: str, t0: float, updates: dict) -> dict:
    elapsed = round((time.monotonic() - t0) * 1000, 2)
    trace = list(state.get("node_trace") or []) + [node_name]
    timing = dict(state.get("timing") or {})
    timing[node_name] = elapsed
    return {**updates, "node_trace": trace, "timing": timing}
