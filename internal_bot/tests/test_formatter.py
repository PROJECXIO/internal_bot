from frappe.tests.utils import FrappeTestCase

from internal_bot.bot.services.formatter import format_structured_response


class TestStructuredFormatter(FrappeTestCase):
	def _base_state(self, rows, message="show sales by territory"):
		return {
			"intent": "query",
			"raw_message": message,
			"normalized_question": message,
			"sql_result_rows": rows,
			"sql_generation_attempts": 0,
			"max_rows": 100,
		}

	def test_single_numeric_value_returns_metric_card(self):
		response = format_structured_response(
			self._base_state([{"total_sales": 125000}])
		)

		self.assertEqual(response["response_type"], "metric_card")
		self.assertEqual(response["visualization"]["kind"], "metric")
		self.assertEqual(response["visualization"]["formatted_value"], "125,000")

	def test_single_text_value_returns_plain_text(self):
		response = format_structured_response(
			self._base_state([{"supplier_name": "Test Supplier"}], message="what supplier has the biggest purchase invoice")
		)

		self.assertEqual(response["response_type"], "plain_text")
		self.assertIsNone(response["visualization"])
		self.assertEqual(response["summary"], "Test Supplier")

	def test_label_numeric_rows_return_bar_chart(self):
		response = format_structured_response(
			self._base_state(
				[
					{"territory": "West", "total_sales": 1200},
					{"territory": "East", "total_sales": 950},
				]
			)
		)

		self.assertEqual(response["response_type"], "bar_chart")
		self.assertEqual(response["visualization"]["kind"], "bar")
		self.assertEqual(response["visualization"]["categories"], ["West", "East"])

	def test_explicit_pie_chart_request_returns_pie_chart(self):
		response = format_structured_response(
			self._base_state(
				[
					{"territory": "West", "total_sales": 1200},
					{"territory": "East", "total_sales": 950},
				],
				message="show sales share by territory as a pie chart",
			)
		)

		self.assertEqual(response["response_type"], "pie_chart")
		self.assertEqual(response["visualization"]["kind"], "pie")

	def test_multi_metric_rows_fall_back_to_table(self):
		response = format_structured_response(
			self._base_state(
				[
					{"territory": "West", "total_sales": 1200, "total_orders": 25},
					{"territory": "East", "total_sales": 950, "total_orders": 18},
				]
			)
		)

		self.assertEqual(response["response_type"], "table")
		self.assertIsNone(response["visualization"])

	def test_negative_pie_values_fall_back_to_bar_chart(self):
		response = format_structured_response(
			self._base_state(
				[
					{"territory": "West", "net_change": -120},
					{"territory": "East", "net_change": 80},
				],
				message="show net change as a pie chart",
			)
		)

		self.assertEqual(response["response_type"], "bar_chart")
		self.assertEqual(response["visualization"]["kind"], "bar")
