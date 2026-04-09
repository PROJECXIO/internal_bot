from unittest import TestCase
from unittest.mock import MagicMock, patch

from internal_bot.bot.services import doctype_aliases


class TestDocTypeAliases(TestCase):
    @patch("internal_bot.bot.services.doctype_aliases.frappe.get_all")
    @patch("internal_bot.bot.services.doctype_aliases.frappe.cache")
    def test_default_arabic_sales_alias_is_available_without_admin_aliases(self, mock_cache, mock_get_all):
        cache = MagicMock()
        cache.get_value.return_value = None
        mock_cache.return_value = cache
        mock_get_all.return_value = []

        index = doctype_aliases.get_alias_index()

        self.assertEqual(index["مبيعات"], "Sales Invoice")
        self.assertIn("مبيعات", doctype_aliases.get_aliases_for_doctype("Sales Invoice"))

