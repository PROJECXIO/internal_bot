"""
Node 3 — Schema Discovery

Extracts keywords from the normalized question, discovers relevant
DocTypes, fetches their fields/links/sample rows, and builds a
Markdown schema context string for the SQL generator.
"""
import re
import time

from internal_bot.bot.services import schema as schema_svc
from internal_bot.bot.state import GraphState


# Common ERP stop words to ignore during keyword extraction
_STOP_WORDS = {
	"show", "me", "all", "the", "a", "an", "of", "in", "for", "and",
	"or", "is", "are", "was", "were", "what", "how", "many", "total",
	"list", "give", "get", "find", "fetch", "today", "yesterday",
	"last", "this", "month", "year", "week", "date", "time", "by",
	"from", "to", "with", "on", "at", "between", "latest", "recent",
}


def run(state: GraphState) -> dict:
	t0 = time.monotonic()
	node_name = "schema_discovery"

	question = state.get("normalized_question") or state.get("raw_message", "")
	settings = state.get("_settings")
	blocked = settings.get_blocked_doctype_list() if settings else []

	keywords = _extract_keywords(question)

	if not keywords:
		return _update(state, node_name, t0, {
			"discovered_doctypes": [],
			"schema_context": "",
		})

	discovered_rows = schema_svc.discover_doctypes(keywords, blocked)
	discovered_names = [r["name"] for r in discovered_rows]

	# Enrich each discovered DocType with fields, links, and sample rows
	enriched = []
	for row in discovered_rows[:5]:  # cap at 5 DocTypes to keep prompt size manageable
		name = row["name"]
		try:
			fields = schema_svc.get_doctype_fields(name)
			links = schema_svc.get_doctype_links(name)
			samples = schema_svc.get_sample_rows(name, limit=2)
		except Exception:
			fields, links, samples = [], [], []

		enriched.append({
			"name": name,
			"fields": fields,
			"links": links,
			"sample_rows": samples,
		})

	schema_ctx = schema_svc.build_schema_context(enriched)

	return _update(state, node_name, t0, {
		"discovered_doctypes": discovered_names,
		"schema_context": schema_ctx,
	})


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
