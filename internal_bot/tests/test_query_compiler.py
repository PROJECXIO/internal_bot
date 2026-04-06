from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from internal_bot.bot.services.query_compiler import compile_analytics_intent


class TestQueryCompiler(TestCase):
    @patch("internal_bot.bot.services.query_compiler.frappe.get_list")
    @patch("internal_bot.bot.services.query_compiler.frappe.get_meta")
    @patch("internal_bot.bot.services.query_compiler.permission_service.get_permitted_field_names")
    @patch("internal_bot.bot.services.query_compiler.permission_service.check_doctype_read_access")
    def test_year_month_dimension_escapes_percent_signs(
        self,
        mock_check_access,
        mock_get_fields,
        mock_get_meta,
        mock_get_list,
    ):
        mock_check_access.return_value = True
        mock_get_fields.side_effect = lambda doctype, user: {
            "Sales Invoice": ["posting_date", "docstatus"],
            "Sales Invoice Item": ["item_code", "amount"],
        }[doctype]
        mock_get_meta.side_effect = lambda doctype: SimpleNamespace(
            istable=(doctype == "Sales Invoice Item"),
            get_field=lambda fieldname: None,
        )
        mock_get_list.return_value = [SimpleNamespace(name="SINV-0001")]

        sql, params = compile_analytics_intent(
            {
                "mode": "analytics",
                "primary_doctype": "Sales Invoice",
                "joins": [
                    {
                        "child_doctype": "Sales Invoice Item",
                        "parent_link_field": "parent",
                        "join_type": "LEFT",
                    }
                ],
                "dimensions": ["YEAR_MONTH(posting_date)", "item_code"],
                "metrics": [{"func": "SUM", "field": "amount", "alias": "total_amount"}],
                "filters": [["docstatus", "=", 1]],
                "order_by": "YEAR_MONTH(posting_date) asc",
                "limit": 100,
            },
            user="Administrator",
            max_rows=100,
        )

        self.assertIn("DATE_FORMAT(`tabSales Invoice`.`posting_date`, '%%Y-%%m')", sql)
        self.assertIn("GROUP BY DATE_FORMAT(`tabSales Invoice`.`posting_date`, '%%Y-%%m')", sql)
        self.assertEqual(params[-1], 100)
