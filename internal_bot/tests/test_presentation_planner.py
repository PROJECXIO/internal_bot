from unittest import TestCase
from unittest.mock import MagicMock

from internal_bot.bot.nodes import presentation_planner


class TestPresentationPlanner(TestCase):
	def test_valid_llm_json_sets_advisory_plan_and_tokens(self):
		llm = MagicMock()
		llm.provider = "MockLLM"
		llm.model = "mock-model"
		llm.last_input_tokens = 11
		llm.last_output_tokens = 7
		llm.chat_completion.return_value = (
			'{"visualization": "line", "query_shape": "time_series", '
			'"dimension_hints": ["posting_date"], "metric_hints": ["grand_total"], '
			'"limit_hint": 20, "reason": "Trend over time"}'
		)
		state = {
			"raw_message": "show sales trend this month",
			"normalized_question": "show sales trend this month",
			"schema_context": "## Sales Invoice",
			"discovered_doctypes": ["Sales Invoice"],
			"response_language": "en",
			"input_tokens": 2,
			"output_tokens": 3,
			"_llm_client": llm,
			"node_trace": [],
			"timing": {},
		}

		result = presentation_planner.run(state)

		self.assertEqual(result["pre_query_visualization_preference"], "line")
		self.assertEqual(result["query_shape"], "time_series")
		self.assertEqual(result["presentation_plan"]["dimension_hints"], ["posting_date"])
		self.assertEqual(result["presentation_plan"]["metric_hints"], ["grand_total"])
		self.assertEqual(result["presentation_plan"]["limit_hint"], 20)
		self.assertEqual(result["presentation_reason"], "Trend over time")
		self.assertEqual(result["input_tokens"], 13)
		self.assertEqual(result["output_tokens"], 10)
		self.assertEqual(result["llm_provider"], "MockLLM")
		self.assertEqual(result["llm_model"], "mock-model")
		self.assertIn("presentation_planner", result["node_trace"])

	def test_no_llm_falls_back_to_auto(self):
		state = {
			"raw_message": "show customers",
			"normalized_question": "show customers",
			"node_trace": [],
			"timing": {},
			"_llm_client": None,
		}

		result = presentation_planner.run(state)

		self.assertEqual(result["presentation_plan"]["visualization"], "auto")
		self.assertEqual(result["pre_query_visualization_preference"], "auto")
		self.assertEqual(result["query_shape"], "auto")
		self.assertEqual(result["presentation_reason"], "")

	def test_metric_plan_drops_dimension_hints(self):
		llm = MagicMock()
		llm.provider = "MockLLM"
		llm.model = "mock-model"
		llm.last_input_tokens = 3
		llm.last_output_tokens = 4
		llm.chat_completion.return_value = (
			'{"visualization": "card", "query_shape": "metric", '
			'"dimension_hints": ["customer"], "metric_hints": ["grand_total"], '
			'"limit_hint": 20, "reason": "Customer sales total"}'
		)
		state = {
			"raw_message": "what are customer sales",
			"normalized_question": "what are customer sales",
			"input_tokens": 0,
			"output_tokens": 0,
			"_llm_client": llm,
			"node_trace": [],
			"timing": {},
		}

		result = presentation_planner.run(state)

		self.assertEqual(result["pre_query_visualization_preference"], "card")
		self.assertEqual(result["query_shape"], "metric")
		self.assertEqual(result["presentation_plan"]["dimension_hints"], [])
		self.assertEqual(result["presentation_plan"]["metric_hints"], ["grand_total"])

	def test_heatmap_matrix_plan_is_allowed(self):
		llm = MagicMock()
		llm.provider = "MockLLM"
		llm.model = "mock-model"
		llm.last_input_tokens = 3
		llm.last_output_tokens = 4
		llm.chat_completion.return_value = (
			'{"visualization": "heatmap", "query_shape": "matrix", '
			'"dimension_hints": ["customer", "item_code"], "metric_hints": ["grand_total"], '
			'"limit_hint": 50, "reason": "Customer item movement matrix"}'
		)
		state = {
			"raw_message": "حركة الاصناف عند كل عميل",
			"normalized_question": "حركة الاصناف عند كل عميل",
			"input_tokens": 0,
			"output_tokens": 0,
			"_llm_client": llm,
			"node_trace": [],
			"timing": {},
		}

		result = presentation_planner.run(state)

		self.assertEqual(result["pre_query_visualization_preference"], "heatmap")
		self.assertEqual(result["query_shape"], "matrix")
		self.assertEqual(result["presentation_plan"]["dimension_hints"], ["customer", "item_code"])

	def test_invalid_json_falls_back_to_auto(self):
		llm = MagicMock()
		llm.provider = "MockLLM"
		llm.model = "mock-model"
		llm.last_input_tokens = 4
		llm.last_output_tokens = 5
		llm.chat_completion.return_value = "not json"
		state = {
			"raw_message": "show customers",
			"normalized_question": "show customers",
			"input_tokens": 1,
			"output_tokens": 2,
			"_llm_client": llm,
			"node_trace": [],
			"timing": {},
		}

		result = presentation_planner.run(state)

		self.assertEqual(result["presentation_plan"]["visualization"], "auto")
		self.assertEqual(result["query_shape"], "auto")
		self.assertEqual(result["input_tokens"], 5)
		self.assertEqual(result["output_tokens"], 7)
