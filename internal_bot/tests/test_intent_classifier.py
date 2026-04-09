from unittest import TestCase
from unittest.mock import MagicMock, patch

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

    def test_detected_message_language_is_saved_in_state(self):
        llm = MagicMock()
        llm.chat_completion.return_value = (
            '{"intent": "query", "normalized_question": "مبيعات العملاء", "detected_language": "ar", "reason": "", "clarification_options": []}'
        )
        llm.last_input_tokens = 1
        llm.last_output_tokens = 1

        state = {
            "raw_message": "مبيعات العملاء",
            "chat_history": [],
            "user_profile_language": "en",
            "node_trace": [],
            "timing": {},
            "input_tokens": 0,
            "output_tokens": 0,
            "_llm_client": llm,
        }

        result = intent_classifier.run(state)

        self.assertEqual(result["response_language"], "ar")
        self.assertEqual(result["response_language_source"], "message")

    def test_unclear_message_falls_back_to_user_profile_language(self):
        llm = MagicMock()
        llm.chat_completion.return_value = (
            '{"intent": "query", "normalized_question": "2024", "detected_language": "", "reason": "", "clarification_options": []}'
        )
        llm.last_input_tokens = 1
        llm.last_output_tokens = 1

        state = {
            "raw_message": "2024",
            "chat_history": [],
            "user_profile_language": "ar",
            "node_trace": [],
            "timing": {},
            "input_tokens": 0,
            "output_tokens": 0,
            "_llm_client": llm,
        }

        result = intent_classifier.run(state)

        self.assertEqual(result["response_language"], "ar")
        self.assertEqual(result["response_language_source"], "profile")

    def test_no_llm_uses_stable_language_fallback(self):
        state = {
            "raw_message": "2024",
            "chat_history": [],
            "user_profile_language": "en",
            "node_trace": [],
            "timing": {},
            "input_tokens": 0,
            "output_tokens": 0,
            "_llm_client": None,
        }

        result = intent_classifier.run(state)

        self.assertEqual(result["response_language"], "en")
        self.assertEqual(result["response_language_source"], "profile")

    @patch("internal_bot.bot.nodes.intent_classifier.frappe.db.get_value")
    def test_greeting_includes_user_name(self, mock_get_value):
        llm = MagicMock()
        llm.chat_completion.return_value = (
            '{"intent": "greeting", "normalized_question": "hi", "detected_language": "en", "reason": "Hello! How can I help you today?", "clarification_options": []}'
        )
        llm.last_input_tokens = 1
        llm.last_output_tokens = 1
        mock_get_value.return_value = "John Doe"

        state = {
            "user": "john@example.com",
            "raw_message": "hi",
            "chat_history": [],
            "node_trace": [],
            "timing": {},
            "input_tokens": 0,
            "output_tokens": 0,
            "_llm_client": llm,
        }

        result = intent_classifier.run(state)

        self.assertEqual(result["intent"], "greeting")
        self.assertEqual(result["intent_reason"], "Hello John! How can I help you today?")
