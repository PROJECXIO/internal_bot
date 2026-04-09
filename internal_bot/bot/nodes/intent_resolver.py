"""
Node: Intent Resolver (Thinking Node)

Runs when schema_discovery returns "ambiguous" or "low_confidence" —
i.e. multiple DocTypes matched but none was a clear winner.

Uses the LLM with chain-of-thought reasoning to decide whether the
intended DocType can be inferred from the question alone, without
asking the user.

If it can resolve: narrows discovered_doctypes to the single winner
and sets schema_decision = "clear_winner" so the graph skips
clarification_planner and goes straight to query_planner.

If it cannot resolve: leaves state unchanged so clarification_planner
takes over as normal.
"""
import json
import re
import time

import frappe

from internal_bot.bot.state import GraphState
from internal_bot.bot import progress, trace
from internal_bot.bot.services import schema as schema_svc
from internal_bot.bot.services import schema_field_filter

_SYSTEM_PROMPT = """\
You are a reasoning assistant for an ERP query system.

A user asked a question and the system found multiple matching document types (DocTypes).
Your job: reason through the question and decide whether the intended DocType is clear
enough to proceed without asking the user.

Think step by step before deciding. Consider:
1. What domain does the question belong to? (sales, purchasing, inventory, accounting...)
2. What action or data is the user asking about? (totals, quantities, comparisons, lists...)
3. Which of the candidate DocTypes is the primary transactional document for that domain?
4. Does the question contain any word, phrase, or implication that strongly points to one DocType?

Output ONLY valid JSON — no markdown fences.

If you can resolve with high confidence:
{"resolved": true, "doctype": "<exact DocType name from the list>", "reason": "<one line>"}

If genuinely ambiguous (two or more DocTypes are equally plausible):
{"resolved": false, "reason": "<one line explaining why it is unclear>"}

Rules:
- Only pick a DocType that is in the Matching DocTypes list.
- "High confidence" means you would bet on it — not just a guess.
- When the question is about selling items to customers, prefer Sales Invoice over Sales Order or Quotation unless the question explicitly mentions orders or quotes.
- When the question is about purchasing, prefer Purchase Invoice over Purchase Order.
- When the question mentions prices or price lists only (not transactions), prefer Item Price.
- Do NOT output anything other than the JSON object.
"""


def run(state: GraphState) -> dict:
	t0 = time.monotonic()
	node_name = "intent_resolver"
	log_t0 = trace.node_start(state, node_name)
	if state.get("_emit_progress"):
		progress.emit(state, node_name, "Understanding your question")

	llm_client = state.get("_llm_client")
	if not llm_client:
		return _unchanged(state, node_name, t0, log_t0)

	discovered = state.get("discovered_doctypes") or []
	if len(discovered) <= 1:
		return _unchanged(state, node_name, t0, log_t0)

	question = state.get("normalized_question") or state.get("raw_message", "")
	schema_context = state.get("schema_context") or ""

	user_content = (
		f"## Question\n{question}\n\n"
		f"## Matching DocTypes\n{', '.join(discovered)}"
	)
	if schema_context:
		user_content += f"\n\n## Schema Summary\n{schema_context[:800]}"

	messages = [
		{"role": "system", "content": _SYSTEM_PROMPT},
		{"role": "user", "content": user_content},
	]

	try:
		raw = llm_client.chat_completion(
			messages,
			temperature=0.0,
			max_tokens=200,
			**trace.llm_trace_context(state, node_name, "resolve_intent"),
		)
		input_tokens = (state.get("input_tokens") or 0) + (getattr(llm_client, "last_input_tokens", 0) or 0)
		output_tokens = (state.get("output_tokens") or 0) + (getattr(llm_client, "last_output_tokens", 0) or 0)
		result = _parse(raw)
		trace.detail(state, "Intent resolver result", result)
	except Exception as exc:
		frappe.log_error(str(exc), "IntentResolver LLM error")
		return _unchanged(state, node_name, t0, log_t0)

	if result.get("resolved") and result.get("doctype") in discovered:
		winner = result["doctype"]
		trace.detail(state, "Intent resolver winner", winner)

		# Rebuild schema_context for only the winning DocType, with field-level
		# embedding filtering to keep only the most relevant fields/child tables.
		new_schema_ctx = _build_filtered_schema(state, winner, question, llm_client)
		trace.detail(state, "Filtered schema tokens (approx)", len(new_schema_ctx) // 4)

		return _update(state, node_name, t0, {
			"discovered_doctypes": [winner],
			"schema_decision": "clear_winner",
			"schema_context": new_schema_ctx,
			"input_tokens": input_tokens,
			"output_tokens": output_tokens,
			"llm_provider": getattr(llm_client, "provider", ""),
			"llm_model": getattr(llm_client, "model", ""),
		}, log_t0)

	trace.detail(state, "Intent resolver", f"unresolved — {result.get('reason', '')}")
	return _update(state, node_name, t0, {
		"input_tokens": input_tokens,
		"output_tokens": output_tokens,
		"llm_provider": getattr(llm_client, "provider", ""),
		"llm_model": getattr(llm_client, "model", ""),
	}, log_t0)


def _build_filtered_schema(state: GraphState, winner: str, question: str, llm_client) -> str:
	"""Return a compact schema_context string for the winning DocType only.

	Uses embedding-based field filtering when available; falls back to heuristic.
	Falls back to the full winner schema if enriched data is not in state.
	"""
	enriched_schemas = state.get("enriched_schemas_by_doctype") or {}
	winner_schema = enriched_schemas.get(winner)
	if not winner_schema:
		# No enriched data — return the original full schema_context unchanged
		return state.get("schema_context") or ""

	query_embedding = state.get("query_embedding")

	try:
		filtered_fields, filtered_children = schema_field_filter.filter_schema_for_query(
			question=question,
			query_embedding=query_embedding,
			fields=winner_schema.get("fields") or [],
			child_tables=winner_schema.get("child_tables") or [],
			llm_client=llm_client,
			doctype_name=winner,
		)
		filtered_entry = {
			**winner_schema,
			"fields": filtered_fields,
			"child_tables": filtered_children,
		}
		return schema_svc.build_schema_context([filtered_entry])
	except Exception as exc:
		frappe.log_error(str(exc), "IntentResolver: schema filtering failed")
		# Fall back to full single-doctype schema
		return schema_svc.build_schema_context([winner_schema])


def _parse(raw: str) -> dict:
	cleaned = raw.strip()
	match = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned, re.IGNORECASE)
	if match:
		cleaned = match.group(1).strip()
	try:
		return json.loads(cleaned)
	except Exception:
		return {"resolved": False}


def _unchanged(state: GraphState, node_name: str, t0: float, log_t0: float) -> dict:
	return _update(state, node_name, t0, {}, log_t0)


def _update(state: GraphState, node_name: str, t0: float, updates: dict, log_t0: float) -> dict:
	elapsed = round((time.monotonic() - t0) * 1000, 2)
	node_trace = list(state.get("node_trace") or []) + [node_name]
	timing = dict(state.get("timing") or {})
	timing[node_name] = elapsed
	from internal_bot.bot import trace as bench_trace
	bench_trace.node_end(state, node_name, log_t0)
	return {**updates, "node_trace": node_trace, "timing": timing}
