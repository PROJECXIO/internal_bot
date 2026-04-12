"""
Hybrid lexical and semantic retrieval for schema discovery.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re

from internal_bot.bot.services import permission_service
from internal_bot.bot.services.doctype_aliases import get_alias_index
from internal_bot.bot.services.schema_corpus import CorpusDocument
from internal_bot.bot.services.text_normalizer import (
    make_ngrams,
    normalize_phrase_for_match,
    normalize_text,
    remove_stop_words,
    tokenize,
)

CLEAR_WINNER_THRESHOLD = 0.45
CLEAR_WINNER_GAP = 0.15
AMBIGUOUS_THRESHOLD = 0.30
MINIMUM_THRESHOLD = 0.10
_LEXICAL_ALPHA = 0.6
_CONTEXT_PREVIOUS_DOCTYPE_BOOST = 0.12
_CONTEXT_FOLLOW_UP_BOOST = 0.35
_IDENTIFIER_TOKEN_RE = re.compile(r"(?:[a-z]+[-_]?\d+|\d{4})", re.IGNORECASE)
_COMPANY_SCOPE_DOWNRANK_FACTOR = 0.25
_MASTER_ANALYTICS_DOWNRANK_FACTOR = 0.25
_SALES_ANALYTICS_BOOST = 0.40
_ANALYTIC_MASTER_DOCTYPES = {"Customer", "Item"}
_COMPANY_SCOPE_TERMS = {
    "company",
    "companies",
    "business",
    "organization",
    "شركة",
    "شركه",
}
_SALES_TERMS = {
    "sale",
    "sales",
    "selling",
    "sold",
    "revenue",
    "invoice",
    "invoices",
    "order",
    "orders",
    "movement",
    "status",
    "performance",
    "مبيعات",   # sales (plural noun)
    "بيع",      # selling / sale (base form)
    "مبيعا",    # sold (passive participle + tanwin alef, e.g. "اصناف مبيعا")
    "مبيع",     # sold (passive participle base)
    "مباع",     # sold (alternative passive form)
    "مبيعه",    # sold (informal feminine)
    "فواتير",
    "فاتورة",
    "حركة",
    "حاله",
    "حالة",
    "وضع",
}
_CUSTOMER_TERMS = {
    "customer",
    "customers",
    "client",
    "clients",
    "عميل",
    "عملاء",
}
_ITEM_TERMS = {
    "item",
    "items",
    "sku",
    "product",
    "products",
    "صنف",
    "اصناف",
}
_RANKING_TERMS = {
    "top",
    "best",
    "highest",
    "strongest",
    "largest",
    "most",
    "first",
    "افضل",
    "اعلي",
    "اعلى",
    "اكبر",
    "اقوي",
    "اقوى",
}
_COMPANY_METADATA_TERMS = {
    "abbr",
    "abbreviation",
    "currency",
    "country",
    "establishment",
    "incorporation",
    "commencement",
    "target",
    "default",
    "address",
    "contact",
    "tax",
    "warehouse",
    "حساب",
    "عملة",
    "دولة",
    "هدف",
    "افتراضي",
}


@dataclass
class ScoredCandidate:
    doctype_name: str
    lexical_score: float
    semantic_score: float
    final_score: float
    match_reason: str


def score_lexical(
    query_tokens: list[str],
    query_bigrams: list[str],
    doc: CorpusDocument,
    normalized_query: str = "",
    exact_alias_doctype: str | None = None,
) -> tuple[float, str]:
    query_phrases = set(query_tokens) | set(query_bigrams)
    if normalized_query:
        query_phrases.add(normalized_query)

    if exact_alias_doctype and exact_alias_doctype == doc.doctype_name:
        return 1.0, "exact alias match"

    if any(alias in query_phrases for alias in doc.normalized_aliases):
        return 1.0, "exact alias phrase match"

    query_token_set = set(query_tokens)
    if query_token_set:
        for alias in doc.normalized_aliases:
            alias_tokens = set(tokenize(alias))
            if alias_tokens and query_token_set.issubset(alias_tokens):
                return 0.85, "alias token containment"

    normalized_name = normalize_text(doc.doctype_name)
    if normalized_name and normalized_query and normalized_name in normalized_query:
        return 0.95, "exact DocType name match"

    union = query_token_set | doc.token_set
    intersection = query_token_set & doc.token_set
    jaccard = (len(intersection) / len(union)) if union else 0.0

    phrase_overlap = (
        sum(1 for phrase in query_bigrams if phrase in doc.normalized_text) / len(query_bigrams)
        if query_bigrams
        else 0.0
    )
    lexical_score = max(jaccard * 0.7 + phrase_overlap * 0.3, 0.0)
    reason_parts = []
    if intersection:
        reason_parts.append(f"token overlap {sorted(intersection)}")
    if phrase_overlap:
        reason_parts.append("phrase overlap")
    return lexical_score, ", ".join(reason_parts) or "no lexical overlap"


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0

    dot_product = sum(left * right for left, right in zip(a, b))
    norm_a = math.sqrt(sum(value * value for value in a))
    norm_b = math.sqrt(sum(value * value for value in b))
    if not norm_a or not norm_b:
        return 0.0
    return dot_product / (norm_a * norm_b)


def _query_term_set(normalized_query: str, match_query: str, query_tokens: list[str]) -> set[str]:
    terms = set(query_tokens)
    for source in (normalized_query, match_query):
        terms.update(tokenize(source))
    return {term for term in terms if term}


def _looks_like_company_scope_business_query(query_terms: set[str]) -> bool:
    if not query_terms.intersection(_COMPANY_SCOPE_TERMS):
        return False
    if query_terms.intersection(_COMPANY_METADATA_TERMS):
        return False
    return bool(
        query_terms.intersection(_SALES_TERMS)
        or query_terms.intersection(_ITEM_TERMS)
        or (
            query_terms.intersection(_CUSTOMER_TERMS)
            and query_terms.intersection(_RANKING_TERMS)
        )
    )


def _looks_like_sales_invoice_analytics_query(query_terms: set[str]) -> bool:
    if query_terms.intersection(_COMPANY_METADATA_TERMS):
        return False
    if query_terms.intersection(_SALES_TERMS):
        return True
    return bool(
        query_terms.intersection(_COMPANY_SCOPE_TERMS)
        and query_terms.intersection(_CUSTOMER_TERMS)
        and query_terms.intersection(_RANKING_TERMS)
    )


def _apply_domain_score_adjustments(
    doctype_name: str,
    final_score: float,
    match_reason: str,
    query_terms: set[str],
) -> tuple[float, str]:
    if doctype_name == "Company" and _looks_like_company_scope_business_query(query_terms):
        return (
            final_score * _COMPANY_SCOPE_DOWNRANK_FACTOR,
            f"{match_reason}, company scope downrank",
        )

    if (
        doctype_name in _ANALYTIC_MASTER_DOCTYPES
        and _looks_like_sales_invoice_analytics_query(query_terms)
        and (
            query_terms.intersection(_SALES_TERMS)
            or query_terms.intersection(_RANKING_TERMS)
        )
    ):
        return (
            final_score * _MASTER_ANALYTICS_DOWNRANK_FACTOR,
            f"{match_reason}, sales analytics master downrank",
        )

    if doctype_name == "Sales Invoice" and _looks_like_sales_invoice_analytics_query(query_terms):
        return final_score + _SALES_ANALYTICS_BOOST, f"{match_reason}, sales analytics boost"

    return final_score, match_reason


def rank_candidates(
    query: str,
    corpus: list[CorpusDocument],
    user: str,
    blocked: set[str],
    query_embedding: list[float] | None = None,
    preferred_doctypes: list[str] | None = None,
    follow_up_to_previous_result: bool = False,
) -> list[ScoredCandidate]:
    normalized_query = normalize_text(query)
    match_query = normalize_phrase_for_match(normalized_query)
    query_tokens = remove_stop_words(tokenize(match_query or normalized_query))
    query_bigrams = make_ngrams(query_tokens, n=2)
    if not query_tokens and not normalized_query:
        return []
    query_terms = _query_term_set(normalized_query, match_query, query_tokens)

    alias_index = get_alias_index()
    candidate_phrases = [normalized_query, match_query, *query_bigrams, *query_tokens]
    exact_alias_doctype = next((alias_index.get(phrase) for phrase in candidate_phrases if alias_index.get(phrase)), None)
    allow_context_priority = _should_apply_context_priority(query_tokens, follow_up_to_previous_result)

    scored = []
    blocked_set = set(blocked or set())
    preferred_set = set(preferred_doctypes or [])
    for doc in corpus:
        if doc.doctype_name in blocked_set:
            continue
        lexical_score, match_reason = score_lexical(
            query_tokens=query_tokens,
            query_bigrams=query_bigrams,
            doc=doc,
            normalized_query=match_query or normalized_query,
            exact_alias_doctype=exact_alias_doctype,
        )
        semantic_score = 0.0
        if query_embedding and doc.embedding:
            semantic_score = max(0.0, cosine_similarity(query_embedding, doc.embedding))
            final_score = (_LEXICAL_ALPHA * lexical_score) + ((1 - _LEXICAL_ALPHA) * semantic_score)
        else:
            final_score = lexical_score

        if allow_context_priority and doc.doctype_name in preferred_set:
            final_score += _CONTEXT_PREVIOUS_DOCTYPE_BOOST
            if follow_up_to_previous_result:
                final_score += _CONTEXT_FOLLOW_UP_BOOST
                match_reason = f"{match_reason}, conversation follow-up priority"
            else:
                match_reason = f"{match_reason}, conversation context priority"

        final_score, match_reason = _apply_domain_score_adjustments(
            doc.doctype_name,
            final_score,
            match_reason,
            query_terms,
        )

        if final_score <= 0:
            continue

        scored.append(
            ScoredCandidate(
                doctype_name=doc.doctype_name,
                lexical_score=round(lexical_score, 4),
                semantic_score=round(semantic_score, 4),
                final_score=round(final_score, 4),
                match_reason=match_reason,
            )
        )

    scored.sort(key=lambda candidate: candidate.final_score, reverse=True)

    permitted = set(
        permission_service.filter_permitted_doctypes(
            [candidate.doctype_name for candidate in scored],
            user,
        )
    )
    return [candidate for candidate in scored if candidate.doctype_name in permitted]


def _should_apply_context_priority(
    query_tokens: list[str],
    follow_up_to_previous_result: bool,
) -> bool:
    compact_tokens = [token for token in query_tokens if token]
    if not compact_tokens:
        return follow_up_to_previous_result
    max_tokens = 10 if follow_up_to_previous_result else 5
    if len(compact_tokens) > max_tokens:
        return False
    return not any(_IDENTIFIER_TOKEN_RE.search(token) for token in compact_tokens)


def classify_confidence(candidates: list[ScoredCandidate]) -> tuple[str, list[ScoredCandidate]]:
    if not candidates:
        return "no_match", []

    above_minimum = [candidate for candidate in candidates if candidate.final_score >= MINIMUM_THRESHOLD]
    if not above_minimum:
        return "no_match", candidates[:5]

    top = above_minimum[0]
    if top.match_reason == "exact alias match":
        return "clear_winner", [top]

    second_score = above_minimum[1].final_score if len(above_minimum) > 1 else 0.0
    score_gap = top.final_score - second_score

    if top.final_score >= CLEAR_WINNER_THRESHOLD and score_gap >= CLEAR_WINNER_GAP:
        return "clear_winner", [top]
    if top.final_score >= AMBIGUOUS_THRESHOLD and score_gap < CLEAR_WINNER_GAP:
        return "ambiguous", above_minimum[:5]
    return "low_confidence", above_minimum[:5]
