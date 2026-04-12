# Phase 0 Baseline

Phase 0 records the bot's current behavior before any refactor. The goal is to
document the execution path, define representative query fixtures, and provide a
repeatable runner that captures structured output for later comparison.

This phase is intentionally observational. It does not change prompts, graph
routing, permission checks, schema retrieval, SQL/query compilation, formatting,
or frontend behavior.

## Current Execution Flow

### `internal_bot.api.chat.ask`

`ask` is the synchronous whitelisted API entry point. It validates that the
request is authenticated, rejects empty messages, creates or reuses an
`AI Chat Session`, loads `AI Provider Settings`, builds the LLM client, creates
the initial graph state, invokes `get_graph().invoke(...)`, and returns
`formatted_response` with the session id attached.

Important entry-state values include the raw message, session name, current date
context, user profile language, max row limit, token counters, retry counters,
timing storage, and injected `_llm_client` / `_settings` objects.

### `memory_loader`

`memory_loader` reads recent `AI Chat Message` records and the session memory
summary. It populates conversation context used by later nodes, including the
last user question, last non-follow-up user question, last assistant structured
response, last result context text, and last discovered DocTypes.

This node is the graph entry point so intent classification can see recent
conversation context before deciding whether a message is a standalone question,
a clarification answer, or a follow-up.

### `intent_classifier`

`intent_classifier` classifies the request as `greeting`, `query`,
`clarification_needed`, or `blocked`. It also writes the normalized question,
response language, follow-up flag, intent reason, and clarification options.

It contains a local sensitive-keyword guard for restricted HR/payroll-style
requests, plus LLM-based classification for the general case. It can expand
short follow-up questions by using the last assistant response and prior
question context.

### `schema_discovery`

`schema_discovery` finds relevant DocTypes for query intents. It normalizes and
tokenizes the question, loads the schema corpus while excluding blocked
DocTypes, optionally computes embeddings, ranks candidates with the hybrid
scorer, and classifies the result as `clear_winner`, `ambiguous`,
`low_confidence`, or `no_match`.

For selected DocTypes it builds permission-filtered schema context, including
fields, links, and child tables. For a clear winner with embeddings available,
it may further filter fields and child tables to keep the schema context compact.

### `intent_resolver` / `clarification_planner`

When schema discovery is ambiguous or low confidence, `intent_resolver` tries to
choose a clear DocType before asking the user. If it resolves the ambiguity, the
graph proceeds toward query planning. If it cannot, the graph routes to
`clarification_planner`.

`clarification_planner` asks for missing information when the bot cannot safely
query yet, including ambiguous DocType choices or vague period placeholders. It
also has fail-open behavior for some cases: if clarification parsing fails or a
query is considered ready enough, the graph can proceed to query planning.

### `presentation_planner`

`presentation_planner` runs before query generation. It asks the LLM for an
advisory presentation plan: preferred visualization, query shape, dimensions,
metrics, limits, and reasoning. This plan is a hint for downstream query and
visualization nodes, not the final rendering decision.

The current local graph also includes `query_architect` between
`presentation_planner` and `query_planner`. That node enriches join planning for
multi-DocType and child-table requests before query generation.

### `query_planner`

`query_planner` generates query intent JSON using the current question, schema
context, memory context, presentation plan, join plan, and current date context.
It validates the requested primary DocType against permissions, rejects child
tables as primary DocTypes, executes the query intent through the current query
executor, stores the compiled SQL when available, and records result rows.

On retryable errors it increments `query_generation_attempts` and loops back
through itself until the retry limit is reached. Permission errors force
give-up immediately.

### `visualization_planner`

`visualization_planner` runs after successful query execution. It uses the result
shape, advisory presentation plan, and question to choose a final visualization
preference and answer prefix. If the LLM call fails, it falls back to `auto`.

### `answer_composer`

`answer_composer` writes the markdown answer after query execution and
visualization planning. It builds a compact payload containing the question,
response language, result shape, selected visualization, result sample, and
follow-up context. For empty rows it produces an empty-result answer without
requiring the LLM.

On success it finalizes `formatted_response` through the current structured
formatter, so successful paths do not route through `result_formatter`.

### `result_formatter`

`result_formatter` handles non-success and give-up paths. It formats greetings,
blocked requests, clarification requests, no-schema clarification, and query
errors into the API response contract. When `debug` is true, formatter output
includes structured debug fields such as schema candidates, generated intent,
compiled SQL, retries, timing, node trace, and visualization preference.

## Key Graph State Fields

- `raw_message`: Original stripped user message.
- `normalized_question`: Classifier-produced normalized question. Follow-up
  requests may be rewritten with prior context.
- `intent`: Request class: `greeting`, `query`, `clarification_needed`, or
  `blocked`.
- `follow_up_to_previous_result`: Whether the classifier treated the message as
  contextual to prior conversation/results.
- `discovered_doctypes`: DocTypes selected by schema discovery or resolution.
- `schema_context`: Markdown schema context supplied to query planning.
- `schema_decision`: Schema confidence decision, such as `clear_winner`,
  `ambiguous`, `low_confidence`, or `no_match`.
- `presentation_plan`: Advisory result-shape and visualization plan produced
  before query generation.
- `generated_intent`: Raw query intent JSON generated by the LLM.
- `compiled_sql`: SQL generated by the current executor for analytics mode;
  list-mode queries may leave this empty.
- `query_result_rows`: Raw query result row dictionaries.
- `visualization_preference`: Final visualization preference selected after
  query execution.
- `answer_markdown`: Markdown answer text composed for the frontend.
- `formatted_response`: Final API response payload.

## Known Risk Areas

- Row-scope handling in query compilation: list-vs-analytics behavior, child
  table joins, status/docstatus filters, and user permission filters must remain
  consistent when query compilation is refactored.
- Clarification fail-open behavior: ambiguous or under-specified requests can
  proceed to query planning instead of asking the user, which may hide routing
  errors.
- Aggressive follow-up rewriting: short contextual questions can be expanded
  using previous result data, which is useful but can point the next query at
  the wrong entity, DocType, or row.
- Embedding cost in schema discovery: schema and query embeddings can add cost
  and latency, especially when cache state is cold.
- Arabic support gaps: Arabic intent classification, aliases, date phrasing,
  clarification copy, and answer composition may not behave consistently across
  all query types.

## Phase 0 Deliverables

- This architecture and scope document.
- A 25-query baseline fixture covering greetings, blocked requests,
  clarification, list queries, aggregates, breakdowns, child-table queries,
  Arabic queries, follow-ups, edge/no-result cases, and business-like requests.
- A 10-query golden fixture selected from the baseline for future regression
  checks.
- A baseline runner that uses the current graph pipeline and writes structured
  per-query and summary reports.
- Machine-readable JSON output suitable for comparison in later phases.

## What Phase 0 Explicitly Does Not Change

- No production code under `internal_bot/api` or `internal_bot/bot`.
- No graph topology changes.
- No prompt changes.
- No permission, schema, routing, query compilation, SQL execution, or result
  formatting changes.
- No hook changes.
- No external dependencies.
- No attempt to fix known behavior gaps. Those are intentionally preserved for
  later regression comparison.
