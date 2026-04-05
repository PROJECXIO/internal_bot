from unittest import TestCase

from internal_bot.bot.services.text_normalizer import (
    make_ngrams,
    normalize_text,
    remove_stop_words,
    tokenize,
)


class TestTextNormalizer(TestCase):
    def test_normalize_text_strips_arabic_diacritics(self):
        self.assertEqual(normalize_text("فَاتُورَةُ"), "فاتورة")

    def test_normalize_text_unifies_arabic_letter_variants(self):
        self.assertEqual(normalize_text("أإآٱىئؤـ"), "ااااييو")

    def test_tokenize_supports_mixed_language_text(self):
        tokens = tokenize(normalize_text("show فاتورة مبيعات today"))
        self.assertEqual(tokens, ["show", "فاتورة", "مبيعات", "today"])

    def test_remove_stop_words_filters_english_and_arabic(self):
        tokens = ["show", "فاتورة", "مبيعات", "كم", "عميل"]
        self.assertEqual(remove_stop_words(tokens), ["فاتورة", "مبيعات", "عميل"])

    def test_make_ngrams_builds_bigrams(self):
        self.assertEqual(
            make_ngrams(["sales", "invoice", "total"], n=2),
            ["sales invoice", "invoice total"],
        )
