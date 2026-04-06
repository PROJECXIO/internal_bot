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

    def test_arabic_clarification_correction_is_forced_to_query(self):
        llm = MagicMock()
        llm.chat_completion.return_value = (
            '{"intent": "clarification_needed", "normalized_question": "", "reason": "need more details", "clarification_options": []}'
        )
        llm.last_input_tokens = 0
        llm.last_output_tokens = 0

        state = {
            "raw_message": "لا قصدي الاصناف الي مبيعاتها وقعت",
            "chat_history": [
                {"role": "user", "content": "حدد الاصناف الساقطة بعد شهر خمسه"},
                {
                    "role": "assistant",
                    "content": "هل تقصد الأصناف التي توقفت مبيعاتها تماماً بعد شهر خمسة؟ أو الأصناف التي شهدت انخفاضاً كبيراً في المبيعات؟",
                },
            ],
            "last_user_question": "حدد الاصناف الساقطة بعد شهر خمسه",
            "last_non_follow_up_user_question": "حدد الاصناف الساقطة بعد شهر خمسه",
            "last_assistant_response": {
                "status": "clarification_needed",
                "question": "هل تقصد الأصناف التي توقفت مبيعاتها تماماً بعد شهر خمسة؟ أو الأصناف التي شهدت انخفاضاً كبيراً في المبيعات؟",
                "options": [
                    "توقفت تماما",
                    "انخفاض كبير",
                ],
            },
            "node_trace": [],
            "timing": {},
            "input_tokens": 0,
            "output_tokens": 0,
            "_llm_client": llm,
        }

        result = intent_classifier.run(state)

        self.assertEqual(result["intent"], "query")
        self.assertEqual(result["normalized_question"], "الاصناف الي مبيعاتها وقعت")
        self.assertTrue(result["follow_up_to_previous_result"])
        llm.chat_completion.assert_not_called()

    def test_short_clarification_answer_reuses_previous_question_context(self):
        state = {
            "raw_message": "انخفاضا كبير",
            "chat_history": [
                {"role": "user", "content": "حدد الاصناف الساقطة بعد شهر خمسه"},
                {
                    "role": "assistant",
                    "content": "هل تقصد الأصناف التي توقفت مبيعاتها تماماً بعد شهر خمسة؟ أو الأصناف التي شهدت انخفاضاً كبيراً في المبيعات؟",
                },
            ],
            "last_user_question": "حدد الاصناف الساقطة بعد شهر خمسه",
            "last_non_follow_up_user_question": "حدد الاصناف الساقطة بعد شهر خمسه",
            "last_assistant_response": {
                "status": "clarification_needed",
                "question": "هل تقصد الأصناف التي توقفت مبيعاتها تماماً بعد شهر خمسة؟ أو الأصناف التي شهدت انخفاضاً كبيراً في المبيعات؟",
                "options": ["توقفت تماما", "انخفاض كبير"],
            },
            "node_trace": [],
            "timing": {},
            "input_tokens": 0,
            "output_tokens": 0,
            "_llm_client": None,
        }

        result = intent_classifier.run(state)

        self.assertEqual(result["intent"], "query")
        self.assertEqual(
            result["normalized_question"],
            "حدد الاصناف الساقطة بعد شهر خمسه انخفاضا كبير",
        )
        self.assertTrue(result["follow_up_to_previous_result"])

    def test_long_option_reply_keeps_previous_question_context(self):
        state = {
            "raw_message": "Last financial year to date",
            "chat_history": [
                {"role": "user", "content": "show sales invoices"},
                {
                    "role": "assistant",
                    "content": "Which period do you mean?",
                },
            ],
            "last_user_question": "show sales invoices",
            "last_non_follow_up_user_question": "show sales invoices",
            "last_assistant_response": {
                "status": "clarification_needed",
                "question": "Which period do you mean?",
                "options": ["This month", "Last month", "Last financial year to date"],
            },
            "node_trace": [],
            "timing": {},
            "input_tokens": 0,
            "output_tokens": 0,
            "_llm_client": None,
        }

        result = intent_classifier.run(state)

        self.assertEqual(result["intent"], "query")
        self.assertEqual(
            result["normalized_question"],
            "show sales invoices last financial year to date",
        )
        self.assertTrue(result["follow_up_to_previous_result"])
