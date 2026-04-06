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
    session_name: str       # AI Chat Session document name
    debug: bool             # include debug fields in response?
    max_rows: int           # from AI Provider Settings.max_result_rows
    current_date: str       # YYYY-MM-DD for this request
    current_day_name: str   # Monday, Tuesday, ...
    current_year: int       # numeric year for this request

    # ── Node 1: Intent Parser ────────────────────────────────────────
    normalized_question: str
    intent: str             # "greeting" | "query" | "clarification_needed" | "blocked"
    intent_reason: str      # free-text reason (shown for blocked/clarification)
    clarification_options: list  # options list for clarification_needed

    # ── Node 2: Memory Loader ────────────────────────────────────────
    chat_history: list      # [{"role": "user"|"assistant", "content": "..."}]
    memory_summary: str     # rolling LLM summary of older messages
    last_user_question: str
    last_non_follow_up_user_question: str
    last_assistant_response: dict
    last_assistant_context_text: str
    last_discovered_doctypes: list
    follow_up_to_previous_result: bool

    # ── Node 3: Schema Discovery ─────────────────────────────────────
    discovered_doctypes: list   # ["Sales Invoice", "Customer", ...]
    schema_context: str         # Markdown-formatted schema for LLM prompt
    schema_confidence: float
    schema_decision: str
    schema_candidates: list

    # ── Node: Clarification Planner ──────────────────────────────────
    ready_to_query: bool         # True = proceed to query_planner
    clarification_question: str  # question to show the user when not ready

    # ── Node: Query Planner (replaces sql_generator + validator + executor) ──
    generated_intent: Optional[dict]    # raw JSON intent from LLM (for audit logging)
    validated_intent: Optional[dict]    # intent after permission re-check
    compiled_sql: Optional[str]         # analytics mode only; None for list mode
    query_result_rows: list             # list of row dicts
    query_execution_error: str
    query_is_valid: bool
    query_invalid_reason: str
    query_generation_attempts: int      # 0–3 (retry counter)

    # ── Node 7: Result Formatter ─────────────────────────────────────
    formatted_response: dict    # final API response
    response_type: str          # "metric_card" | "bar_chart" | "pie_chart" | "donut_chart" | "line_chart" | "area_chart" | "stacked_bar_chart" | "table" | "empty"
    visualization: Optional[dict]
    summary: str
    visualization_preference: str  # "auto" | "card" | "bar" | "pie" | "donut" | "line" | "area" | "stacked_bar" | "text"
    answer_prefix: str             # friendly intro sentence, e.g. "Here's what I found:"
    answer_markdown: str           # markdown answer or brief shown in the frontend

    # ── Per-request injected objects (must be in schema for LangGraph to preserve) ──
    _llm_client: Any   # LLMClient instance, injected in chat.py
    _settings: Any     # AI Provider Settings doc, injected in chat.py
    _job_id: str       # UUID4 string, injected by ask_async(); empty in sync path
    _emit_progress: bool  # True only in async path; absent/False in sync ask()

    # ── Observability (accumulated across nodes) ─────────────────────
    start_time: float               # time.monotonic() at graph entry
    node_trace: list                # ordered list of visited node names
    timing: dict                    # {node_name: elapsed_ms}
    llm_provider: str
    llm_model: str
    input_tokens: int
    output_tokens: int
    retries: int                    # total query planning retries
    result_row_count: int
