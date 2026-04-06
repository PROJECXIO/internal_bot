from unittest import TestCase

from internal_bot.bot.nodes.schema_discovery import _should_prefer_previous_doctype


class TestSchemaDiscovery(TestCase):
    def test_previous_doctype_is_only_forced_for_brief_follow_ups(self):
        self.assertTrue(
            _should_prefer_previous_doctype(
                query_tokens=["انخفاضا", "كبير"],
                follow_up_to_previous_result=True,
            )
        )

    def test_previous_doctype_is_not_forced_for_explicit_item_sales_question(self):
        self.assertFalse(
            _should_prefer_previous_doctype(
                query_tokens=["مبيعات", "sku006", "2026"],
                follow_up_to_previous_result=True,
            )
        )
