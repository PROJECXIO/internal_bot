"""
Service: Schema Field Filter

Reduces the schema_context sent to the query LLM by selecting only fields and
child tables relevant to the user's question, using embedding cosine similarity.

Three-tier cache strategy for field embeddings:
  1. Redis (frappe.cache)          — fast, 24-hour TTL
  2. MariaDB (AI Schema Embedding Cache) — persistent across restarts
  3. LLM embeddings API            — computed on first miss, stored in both

Graceful fallback when embeddings are unavailable (e.g. Anthropic provider):
uses heuristic scoring based on field type importance and token overlap.
"""
from __future__ import annotations

import hashlib
import json
import math

import frappe

_REDIS_CACHE_TTL = 60 * 60 * 24   # 24 hours
_REDIS_KEY_PREFIX = "internal_bot:field_embeddings:v2:"  # bumped when child_fields added

# Maximum number of parent fields / child tables / per-child fields to keep after filtering
_TOP_K_FIELDS = 20
_TOP_K_CHILDREN = 2
_TOP_K_CHILD_FIELDS = 10  # max fields to keep per selected child table

# Field types always included regardless of embedding score
_PINNED_FIELD_TYPES = {"Date", "Datetime"}

# Substrings in fieldname that make a field "always include"
_PINNED_NAME_FRAGMENTS = frozenset({
    "docstatus", "name", "total", "amount", "rate", "grand", "net",
    "qty", "quantity", "date", "item_code", "customer", "supplier",
    "posting", "transaction",
})

# Child table name fragments that are almost always relevant to transactional queries
_PRIORITY_CHILD_FRAGMENTS = frozenset({"item", "detail", "line"})


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def filter_schema_for_query(
    question: str,
    query_embedding: list[float] | None,
    fields: list[dict],
    child_tables: list[dict],
    llm_client=None,
    doctype_name: str = "",
) -> tuple[list[dict], list[dict]]:
    """Return (filtered_fields, filtered_children) relevant to the question.

    Tries embedding-based filtering first; falls back to heuristic scoring
    if embeddings are not available (no LLM client or Anthropic provider).
    """
    if query_embedding and llm_client:
        field_embeddings = _get_or_compute_field_embeddings(
            fields, child_tables, llm_client, doctype_name=doctype_name
        )
        if field_embeddings:
            return _filter_by_embeddings(query_embedding, fields, child_tables, field_embeddings)

    # Fallback: heuristic
    from internal_bot.bot.services.text_normalizer import normalize_text, remove_stop_words, tokenize
    q_tokens = set(remove_stop_words(tokenize(normalize_text(question))))
    return _filter_by_heuristic(q_tokens, fields, child_tables)


def get_or_compute_field_embeddings_for_doctype(
    doctype_name: str,
    fields: list[dict],
    child_tables: list[dict],
    llm_client,
) -> dict:
    """Public wrapper used by intent_resolver to pre-warm the cache.

    Returns embedding dict: {"fields": {fieldname: vector}, "children": {child_name: vector}}
    or empty dict on failure.
    """
    return _get_or_compute_field_embeddings(fields, child_tables, llm_client, doctype_name=doctype_name)


# ──────────────────────────────────────────────────────────────────────────────
# Cache management
# ──────────────────────────────────────────────────────────────────────────────

def _make_cache_key(fields: list[dict], child_tables: list[dict], embedding_model: str) -> str:
    """SHA256 of (sorted fieldnames + child names + child fieldnames + embedding_model)."""
    all_names = sorted(f["fieldname"] for f in fields)
    all_names += sorted(c["name"] for c in child_tables)
    # Include child field names so cache invalidates when child schema changes
    for c in sorted(child_tables, key=lambda x: x["name"]):
        all_names += sorted(f["fieldname"] for f in (c.get("fields") or []))
    raw = ":".join(all_names) + ":" + embedding_model
    return hashlib.sha256(raw.encode()).hexdigest()


def _redis_key(cache_key: str) -> str:
    return _REDIS_KEY_PREFIX + cache_key


def _get_or_compute_field_embeddings(
    fields: list[dict],
    child_tables: list[dict],
    llm_client,
    doctype_name: str = "",
) -> dict:
    """Three-tier lookup: Redis → MariaDB → LLM API."""
    embedding_model = getattr(llm_client, "embedding_model", None) or ""
    provider = getattr(llm_client, "provider", "") or ""
    if not embedding_model:
        return {}

    cache_key = _make_cache_key(fields, child_tables, embedding_model)

    # ── Tier 1: Redis ──────────────────────────────────────────────────────────
    try:
        cached = frappe.cache().get_value(_redis_key(cache_key))
        if isinstance(cached, dict) and cached.get("fields") is not None:
            return cached
    except Exception:
        pass

    # ── Tier 2: MariaDB ───────────────────────────────────────────────────────
    try:
        db_row = frappe.db.get_value(
            "AI Schema Embedding Cache",
            {"cache_key": cache_key},
            ["embeddings_json"],
            as_dict=True,
        )
        if db_row and db_row.get("embeddings_json"):
            data = json.loads(db_row["embeddings_json"])
            if isinstance(data, dict) and data.get("fields") is not None:
                # Warm Redis
                _set_redis(cache_key, data)
                return data
    except Exception:
        pass

    # ── Tier 3: Compute via LLM API ───────────────────────────────────────────
    try:
        data = _compute_embeddings(fields, child_tables, llm_client)
        if not data:
            return {}

        # Save to Redis
        _set_redis(cache_key, data)

        # Save to MariaDB
        _upsert_db(
            cache_key=cache_key,
            doctype_name=doctype_name,
            fingerprint=cache_key[:16],
            provider=provider,
            embedding_model=embedding_model,
            data=data,
        )
        return data
    except Exception as exc:
        frappe.log_error(str(exc), "SchemaFieldFilter: embedding computation failed")
        return {}


def _compute_embeddings(
    fields: list[dict],
    child_tables: list[dict],
    llm_client,
) -> dict | None:
    """Call the embeddings API and return structured dict.

    Embeds parent fields, child table summaries, AND individual fields within
    each child table — all in a single batched API call.
    """
    # Parent field texts
    field_texts = [f"{f.get('label', f['fieldname'])} ({f['fieldname']})" for f in fields]

    # Child table summary texts (one per child — for selecting which child to include)
    child_texts = [
        "{name}: {labels}".format(
            name=c["name"],
            labels=", ".join(
                f2.get("label", f2["fieldname"])
                for f2 in c.get("fields", [])[:6]
            ),
        )
        for c in child_tables
    ]

    # Per-child field texts (for filtering fields within each selected child table)
    # Track slice boundaries: {child_name: (start_idx, end_idx)} in the flat list
    child_field_slices: dict[str, tuple[int, int]] = {}
    child_field_lists: dict[str, list[dict]] = {}
    child_field_texts_flat: list[str] = []
    for c in child_tables:
        c_fields = c.get("fields") or []
        if c_fields:
            start = len(child_field_texts_flat)
            child_field_texts_flat.extend(
                f"{f.get('label', f['fieldname'])} ({f['fieldname']})" for f in c_fields
            )
            child_field_slices[c["name"]] = (start, len(child_field_texts_flat))
            child_field_lists[c["name"]] = c_fields

    all_texts = field_texts + child_texts + child_field_texts_flat
    if not all_texts:
        return None

    vectors = llm_client.create_embeddings(all_texts)
    if not vectors or len(vectors) != len(all_texts):
        return None

    n_fields = len(field_texts)
    n_children = len(child_texts)
    field_vectors = vectors[:n_fields]
    child_vectors = vectors[n_fields: n_fields + n_children]
    child_field_vectors_flat = vectors[n_fields + n_children:]

    # Reconstruct per-child field embedding dicts
    child_fields_result: dict[str, dict[str, list]] = {}
    for c_name, (start, end) in child_field_slices.items():
        c_fields = child_field_lists[c_name]
        c_vecs = child_field_vectors_flat[start:end]
        child_fields_result[c_name] = {
            f["fieldname"]: v for f, v in zip(c_fields, c_vecs)
        }

    return {
        "fields": {f["fieldname"]: v for f, v in zip(fields, field_vectors)},
        "children": {c["name"]: v for c, v in zip(child_tables, child_vectors)},
        "child_fields": child_fields_result,
    }


def _set_redis(cache_key: str, data: dict) -> None:
    try:
        frappe.cache().set_value(_redis_key(cache_key), data, expires_in_sec=_REDIS_CACHE_TTL)
    except Exception:
        pass


def _upsert_db(
    cache_key: str,
    doctype_name: str,
    fingerprint: str,
    provider: str,
    embedding_model: str,
    data: dict,
) -> None:
    try:
        embeddings_json = json.dumps(data)
        existing = frappe.db.get_value(
            "AI Schema Embedding Cache",
            {"cache_key": cache_key},
            "name",
        )
        if existing:
            frappe.db.set_value(
                "AI Schema Embedding Cache",
                existing,
                {
                    "embeddings_json": embeddings_json,
                    "fingerprint": fingerprint,
                    "provider": provider,
                    "embedding_model": embedding_model,
                    "doctype_name": doctype_name or "",
                },
            )
        else:
            doc = frappe.get_doc({
                "doctype": "AI Schema Embedding Cache",
                "cache_key": cache_key,
                "doctype_name": doctype_name or "",
                "fingerprint": fingerprint,
                "provider": provider,
                "embedding_model": embedding_model,
                "embedding_type": "fields",
                "embeddings_json": embeddings_json,
            })
            doc.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception as exc:
        frappe.log_error(str(exc), "SchemaFieldFilter: DB upsert failed")


# ──────────────────────────────────────────────────────────────────────────────
# Filtering logic
# ──────────────────────────────────────────────────────────────────────────────

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)


def _is_pinned_field(field: dict) -> bool:
    """Return True if this field should always be included."""
    if field.get("reqd"):
        return True
    if field["fieldtype"] in _PINNED_FIELD_TYPES:
        return True
    fn = (field["fieldname"] or "").lower()
    return any(frag in fn for frag in _PINNED_NAME_FRAGMENTS)


def _filter_by_embeddings(
    query_embedding: list[float],
    fields: list[dict],
    child_tables: list[dict],
    field_embeddings: dict,
) -> tuple[list[dict], list[dict]]:
    field_vecs = field_embeddings.get("fields") or {}
    child_vecs = field_embeddings.get("children") or {}
    child_field_vecs_all = field_embeddings.get("child_fields") or {}

    # ── Parent fields ──────────────────────────────────────────────────────────
    pinned = [f for f in fields if _is_pinned_field(f)]
    pinned_names = {f["fieldname"] for f in pinned}
    scoreable = [f for f in fields if f["fieldname"] not in pinned_names]

    scored = []
    for f in scoreable:
        vec = field_vecs.get(f["fieldname"])
        score = _cosine_similarity(query_embedding, vec) if vec else 0.0
        scored.append((score, f))
    scored.sort(key=lambda x: x[0], reverse=True)

    budget = max(0, _TOP_K_FIELDS - len(pinned))
    selected_fields = pinned + [f for _, f in scored[:budget]]

    # ── Child tables ───────────────────────────────────────────────────────────
    if not child_tables:
        return selected_fields, []

    child_scored = []
    for c in child_tables:
        vec = child_vecs.get(c["name"])
        score = _cosine_similarity(query_embedding, vec) if vec else 0.0
        # Boost child tables whose names contain priority fragments
        name_lower = c["name"].lower()
        if any(frag in name_lower for frag in _PRIORITY_CHILD_FRAGMENTS):
            score += 0.1
        child_scored.append((score, c))
    child_scored.sort(key=lambda x: x[0], reverse=True)
    top_children = [c for _, c in child_scored[:_TOP_K_CHILDREN]]

    # ── Per-child field filtering ──────────────────────────────────────────────
    # For each selected child table, filter its fields by cosine similarity too.
    selected_children = []
    for c in top_children:
        c_field_vecs = child_field_vecs_all.get(c["name"]) or {}
        c_fields = c.get("fields") or []
        if c_field_vecs and c_fields:
            c_pinned = [f for f in c_fields if _is_pinned_field(f)]
            c_pinned_names = {f["fieldname"] for f in c_pinned}
            c_scoreable = [f for f in c_fields if f["fieldname"] not in c_pinned_names]
            c_scored = []
            for f in c_scoreable:
                vec = c_field_vecs.get(f["fieldname"])
                score = _cosine_similarity(query_embedding, vec) if vec else 0.0
                c_scored.append((score, f))
            c_scored.sort(key=lambda x: x[0], reverse=True)
            c_budget = max(0, _TOP_K_CHILD_FIELDS - len(c_pinned))
            filtered_c_fields = c_pinned + [f for _, f in c_scored[:c_budget]]
            selected_children.append({**c, "fields": filtered_c_fields})
        else:
            selected_children.append(c)

    return selected_fields, selected_children


def _filter_by_heuristic(
    question_tokens: set[str],
    fields: list[dict],
    child_tables: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Fallback when embeddings are unavailable."""
    # ── Parent fields ──────────────────────────────────────────────────────────
    pinned = [f for f in fields if _is_pinned_field(f)]
    pinned_names = {f["fieldname"] for f in pinned}
    scoreable = [f for f in fields if f["fieldname"] not in pinned_names]

    scored = []
    for f in scoreable:
        score = 0
        fn_tokens = set((f["fieldname"] or "").lower().replace("_", " ").split())
        lbl_tokens = set((f.get("label") or "").lower().split())
        score += len(fn_tokens & question_tokens)
        score += len(lbl_tokens & question_tokens)
        # Bonus for Currency/Float — likely relevant to analytics
        if f["fieldtype"] in {"Currency", "Float", "Int"}:
            score += 0.5
        scored.append((score, f))
    scored.sort(key=lambda x: x[0], reverse=True)

    budget = max(0, _TOP_K_FIELDS - len(pinned))
    selected_fields = pinned + [f for _, f in scored[:budget]]

    # ── Child tables ───────────────────────────────────────────────────────────
    if not child_tables:
        return selected_fields, []

    child_scored = []
    for c in child_tables:
        name_tokens = set(c["name"].lower().replace(" ", "_").split("_"))
        score = len(name_tokens & question_tokens)
        if any(frag in c["name"].lower() for frag in _PRIORITY_CHILD_FRAGMENTS):
            score += 1
        child_scored.append((score, c))
    child_scored.sort(key=lambda x: x[0], reverse=True)
    top_children = [c for _, c in child_scored[:_TOP_K_CHILDREN]]

    # ── Per-child field filtering (heuristic) ──────────────────────────────────
    selected_children = []
    for c in top_children:
        c_fields = c.get("fields") or []
        if c_fields:
            c_pinned = [f for f in c_fields if _is_pinned_field(f)]
            c_pinned_names = {f["fieldname"] for f in c_pinned}
            c_scoreable = [f for f in c_fields if f["fieldname"] not in c_pinned_names]
            c_scored = []
            for f in c_scoreable:
                score = 0
                fn_tokens = set((f["fieldname"] or "").lower().replace("_", " ").split())
                lbl_tokens = set((f.get("label") or "").lower().split())
                score += len(fn_tokens & question_tokens)
                score += len(lbl_tokens & question_tokens)
                if f["fieldtype"] in {"Currency", "Float", "Int"}:
                    score += 0.5
                c_scored.append((score, f))
            c_scored.sort(key=lambda x: x[0], reverse=True)
            c_budget = max(0, _TOP_K_CHILD_FIELDS - len(c_pinned))
            filtered_c_fields = c_pinned + [f for _, f in c_scored[:c_budget]]
            selected_children.append({**c, "fields": filtered_c_fields})
        else:
            selected_children.append(c)

    return selected_fields, selected_children
