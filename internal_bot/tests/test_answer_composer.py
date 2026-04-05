from unittest.mock import MagicMock
import json

from frappe.tests.utils import FrappeTestCase

from internal_bot.bot.nodes import answer_composer


class TestAnswerComposer(FrappeTestCase):
	def test_answer_composer_sets_markdown_and_token_counts(self):
		llm = MagicMock()
		llm.provider = "MockLLM"
		llm.model = "mock-model"
		llm.last_input_tokens = 21
		llm.last_output_tokens = 13
		llm.chat_completion.return_value = "## Summary\n\n- West leads sales."

		state = {
			"raw_message": "show sales by territory",
			"normalized_question": "show sales by territory",
			"query_result_rows": [
				{"territory": "West", "total_sales": 1200},
				{"territory": "East", "total_sales": 950},
			],
			"visualization_preference": "bar",
			"answer_prefix": "Here's the breakdown:",
			"input_tokens": 0,
			"output_tokens": 0,
			"_llm_client": llm,
			"node_trace": [],
			"timing": {},
		}

		result = answer_composer.run(state)

		self.assertEqual(result["answer_markdown"], "## Summary\n\n- West leads sales.")
		self.assertEqual(result["input_tokens"], 21)
		self.assertEqual(result["output_tokens"], 13)
		self.assertEqual(result["formatted_response"]["status"], "success")

	def test_answer_composer_removes_repeated_answer_prefix(self):
		llm = MagicMock()
		llm.provider = "MockLLM"
		llm.model = "mock-model"
		llm.last_input_tokens = 10
		llm.last_output_tokens = 6
		llm.chat_completion.return_value = "Here's the breakdown:\n\n- **SKU007** leads sales."

		state = {
			"raw_message": "show item sales by sku",
			"normalized_question": "show item sales by sku",
			"query_result_rows": [
				{"item_code": "SKU007", "total_sales": 90000},
				{"item_code": "SKU006", "total_sales": 89000},
				{"item_code": "SKU003", "total_sales": 50000},
			],
			"visualization_preference": "bar",
			"answer_prefix": "Here's the breakdown:",
			"input_tokens": 0,
			"output_tokens": 0,
			"_llm_client": llm,
			"node_trace": [],
			"timing": {},
		}

		result = answer_composer.run(state)

		self.assertEqual(result["answer_markdown"], "- **SKU007** leads sales.")

		payload = json.loads(llm.chat_completion.call_args.args[0][1]["content"])
		self.assertEqual(payload["response_type"], "bar_chart")
		self.assertEqual(payload["visualization_kind"], "bar")

	def test_grouped_bar_payload_includes_full_sample_and_grouped_hints(self):
		llm = MagicMock()
		llm.provider = "MockLLM"
		llm.model = "mock-model"
		llm.last_input_tokens = 14
		llm.last_output_tokens = 9
		llm.chat_completion.return_value = "- **2025-09-16** is the peak day."

		state = {
			"raw_message": "make chart for sales for all items per day per item",
			"normalized_question": "make chart for sales for all items per day per item",
			"query_result_rows": [
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
			"visualization_preference": "auto",
			"answer_prefix": "Here's the breakdown:",
			"input_tokens": 0,
			"output_tokens": 0,
			"_llm_client": llm,
			"node_trace": [],
			"timing": {},
		}

		answer_composer.run(state)

		payload = json.loads(llm.chat_completion.call_args.args[0][1]["content"])
		self.assertEqual(payload["response_type"], "bar_chart")
		self.assertEqual(payload["visualization_kind"], "grouped_bar")
		self.assertEqual(len(payload["data_rows"]), 13)
		self.assertEqual(payload["analysis_hints"]["shape"], "grouped_long_form")
		self.assertEqual(payload["analysis_hints"]["label_column"], "DATE(posting_date)")
		self.assertEqual(payload["analysis_hints"]["series_column"], "item_code")
		self.assertEqual(payload["analysis_hints"]["top_category_label"], "2025-09-16")
		self.assertEqual(payload["analysis_hints"]["top_series_label"], "SKU004")
