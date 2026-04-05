from unittest import TestCase
from unittest.mock import patch

from internal_bot.bot.services.hybrid_scorer import (
    ScoredCandidate,
    classify_confidence,
    cosine_similarity,
    rank_candidates,
)
from internal_bot.bot.services.schema_corpus import CorpusDocument
from internal_bot.bot.services.text_normalizer import normalize_text, remove_stop_words, tokenize


def _make_doc(
    doctype_name: str,
    text: str,
    aliases: list[str] | None = None,
    embedding: list[float] | None = None,
) -> CorpusDocument:
    normalized_text = normalize_text(text)
    return CorpusDocument(
        doctype_name=doctype_name,
        module="Selling",
        description="",
        normalized_text=normalized_text,
        aliases=aliases or [],
        normalized_aliases=[normalize_text(alias) for alias in aliases or []],
        field_labels=[],
        link_targets=[],
        token_set=set(remove_stop_words(tokenize(normalized_text))),
        embedding=embedding,
    )


class TestHybridScorer(TestCase):
    @patch("internal_bot.bot.services.hybrid_scorer.permission_service.filter_permitted_doctypes")
    @patch("internal_bot.bot.services.hybrid_scorer.get_alias_index")
    def test_exact_alias_match_wins(self, mock_alias_index, mock_filter):
        mock_alias_index.return_value = {"فاتورة مبيعات": "Sales Invoice"}
        mock_filter.side_effect = lambda names, user: names
        corpus = [
            _make_doc("Sales Invoice", "Sales Invoice customer invoice", aliases=["فاتورة مبيعات"]),
            _make_doc("Purchase Invoice", "Purchase Invoice supplier invoice", aliases=["فاتورة شراء"]),
        ]

        ranked = rank_candidates("فاتورة مبيعات", corpus, "test@example.com", set())

        self.assertEqual(ranked[0].doctype_name, "Sales Invoice")
        self.assertEqual(ranked[0].lexical_score, 1.0)

    @patch("internal_bot.bot.services.hybrid_scorer.permission_service.filter_permitted_doctypes")
    @patch("internal_bot.bot.services.hybrid_scorer.get_alias_index")
    def test_indirect_english_token_overlap_scores_customer(self, mock_alias_index, mock_filter):
        mock_alias_index.return_value = {}
        mock_filter.side_effect = lambda names, user: names
        corpus = [
            _make_doc("Customer", "Customer customer name customer group", aliases=["customers"]),
            _make_doc("Supplier", "Supplier supplier group", aliases=["suppliers"]),
        ]

        ranked = rank_candidates("how many customers do i have", corpus, "test@example.com", set())

        self.assertEqual(ranked[0].doctype_name, "Customer")
        self.assertGreater(ranked[0].final_score, 0)

    @patch("internal_bot.bot.services.hybrid_scorer.permission_service.filter_permitted_doctypes")
    @patch("internal_bot.bot.services.hybrid_scorer.get_alias_index")
    def test_plural_invoice_query_is_ambiguous(self, mock_alias_index, mock_filter):
        mock_alias_index.return_value = {}
        mock_filter.side_effect = lambda names, user: names
        corpus = [
            _make_doc("Sales Invoice", "Sales Invoice invoice invoices", aliases=["invoices"]),
            _make_doc("Purchase Invoice", "Purchase Invoice invoice invoices", aliases=["invoices"]),
        ]

        ranked = rank_candidates("invoices", corpus, "test@example.com", set())
        decision, selected = classify_confidence(ranked)

        self.assertEqual(decision, "ambiguous")
        self.assertEqual({candidate.doctype_name for candidate in selected}, {"Sales Invoice", "Purchase Invoice"})

    def test_low_confidence_classification(self):
        decision, selected = classify_confidence(
            [ScoredCandidate("Journal Entry", 0.18, 0.0, 0.18, "weak overlap")]
        )

        self.assertEqual(decision, "low_confidence")
        self.assertEqual(selected[0].doctype_name, "Journal Entry")

    @patch("internal_bot.bot.services.hybrid_scorer.permission_service.filter_permitted_doctypes")
    @patch("internal_bot.bot.services.hybrid_scorer.get_alias_index")
    def test_permission_filter_removes_inaccessible_candidates(self, mock_alias_index, mock_filter):
        mock_alias_index.return_value = {}
        mock_filter.return_value = ["Customer"]
        corpus = [
            _make_doc("Customer", "Customer customers", aliases=["customers"]),
            _make_doc("Supplier", "Supplier suppliers", aliases=["suppliers"]),
        ]

        ranked = rank_candidates("customers and suppliers", corpus, "limited@example.com", set())

        self.assertEqual([candidate.doctype_name for candidate in ranked], ["Customer"])

    @patch("internal_bot.bot.services.hybrid_scorer.permission_service.filter_permitted_doctypes")
    @patch("internal_bot.bot.services.hybrid_scorer.get_alias_index")
    def test_semantic_score_blends_with_lexical_score(self, mock_alias_index, mock_filter):
        mock_alias_index.return_value = {}
        mock_filter.side_effect = lambda names, user: names
        corpus = [
            _make_doc("Sales Invoice", "Sales Invoice", embedding=[1.0, 0.0]),
            _make_doc("Customer", "Customer", embedding=[0.0, 1.0]),
        ]

        ranked = rank_candidates(
            "revenue",
            corpus,
            "test@example.com",
            set(),
            query_embedding=[1.0, 0.0],
        )

        self.assertEqual(ranked[0].doctype_name, "Sales Invoice")
        self.assertGreater(ranked[0].semantic_score, 0)

    def test_cosine_similarity_handles_basic_vectors(self):
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [1.0, 0.0]), 1.0)
