from unittest.mock import MagicMock

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
