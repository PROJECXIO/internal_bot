from unittest import TestCase

from internal_bot.bot.services.text_normalizer import (
    make_ngrams,
    normalize_phrase_for_match,
    normalize_text,
    normalize_token_for_match,
    remove_stop_words,
    tokenize,
)


class TestTextNormalizer(TestCase):
    def test_normalize_text_strips_arabic_diacritics(self):
        self.assertEqual(normalize_text("فَاتُورَةُ"), "فاتورة")

    def test_normalize_text_unifies_arabic_letter_variants(self):
        self.assertEqual(normalize_text("أإآٱىئؤـ"), "ااااييو")

    def test_normalize_token_for_match_strips_arabic_definite_article(self):
        self.assertEqual(normalize_token_for_match("المبيعات"), "مبيعات")

    def test_normalize_phrase_for_match_strips_arabic_definite_article_per_token(self):
        self.assertEqual(normalize_phrase_for_match("المبيعات بالشهر"), "مبيعات بشهر")

    def test_tokenize_supports_mixed_language_text(self):
        tokens = tokenize(normalize_text("show فاتورة مبيعات today"))
        self.assertEqual(tokens, ["show", "فاتورة", "مبيعات", "today"])

    def test_remove_stop_words_filters_english_and_arabic(self):
        tokens = ["show", "فاتورة", "مبيعات", "كم", "عميل"]
        self.assertEqual(remove_stop_words(tokens), ["فاتورة", "مبيعات", "عميل"])

    def test_remove_stop_words_filters_prefixed_arabic_stop_words(self):
        tokens = ["مبيعات", "بالشهر"]
        self.assertEqual(remove_stop_words(tokens), ["مبيعات"])

    def test_make_ngrams_builds_bigrams(self):
        self.assertEqual(
            make_ngrams(["sales", "invoice", "total"], n=2),
            ["sales invoice", "invoice total"],
        )
