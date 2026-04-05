from unittest import TestCase
from unittest.mock import MagicMock

from internal_bot.bot.nodes import intent_classifier


class TestIntentClassifier(TestCase):
    def test_includes_current_calendar_context_in_first_llm_call(self):
        llm = MagicMock()
        llm.chat_completion.return_value = (
            '{"intent": "query", "normalized_question": "show sales today", "reason": "", "clarification_options": []}'
        )
        llm.last_input_tokens = 1
        llm.last_output_tokens = 1

        state = {
            "raw_message": "show sales today",
            "chat_history": [],
            "current_date": "2026-04-05",
            "current_day_name": "Sunday",
            "current_year": 2026,
            "node_trace": [],
            "timing": {},
            "input_tokens": 0,
            "output_tokens": 0,
            "_llm_client": llm,
        }

        result = intent_classifier.run(state)

        self.assertEqual(result["intent"], "query")
        messages = llm.chat_completion.call_args.kwargs["messages"]
        self.assertEqual(messages[1]["role"], "system")
        self.assertIn("Date: 2026-04-05", messages[1]["content"])
        self.assertIn("Day: Sunday", messages[1]["content"])
        self.assertIn("Year: 2026", messages[1]["content"])
