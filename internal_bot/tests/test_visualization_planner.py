from unittest import TestCase
from unittest.mock import MagicMock

from internal_bot.bot.nodes import visualization_planner


class TestVisualizationPlanner(TestCase):
	def test_actual_result_shape_can_override_advisory_plan(self):
		llm = MagicMock()
		llm.provider = "MockLLM"
		llm.model = "mock-model"
		llm.last_input_tokens = 9
		llm.last_output_tokens = 4
		llm.chat_completion.return_value = '{"visualization": "card", "prefix": "Here is the total:"}'
		state = {
			"raw_message": "show total sales",
			"normalized_question": "show total sales",
			"query_result_rows": [{"total_sales": 125000}],
			"presentation_plan": {
				"visualization": "line",
				"query_shape": "time_series",
				"reason": "Initial trend guess",
			},
			"response_language": "en",
			"input_tokens": 1,
			"output_tokens": 2,
			"_llm_client": llm,
			"node_trace": [],
			"timing": {},
		}

		result = visualization_planner.run(state)

		self.assertEqual(result["visualization_preference"], "card")
		user_message = llm.chat_completion.call_args.args[0][1]["content"]
		self.assertIn("Advisory presentation plan", user_message)
		self.assertIn("Initial trend guess", user_message)

	def test_heatmap_choice_is_allowed(self):
		llm = MagicMock()
		llm.provider = "MockLLM"
		llm.model = "mock-model"
		llm.last_input_tokens = 9
		llm.last_output_tokens = 4
		llm.chat_completion.return_value = '{"visualization": "heatmap", "prefix": "Here is the movement matrix:"}'
		state = {
			"raw_message": "حركة الاصناف عند كل عميل",
			"normalized_question": "حركة الاصناف عند كل عميل",
			"query_result_rows": [
				{"customer": "Grant Plastics Ltd.", "item_code": "SKU001", "total_sales": 67000},
				{"customer": "West View Software Ltd.", "item_code": "SKU001", "total_sales": 91000},
			],
			"response_language": "en",
			"input_tokens": 1,
			"output_tokens": 2,
			"_llm_client": llm,
			"node_trace": [],
			"timing": {},
		}

		result = visualization_planner.run(state)

		self.assertEqual(result["visualization_preference"], "heatmap")
