from frappe.tests.utils import FrappeTestCase

from internal_bot.bot.services.formatter import format_structured_response, normalize_cached_response


class TestStructuredFormatter(FrappeTestCase):
	def _base_state(self, rows, message="show sales by territory"):
		return {
			"intent": "query",
			"raw_message": message,
			"normalized_question": message,
			"query_result_rows": rows,
			"query_generation_attempts": 0,
			"max_rows": 100,
		}

	def test_single_numeric_value_defaults_to_plain_text(self):
		response = format_structured_response(
			self._base_state([{"total_sales": 125000}])
		)

		self.assertEqual(response["response_type"], "metric_card")
		self.assertEqual(response["visualization"]["kind"], "metric")
		self.assertEqual(response["summary"], "Total Sales: 125,000")
		self.assertEqual(response["markdown"], "")

	def test_single_numeric_value_returns_metric_card_when_requested(self):
		response = format_structured_response(
			self._base_state([{"total_sales": 125000}], message="show total sales as a metric card")
		)

		self.assertEqual(response["response_type"], "metric_card")
		self.assertEqual(response["visualization"]["kind"], "metric")
		self.assertEqual(response["visualization"]["formatted_value"], "125,000")
		self.assertEqual(response["markdown"], "")

	def test_single_text_value_returns_plain_text(self):
		response = format_structured_response(
			self._base_state([{"supplier_name": "Test Supplier"}], message="what supplier has the biggest purchase invoice")
		)

		self.assertEqual(response["response_type"], "plain_text")
		self.assertIsNone(response["visualization"])
		self.assertEqual(response["summary"], "Test Supplier")
		self.assertEqual(response["markdown"], "")

	def test_label_numeric_rows_default_to_bar_chart(self):
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
		self.assertEqual(response["markdown"], "")

	def test_label_numeric_rows_return_bar_chart_when_requested(self):
		response = format_structured_response(
			self._base_state(
				[
					{"territory": "West", "total_sales": 1200},
					{"territory": "East", "total_sales": 950},
				],
				message="show sales by territory as a bar chart",
			)
		)

		self.assertEqual(response["response_type"], "bar_chart")
		self.assertEqual(response["visualization"]["kind"], "bar")
		self.assertEqual(response["visualization"]["categories"], ["West", "East"])
		self.assertEqual(response["markdown"], "")

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
		self.assertEqual(response["markdown"], "")

	def test_breakdown_word_does_not_force_pie_chart_for_ranked_sales(self):
		response = format_structured_response(
			self._base_state(
				[
					{"item_code": "SKU007", "total_sales": 90000},
					{"item_code": "SKU006", "total_sales": 89000},
					{"item_code": "SKU003", "total_sales": 50000},
				],
				message="show me the sales breakdown by item for 2025-09-16",
			)
		)

		self.assertEqual(response["response_type"], "bar_chart")
		self.assertEqual(response["visualization"]["kind"], "bar")
		self.assertEqual(response["visualization"]["categories"], ["SKU007", "SKU006", "SKU003"])

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
		self.assertEqual(response["markdown"], "")

	def test_multi_metric_rows_support_grouped_bar_chart(self):
		response = format_structured_response(
			self._base_state(
				[
					{"territory": "West", "total_sales": 1200, "total_orders": 25},
					{"territory": "East", "total_sales": 950, "total_orders": 18},
				],
				message="show grouped column chart for sales and orders by territory",
			)
		)

		self.assertEqual(response["response_type"], "bar_chart")
		self.assertEqual(response["visualization"]["kind"], "grouped_bar")
		self.assertEqual(response["visualization"]["layout"], "vertical")
		self.assertEqual(response["visualization"]["categories"], ["West", "East"])
		self.assertEqual(
			response["visualization"]["value_keys"],
			["total_sales", "total_orders"],
		)
		self.assertEqual(
			response["visualization"]["series"],
			[
				{"name": "Total Sales", "data": [1200.0, 950.0]},
				{"name": "Total Orders", "data": [25.0, 18.0]},
			],
		)

	def test_long_form_comparison_rows_support_grouped_bar_chart(self):
		response = format_structured_response(
			self._base_state(
				[
					{"item_code": "SKU003", "posting_date": "2025-09-16", "total_sales": 50000},
					{"item_code": "SKU006", "posting_date": "2025-09-16", "total_sales": 89000},
					{"item_code": "SKU007", "posting_date": "2025-09-16", "total_sales": 90000},
					{"item_code": "SKU008", "posting_date": "2026-03-03", "total_sales": 10000},
					{"item_code": "SKU009", "posting_date": "2026-03-03", "total_sales": 12000},
					{"item_code": "SKU010", "posting_date": "2026-03-03", "total_sales": 45000},
				],
				message="compare item sales between 2025-09-16 and 2026-03-03",
			)
		)

		self.assertEqual(response["response_type"], "bar_chart")
		self.assertEqual(response["visualization"]["kind"], "grouped_bar")
		self.assertEqual(response["visualization"]["label_key"], "item_code")
		self.assertEqual(response["visualization"]["series_key"], "posting_date")
		self.assertEqual(response["visualization"]["value_key"], "total_sales")
		self.assertEqual(
			response["visualization"]["categories"],
			["SKU003", "SKU006", "SKU007", "SKU008", "SKU009", "SKU010"],
		)
		self.assertEqual(
			response["visualization"]["series"],
			[
				{"name": "2025-09-16", "data": [50000.0, 89000.0, 90000.0, 0.0, 0.0, 0.0]},
				{"name": "2026-03-03", "data": [0.0, 0.0, 0.0, 10000.0, 12000.0, 45000.0]},
			],
		)

	def test_daily_item_sales_rows_support_grouped_bar_chart(self):
		response = format_structured_response(
			self._base_state(
				[
					{"DATE(posting_date)": "2025-09-03", "item_code": "SKU001", "total_sales": 20000},
					{"DATE(posting_date)": "2025-09-03", "item_code": "SKU002", "total_sales": 12000},
					{"DATE(posting_date)": "2025-09-16", "item_code": "SKU003", "total_sales": 50000},
					{"DATE(posting_date)": "2025-09-16", "item_code": "SKU006", "total_sales": 89000},
					{"DATE(posting_date)": "2025-09-16", "item_code": "SKU007", "total_sales": 90000},
					{"DATE(posting_date)": "2025-09-26", "item_code": "SKU004", "total_sales": 20000},
				],
				message="make chart for sales for all items per day",
			)
		)

		self.assertEqual(response["response_type"], "bar_chart")
		self.assertEqual(response["visualization"]["kind"], "grouped_bar")
		self.assertEqual(response["visualization"]["label_key"], "DATE(posting_date)")
		self.assertEqual(response["visualization"]["series_key"], "item_code")
		self.assertEqual(response["visualization"]["value_key"], "total_sales")
		self.assertEqual(
			response["visualization"]["categories"],
			["2025-09-03", "2025-09-16", "2025-09-26"],
		)
		self.assertEqual(
			response["visualization"]["series"],
			[
				{"name": "SKU001", "data": [20000.0, 0.0, 0.0]},
				{"name": "SKU002", "data": [12000.0, 0.0, 0.0]},
				{"name": "SKU003", "data": [0.0, 50000.0, 0.0]},
				{"name": "SKU006", "data": [0.0, 89000.0, 0.0]},
				{"name": "SKU007", "data": [0.0, 90000.0, 0.0]},
				{"name": "SKU004", "data": [0.0, 0.0, 20000.0]},
			],
		)
		self.assertEqual(
			response["summary"],
			"2025-09-16 is highest overall at 229,000 across 6 item code groups.",
		)

	def test_year_month_day_comparison_rows_support_grouped_bar_chart(self):
		response = format_structured_response(
			self._base_state(
				[
					{"YEAR(posting_date)": 2025, "MONTH(posting_date)": 2, "DAY(posting_date)": 12, "total_sales": 18000},
					{"YEAR(posting_date)": 2026, "MONTH(posting_date)": 2, "DAY(posting_date)": 12, "total_sales": 15000},
					{"YEAR(posting_date)": 2025, "MONTH(posting_date)": 3, "DAY(posting_date)": 3, "total_sales": 42000},
					{"YEAR(posting_date)": 2026, "MONTH(posting_date)": 3, "DAY(posting_date)": 3, "total_sales": 67000},
				],
				message="compare daily sales invoices between this year and last year",
			)
		)

		self.assertEqual(response["response_type"], "bar_chart")
		self.assertEqual(response["visualization"]["kind"], "grouped_bar")
		self.assertEqual(response["visualization"]["label_key"], "month_day")
		self.assertEqual(response["visualization"]["series_key"], "YEAR(posting_date)")
		self.assertEqual(response["visualization"]["categories"], ["02-12", "03-03"])
		self.assertEqual(
			response["visualization"]["series"],
			[
				{"name": "2025", "data": [18000.0, 42000.0]},
				{"name": "2026", "data": [15000.0, 67000.0]},
			],
		)

	def test_large_daily_item_sales_rows_still_support_grouped_bar_chart(self):
		response = format_structured_response(
			self._base_state(
				[
					{"DATE(posting_date)": "2025-09-03", "item_code": "SKU001", "total_sales": 20000},
					{"DATE(posting_date)": "2025-09-03", "item_code": "SKU002", "total_sales": 12000},
					{"DATE(posting_date)": "2025-09-16", "item_code": "SKU003", "total_sales": 50000},
					{"DATE(posting_date)": "2025-09-16", "item_code": "SKU006", "total_sales": 89000},
					{"DATE(posting_date)": "2025-09-16", "item_code": "SKU007", "total_sales": 90000},
					{"DATE(posting_date)": "2025-09-26", "item_code": "SKU004", "total_sales": 20000},
					{"DATE(posting_date)": "2026-02-12", "item_code": "SKU005", "total_sales": 15000},
					{"DATE(posting_date)": "2026-03-03", "item_code": "SKU008", "total_sales": 10000},
					{"DATE(posting_date)": "2026-03-03", "item_code": "SKU009", "total_sales": 12000},
					{"DATE(posting_date)": "2026-03-03", "item_code": "SKU010", "total_sales": 45000},
					{"DATE(posting_date)": "2026-04-17", "item_code": "SKU004", "total_sales": 20000},
					{"DATE(posting_date)": "2026-04-30", "item_code": "SKU004", "total_sales": 40000},
					{"DATE(posting_date)": "2026-05-14", "item_code": "SKU004", "total_sales": 20000},
				],
				message="make chart for sales for all items per day per item",
			)
		)

		self.assertEqual(response["response_type"], "bar_chart")
		self.assertEqual(response["visualization"]["kind"], "grouped_bar")
		self.assertEqual(response["visualization"]["label_key"], "DATE(posting_date)")
		self.assertEqual(response["visualization"]["series_key"], "item_code")
		self.assertEqual(len(response["visualization"]["categories"]), 7)
		self.assertEqual(len(response["visualization"]["series"]), 10)

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
		self.assertEqual(response["markdown"], "")

	def test_cached_single_text_table_is_normalized_to_plain_text(self):
		cached = {
			"status": "success",
			"response_type": "table",
			"title": "Supplier with biggest grand total purchase invoice",
			"columns": ["supplier_name"],
			"rows": [{"supplier_name": "Test Supplier"}],
			"summary": "Returned 1 row across 1 column.",
			"visualization": None,
			"meta": {"confidence": 0.95, "has_more": False, "returned_rows": 1},
		}

		response = normalize_cached_response(
			cached,
			self._base_state(
				[{"supplier_name": "Test Supplier"}],
				message="what the name of the supplier with biggest grand total purchase invoice",
			),
		)

		self.assertEqual(response["response_type"], "plain_text")
		self.assertEqual(response["summary"], "Test Supplier")
		self.assertEqual(response["markdown"], "")

	def test_follow_up_analysis_for_chart_forces_plain_text_response(self):
		response = format_structured_response(
			{
				**self._base_state(
					[
						{"posting_date": "2025-09-16", "total_sales": 229000},
						{"posting_date": "2025-09-03", "total_sales": 32000},
					],
					message="analysis this data more",
				),
				"visualization_preference": "text",
				"follow_up_to_previous_result": True,
				"last_assistant_response": {"response_type": "bar_chart"},
				"answer_markdown": "- **2025-09-16** was the strongest day at **229,000**.",
			}
		)

		self.assertEqual(response["response_type"], "plain_text")
		self.assertIsNone(response["visualization"])
		self.assertEqual(response["markdown"], "- **2025-09-16** was the strongest day at **229,000**.")

	def test_debug_context_window_is_gated_by_settings(self):
		settings = type("Settings", (), {"enable_debug_context_window": 0})()
		response = format_structured_response(
			{
				**self._base_state([{"total_sales": 125000}]),
				"debug": True,
				"_settings": settings,
				"chat_history": [{"role": "user", "content": "show total sales"}],
				"memory_summary": "Asked about total sales.",
				"last_assistant_context_text": "Title: Total Sales",
				"schema_context": "## Sales Invoice",
				"input_tokens": 10,
				"output_tokens": 5,
			}
		)

		self.assertIn("debug", response)
		self.assertNotIn("context_window", response["debug"])
		self.assertNotIn("token_usage", response["debug"])

	def test_debug_context_window_and_tokens_are_included_when_enabled(self):
		settings = type("Settings", (), {"enable_debug_context_window": 1})()
		response = format_structured_response(
			{
				**self._base_state([{"total_sales": 125000}]),
				"debug": True,
				"_settings": settings,
				"chat_history": [{"role": "user", "content": "show total sales"}],
				"memory_summary": "Asked about total sales.",
				"last_assistant_context_text": "Title: Total Sales",
				"schema_context": "## Sales Invoice",
				"last_user_question": "show total sales",
				"last_non_follow_up_user_question": "show total sales",
				"follow_up_to_previous_result": True,
				"discovered_doctypes": ["Sales Invoice"],
				"visualization_preference": "bar",
				"input_tokens": 10,
				"output_tokens": 5,
			}
		)

		self.assertEqual(response["debug"]["token_usage"]["input_tokens"], 10)
		self.assertEqual(response["debug"]["token_usage"]["output_tokens"], 5)
		self.assertEqual(response["debug"]["token_usage"]["total_tokens"], 15)
		self.assertEqual(
			response["debug"]["context_window"]["question_context"]["normalized_question"],
			"show sales by territory",
		)
		self.assertEqual(
			response["debug"]["context_window"]["question_context"]["discovered_doctypes"],
			["Sales Invoice"],
		)
