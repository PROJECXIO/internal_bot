from unittest import TestCase
from unittest.mock import patch

from internal_bot.bot.services.hybrid_scorer import rank_candidates
from internal_bot.bot.services.schema_corpus import CorpusDocument


def _doc(doctype_name: str, token_set: set[str], aliases: list[str] | None = None) -> CorpusDocument:
    return CorpusDocument(
        doctype_name=doctype_name,
        module="Selling",
        description="",
        normalized_text=" ".join(sorted(token_set)),
        aliases=aliases or [],
        normalized_aliases=aliases or [],
        field_labels=[],
        link_targets=[],
        token_set=token_set,
        embedding=None,
    )


class TestHybridScorer(TestCase):
    @patch("internal_bot.bot.services.hybrid_scorer.permission_service.filter_permitted_doctypes")
    @patch("internal_bot.bot.services.hybrid_scorer.get_alias_index")
    def test_previous_doctype_gets_context_priority(self, mock_get_alias_index, mock_filter):
        mock_get_alias_index.return_value = {}
        mock_filter.side_effect = lambda names, user: names
        corpus = [
            _doc("Sales Order", {"sales", "order"}),
            _doc("Sales Invoice", {"sales", "invoice"}),
        ]

        candidates = rank_candidates(
            query="sales total",
            corpus=corpus,
            user="test@example.com",
            blocked=set(),
            preferred_doctypes=["Sales Invoice"],
        )

        self.assertTrue(candidates)
        self.assertEqual(candidates[0].doctype_name, "Sales Invoice")
        self.assertIn("conversation context priority", candidates[0].match_reason)

    @patch("internal_bot.bot.services.hybrid_scorer.permission_service.filter_permitted_doctypes")
    @patch("internal_bot.bot.services.hybrid_scorer.get_alias_index")
    def test_follow_up_priority_keeps_previous_doctype_when_query_is_generic(self, mock_get_alias_index, mock_filter):
        mock_get_alias_index.return_value = {}
        mock_filter.side_effect = lambda names, user: names
        corpus = [
            _doc("Sales Invoice", {"invoice", "customer"}),
            _doc("Quotation", {"quotation", "customer"}),
        ]

        candidates = rank_candidates(
            query="compare this year with last year",
            corpus=corpus,
            user="test@example.com",
            blocked=set(),
            preferred_doctypes=["Sales Invoice"],
            follow_up_to_previous_result=True,
        )

        self.assertTrue(candidates)
        self.assertEqual(candidates[0].doctype_name, "Sales Invoice")
        self.assertGreater(candidates[0].final_score, 0.4)
        self.assertIn("conversation follow-up priority", candidates[0].match_reason)

    @patch("internal_bot.bot.services.hybrid_scorer.permission_service.filter_permitted_doctypes")
    @patch("internal_bot.bot.services.hybrid_scorer.get_alias_index")
    def test_explicit_query_does_not_apply_previous_doctype_context_priority(self, mock_get_alias_index, mock_filter):
        mock_get_alias_index.return_value = {}
        mock_filter.side_effect = lambda names, user: names
        corpus = [
            _doc("Item", {"item"}),
            _doc("Sales Invoice", {"sales", "invoice"}),
        ]

        candidates = rank_candidates(
            query="sales for sku006 in 2026",
            corpus=corpus,
            user="test@example.com",
            blocked=set(),
            preferred_doctypes=["Item"],
        )

        self.assertTrue(candidates)
        self.assertEqual(candidates[0].doctype_name, "Sales Invoice")
        self.assertNotIn("Item", [candidate.doctype_name for candidate in candidates])
