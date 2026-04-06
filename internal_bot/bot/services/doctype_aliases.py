"""
Cached access to admin-managed DocType aliases.
"""
from __future__ import annotations

from collections import defaultdict

import frappe

from internal_bot.bot.services.text_normalizer import normalize_phrase_for_match, normalize_text

_ALIAS_CACHE_KEY = "internal_bot:doctype_aliases:v2"
_ALIAS_CACHE_TTL = 30 * 60

_DEFAULT_ALIASES_BY_DOCTYPE: dict[str, list[str]] = {
    "Sales Invoice": [
        "مبيعات",
        "فاتورة مبيعات",
        "فواتير مبيعات",
        "ايراد",
        "ايرادات",
    ],
    "Sales Order": [
        "طلب بيع",
        "طلبات بيع",
    ],
    "Item": [
        "صنف",
        "اصناف",
        "منتج",
        "منتجات",
        "sku",
    ],
    "Customer": [
        "عميل",
        "عملاء",
    ],
    "Supplier": [
        "مورد",
        "موردين",
    ],
}


def get_alias_index() -> dict[str, str]:
    payload = _get_alias_payload()
    return dict(payload.get("index") or {})


def get_aliases_for_doctype(doctype: str) -> list[str]:
    payload = _get_alias_payload()
    return list((payload.get("by_doctype") or {}).get(doctype) or [])


def invalidate_alias_cache():
    frappe.cache().delete_value(_ALIAS_CACHE_KEY)
    try:
        from internal_bot.bot.services import schema_corpus

        schema_corpus.invalidate_corpus_cache()
    except Exception:
        pass


def _get_alias_payload() -> dict:
    cached = frappe.cache().get_value(_ALIAS_CACHE_KEY)
    if isinstance(cached, dict):
        return cached

    rows = frappe.get_all(
        "AI DocType Alias",
        fields=["doctype_name", "alias"],
        order_by="doctype_name asc, alias asc",
    )

    by_doctype: dict[str, list[str]] = defaultdict(list)
    alias_to_doctypes: dict[str, set[str]] = defaultdict(set)

    for row in rows:
        doctype = (row.get("doctype_name") or "").strip()
        alias = (row.get("alias") or "").strip()
        normalized_alias = normalize_text(alias)
        match_alias = normalize_phrase_for_match(alias)
        if not doctype or not alias or not normalized_alias:
            continue
        by_doctype[doctype].append(alias)
        alias_to_doctypes[normalized_alias].add(doctype)
        if match_alias:
            alias_to_doctypes[match_alias].add(doctype)

    for doctype, aliases in _DEFAULT_ALIASES_BY_DOCTYPE.items():
        for alias in aliases:
            normalized_alias = normalize_text(alias)
            match_alias = normalize_phrase_for_match(alias)
            if not normalized_alias:
                continue
            by_doctype[doctype].append(alias)
            if normalized_alias not in alias_to_doctypes:
                alias_to_doctypes[normalized_alias].add(doctype)
            if match_alias and match_alias not in alias_to_doctypes:
                alias_to_doctypes[match_alias].add(doctype)

    index = {
        alias: next(iter(sorted(doctypes)))
        for alias, doctypes in alias_to_doctypes.items()
        if len(doctypes) == 1
    }
    payload = {
        "index": index,
        "by_doctype": {doctype: sorted(set(aliases)) for doctype, aliases in by_doctype.items()},
    }
    frappe.cache().set_value(_ALIAS_CACHE_KEY, payload, expires_in_sec=_ALIAS_CACHE_TTL)
    return payload
