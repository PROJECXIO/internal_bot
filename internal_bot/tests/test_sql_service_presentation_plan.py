from unittest import TestCase
from unittest.mock import MagicMock

from internal_bot.bot.services.sql_service import generate_query_intent


class TestSqlServicePresentationPlan(TestCase):
	def test_includes_advisory_presentation_plan_in_prompt(self):
		llm = MagicMock()
		llm.chat_completion.return_value = (
			'{"mode": "analytics", "primary_doctype": "Sales Invoice", '
			'"dimensions": ["customer"], '
			'"metrics": [{"func": "SUM", "field": "grand_total", "alias": "total_sales"}], '
			'"filters": [], "limit": 10}'
		)

		intent = generate_query_intent(
			"show sales by customer",
			"## Sales Invoice",
			"",
			llm,
			presentation_plan={
				"visualization": "bar",
				"query_shape": "category_comparison",
				"dimension_hints": ["customer"],
				"metric_hints": ["grand_total"],
				"limit_hint": 10,
				"reason": "Compare customers",
			},
		)

		self.assertEqual(intent["mode"], "analytics")
		user_message = llm.chat_completion.call_args.args[0][1]["content"]
		self.assertIn("## Presentation Plan (Advisory)", user_message)
		self.assertIn("category_comparison", user_message)
		self.assertIn("grand_total", user_message)

	def test_metric_card_plan_drops_accidental_dimensions(self):
		llm = MagicMock()
		llm.chat_completion.return_value = (
			'{"mode": "analytics", "primary_doctype": "Sales Invoice", '
			'"dimensions": ["customer"], '
			'"metrics": [{"func": "SUM", "field": "grand_total", "alias": "total_sales"}], '
			'"filters": [], "limit": 20}'
		)

		intent = generate_query_intent(
			"what are customer sales",
			"## Sales Invoice",
			"",
			llm,
			presentation_plan={
				"visualization": "card",
				"query_shape": "metric",
				"dimension_hints": [],
				"metric_hints": ["grand_total"],
				"limit_hint": 20,
				"reason": "Customer sales total",
			},
		)

		self.assertEqual(intent["mode"], "analytics")
		self.assertEqual(intent["dimensions"], [])

	def test_metric_card_plan_keeps_dimensions_when_question_requests_grouping(self):
		llm = MagicMock()
		llm.chat_completion.return_value = (
			'{"mode": "analytics", "primary_doctype": "Sales Invoice", '
			'"dimensions": ["customer"], '
			'"metrics": [{"func": "SUM", "field": "grand_total", "alias": "total_sales"}], '
			'"filters": [], "limit": 20}'
		)

		intent = generate_query_intent(
			"show sales by customer",
			"## Sales Invoice",
			"",
			llm,
			presentation_plan={
				"visualization": "card",
				"query_shape": "metric",
				"dimension_hints": [],
				"metric_hints": ["grand_total"],
				"limit_hint": 20,
				"reason": "Customer sales total",
			},
		)

		self.assertEqual(intent["dimensions"], ["customer"])
