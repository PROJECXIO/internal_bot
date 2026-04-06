from unittest import TestCase
from unittest.mock import MagicMock

from internal_bot.bot.nodes import clarification_planner


class TestClarificationPlanner(TestCase):
	def test_arabic_clarification_question_and_period_options_follow_response_language(self):
		llm = MagicMock()
		llm.provider = "MockLLM"
		llm.model = "mock-model"
		llm.last_input_tokens = 10
		llm.last_output_tokens = 5
		llm.chat_completion.return_value = (
			'{"ready": false, "question": "ما الفترة التي تقصدها؟", '
			'"options": ["كل التواريخ", "هذا الشهر", "الشهر الماضي"]}'
		)

		state = {
			"raw_message": "مبيعات كل صنف",
			"normalized_question": "مبيعات كل صنف for a period",
			"discovered_doctypes": ["Sales Invoice"],
			"response_language": "ar",
			"chat_history": [],
			"input_tokens": 0,
			"output_tokens": 0,
			"_llm_client": llm,
			"node_trace": [],
			"timing": {},
		}

		result = clarification_planner.run(state)

		self.assertFalse(result["ready_to_query"])
		self.assertEqual(result["clarification_question"], "ما الفترة التي تقصدها؟")
		self.assertEqual(
			result["clarification_options"],
			["كل التواريخ", "هذا الشهر", "الشهر الماضي"],
		)
