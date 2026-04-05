"""
Build and cache retrieval documents for DocType schema discovery.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import md5
import json

import frappe

from internal_bot.bot.services import schema as schema_svc
from internal_bot.bot.services.doctype_aliases import get_aliases_for_doctype
from internal_bot.bot.services.text_normalizer import normalize_text, remove_stop_words, tokenize

_CORPUS_CACHE_KEY = "internal_bot:schema_corpus:v1"
_EMBEDDINGS_CACHE_KEY = "internal_bot:schema_corpus_embeddings:v1"
_CORPUS_TTL = 60 * 60


@dataclass
class CorpusDocument:
    doctype_name: str
    module: str
    description: str
    normalized_text: str
    aliases: list[str]
    normalized_aliases: list[str]
    field_labels: list[str]
    link_targets: list[str]
    token_set: set[str]
    embedding: list[float] | None = None


def compute_schema_fingerprint() -> str:
    rows = frappe.db.sql(
        """
        SELECT dt.name, dt.modified, COUNT(df.name) AS field_count
        FROM `tabDocType` dt
        LEFT JOIN `tabDocField` df
            ON df.parent = dt.name
            AND df.parenttype = 'DocType'
            AND df.parentfield = 'fields'
        WHERE dt.issingle = 0
          AND dt.istable = 0
          AND dt.hide_toolbar = 0
        GROUP BY dt.name, dt.modified
        ORDER BY dt.name
        """,
        as_dict=True,
    )
    digest_input = [
        (row["name"], str(row["modified"]), int(row["field_count"] or 0))
        for row in rows
    ]
    return md5(json.dumps(digest_input, sort_keys=True).encode("utf-8")).hexdigest()


def build_corpus_document(
    doctype_name: str,
    meta_fields: list[dict],
    meta_links: list[dict],
    module: str,
    description: str,
) -> CorpusDocument:
    aliases = get_aliases_for_doctype(doctype_name)
    normalized_aliases = []
    for alias in aliases:
        normalized_alias = normalize_text(alias)
        if normalized_alias:
            normalized_aliases.append(normalized_alias)

    field_labels = [field.get("label") or field.get("fieldname") or "" for field in meta_fields]
    link_targets = [link.get("links_to") or "" for link in meta_links]
    searchable_text = " ".join(
        part
        for part in [doctype_name, module, description, *field_labels, *link_targets, *aliases]
        if part
    )
    normalized_text = normalize_text(searchable_text)
    token_set = set(remove_stop_words(tokenize(normalized_text)))

    return CorpusDocument(
        doctype_name=doctype_name,
        module=module or "",
        description=description or "",
        normalized_text=normalized_text,
        aliases=sorted(set(aliases)),
        normalized_aliases=sorted(set(normalized_aliases)),
        field_labels=field_labels,
        link_targets=link_targets,
        token_set=token_set,
        embedding=None,
    )


def get_corpus(blocked: set[str]) -> list[CorpusDocument]:
    corpus = _get_full_corpus()
    blocked_set = set(blocked or set())
    return [doc for doc in corpus if doc.doctype_name not in blocked_set]


def compute_and_cache_embeddings(
    corpus: list[CorpusDocument],
    llm_client,
) -> list[CorpusDocument]:
    if not corpus or not llm_client:
        return corpus

    embedding_model = getattr(llm_client, "embedding_model", None)
    provider = getattr(llm_client, "provider", "") or ""
    if not embedding_model:
        return corpus

    fingerprint = compute_schema_fingerprint()
    docnames = [doc.doctype_name for doc in corpus]
    cached = frappe.cache().get_value(_EMBEDDINGS_CACHE_KEY)
    if isinstance(cached, dict):
        if (
            cached.get("fingerprint") == fingerprint
            and cached.get("provider") == provider
            and cached.get("embedding_model") == embedding_model
            and cached.get("docnames") == docnames
        ):
            embeddings = cached.get("embeddings") or []
            if len(embeddings) == len(corpus):
                return [replace(doc, embedding=embedding) for doc, embedding in zip(corpus, embeddings)]

    embeddings = llm_client.create_embeddings([doc.normalized_text for doc in corpus])
    if not embeddings or len(embeddings) != len(corpus):
        return corpus

    frappe.cache().set_value(
        _EMBEDDINGS_CACHE_KEY,
        {
            "fingerprint": fingerprint,
            "provider": provider,
            "embedding_model": embedding_model,
            "docnames": docnames,
            "embeddings": embeddings,
        },
        expires_in_sec=_CORPUS_TTL,
    )
    return [replace(doc, embedding=embedding) for doc, embedding in zip(corpus, embeddings)]


def invalidate_corpus_cache():
    cache = frappe.cache()
    cache.delete_value(_CORPUS_CACHE_KEY)
    cache.delete_value(_EMBEDDINGS_CACHE_KEY)


def _get_full_corpus() -> list[CorpusDocument]:
    fingerprint = compute_schema_fingerprint()
    cached = frappe.cache().get_value(_CORPUS_CACHE_KEY)
    if isinstance(cached, dict) and cached.get("fingerprint") == fingerprint:
        documents = cached.get("documents") or []
        return [_deserialize_doc(doc) for doc in documents]

    rows = frappe.db.sql(
        """
        SELECT name, module, description
        FROM `tabDocType`
        WHERE issingle = 0
          AND istable = 0
          AND hide_toolbar = 0
        ORDER BY name
        """,
        as_dict=True,
    )

    documents = []
    for row in rows:
        doctype_name = row["name"]
        fields = schema_svc.get_doctype_fields(doctype_name)
        links = schema_svc.get_doctype_links(doctype_name)
        documents.append(
            build_corpus_document(
                doctype_name=doctype_name,
                meta_fields=fields,
                meta_links=links,
                module=row.get("module") or "",
                description=row.get("description") or "",
            )
        )

    frappe.cache().set_value(
        _CORPUS_CACHE_KEY,
        {
            "fingerprint": fingerprint,
            "documents": [_serialize_doc(doc) for doc in documents],
        },
        expires_in_sec=_CORPUS_TTL,
    )
    return documents


def _serialize_doc(doc: CorpusDocument) -> dict:
    payload = asdict(doc)
    payload["token_set"] = sorted(doc.token_set)
    return payload


def _deserialize_doc(payload: dict) -> CorpusDocument:
    return CorpusDocument(
        doctype_name=payload["doctype_name"],
        module=payload.get("module") or "",
        description=payload.get("description") or "",
        normalized_text=payload.get("normalized_text") or "",
        aliases=list(payload.get("aliases") or []),
        normalized_aliases=list(payload.get("normalized_aliases") or []),
        field_labels=list(payload.get("field_labels") or []),
        link_targets=list(payload.get("link_targets") or []),
        token_set=set(payload.get("token_set") or []),
        embedding=payload.get("embedding"),
    )
