"""
GraphState — the single mutable dict that flows through the LangGraph pipeline.

All nodes read from and write to this TypedDict.
LangGraph requires a TypedDict (not dataclass or BaseModel).
"""
from typing import Any, Optional, TypedDict


class GraphState(TypedDict, total=False):
	# ── Inputs (set at graph entry) ─────────────────────────────────
	user: str               # frappe.session.user
	raw_message: str        # original user input
	session_name: str       # AI Chat Session name (= user email)
	debug: bool             # include debug fields in response?
	max_rows: int           # from AI Provider Settings.max_result_rows

	# ── Node 1: Intent Parser ────────────────────────────────────────
	normalized_question: str
	intent: str             # "greeting" | "query" | "clarification_needed" | "blocked"
	intent_reason: str      # free-text reason (shown for blocked/clarification)
	clarification_options: list  # options list for clarification_needed

	# ── Node 2: Memory Loader ────────────────────────────────────────
	chat_history: list      # [{"role": "user"|"assistant", "content": "..."}]
	memory_summary: str     # rolling LLM summary of older messages

	# ── Node 3: Schema Discovery ─────────────────────────────────────
	discovered_doctypes: list   # ["Sales Invoice", "Customer", ...]
	schema_context: str         # Markdown-formatted schema for LLM prompt

	# ── Node 8: Cache Check (runs before SQL gen) ────────────────────
	cache_hit: bool
	cached_result: Optional[dict]

	# ── Node 4: SQL Generator ────────────────────────────────────────
	generated_sql: str
	sql_generation_attempts: int    # 0-3
	sql_generation_error: str

	# ── Node 5: SQL Validator ────────────────────────────────────────
	validated_sql: str
	sql_is_valid: bool
	sql_invalid_reason: str

	# ── Node 6: SQL Executor ─────────────────────────────────────────
	sql_result_rows: list   # list of row dicts
	sql_execution_error: str

	# ── Node 7: Result Formatter ─────────────────────────────────────
	formatted_response: dict    # final API response

	# ── Per-request injected objects (must be in schema for LangGraph to preserve) ──
	_llm_client: Any   # LLMClient instance, injected in chat.py
	_settings: Any     # AI Provider Settings doc, injected in chat.py

	# ── Observability (accumulated across nodes) ─────────────────────
	start_time: float               # time.monotonic() at graph entry
	node_trace: list                # ordered list of visited node names
	timing: dict                    # {node_name: elapsed_ms}
	llm_provider: str
	llm_model: str
	input_tokens: int
	output_tokens: int
	retries: int                    # total SQL gen retries
	result_row_count: int
