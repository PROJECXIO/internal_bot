"""
Shared multilingual text normalization for schema retrieval.
"""
from __future__ import annotations

import re
import unicodedata

_ARABIC_CHAR_MAP = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ئ": "ي",
        "ؤ": "و",
        "ـ": "",
    }
)

_ENGLISH_STOP_WORDS = {
    "show", "me", "all", "the", "a", "an", "of", "in", "for", "and",
    "or", "is", "are", "was", "were", "what", "how", "by", "from",
    "to", "with", "on", "at", "between", "about", "into", "over",
    "give", "get", "find", "fetch", "list", "tell", "display", "return",
    "today", "yesterday", "last", "this", "month", "year", "week",
    "date", "time", "per", "each", "every", "day", "days", "period",
    "latest", "recent", "current", "previous", "past", "next",
    "total", "count", "number", "num", "many", "sum", "average", "avg",
    "summary", "report", "overview", "analysis", "breakdown", "detail",
    "details", "data", "info", "information", "record", "records",
    "result", "results", "figure", "figures", "please", "can", "you",
    "my", "our", "their", "there", "here", "that", "those", "these",
}

_ARABIC_STOP_WORDS = {
    "اعرض", "اظهر", "ارني", "وريني", "هات", "جيب", "قولي", "اخبرني",
    "كل", "جميع", "عن", "في", "من", "الى", "مع", "على", "بين",
    "كم", "ما", "ماذا", "كيف", "هل", "اذا", "او", "و", "ثم",
    "اليوم", "امس", "الشهر", "السنة", "الاسبوع", "الفترة", "الفترات",
    "تاريخ", "وقت", "حالياً", "حاليا", "الحالي", "الحالية", "السابق",
    "السابقة", "التالي", "القادم", "اجمالي", "إجمالي", "عدد", "متوسط",
    "ملخص", "تقرير", "نظرة", "تحليل", "تفصيل", "تفاصيل", "بيانات",
    "معلومات", "سجل", "سجلات", "نتيجة", "نتائج", "لو", "سمحت",
    "عندي", "لدي", "عندنا", "لدينا", "اريد", "أريد", "ابغى", "ابي",
    "هذا", "هذه", "هؤلاء", "ذلك", "تلك", "هناك", "هنا",
}

STOP_WORDS = _ENGLISH_STOP_WORDS | _ARABIC_STOP_WORDS


def normalize_text(text: str) -> str:
    if not text:
        return ""

    normalized = unicodedata.normalize("NFKD", text)
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    normalized = normalized.translate(_ARABIC_CHAR_MAP)
    normalized = normalized.lower()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def tokenize(text: str) -> list[str]:
    if not text:
        return []
    return [token for token in re.findall(r"[\w]+", text, re.UNICODE) if len(token) >= 2]


def make_ngrams(tokens: list[str], n: int = 2) -> list[str]:
    if n <= 0 or len(tokens) < n:
        return []
    return [" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def remove_stop_words(tokens: list[str]) -> list[str]:
    return [token for token in tokens if normalize_text(token) not in STOP_WORDS]
