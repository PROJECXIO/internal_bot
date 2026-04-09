from unittest import TestCase
from unittest.mock import MagicMock, patch

from internal_bot.bot.nodes import query_planner


class TestQueryPlanner(TestCase):
	def test_passes_presentation_plan_to_generate_query_intent(self):
		llm = MagicMock()
		llm.provider = "MockLLM"
		llm.model = "mock-model"
		llm.last_input_tokens = 5
		llm.last_output_tokens = 6
		settings = MagicMock()
		settings.max_result_rows = 100
		presentation_plan = {
			"visualization": "bar",
			"query_shape": "category_comparison",
			"dimension_hints": ["customer"],
			"metric_hints": ["grand_total"],
			"limit_hint": 10,
			"reason": "Compare customers",
		}
		state = {
			"user": "Administrator",
			"raw_message": "show sales by customer",
			"normalized_question": "show sales by customer",
			"schema_context": "## Sales Invoice",
			"presentation_plan": presentation_plan,
			"query_generation_attempts": 0,
			"input_tokens": 1,
			"output_tokens": 2,
			"_llm_client": llm,
			"_settings": settings,
			"node_trace": [],
			"timing": {},
		}
		intent = {
			"mode": "list",
			"doctype": "Customer",
			"fields": ["name"],
			"filters": [],
			"limit": 10,
		}

		with patch("internal_bot.bot.nodes.query_planner.sql_service.generate_query_intent") as mock_generate, \
		     patch("internal_bot.bot.nodes.query_planner.permission_service") as mock_perm, \
		     patch("internal_bot.bot.nodes.query_planner.query_executor") as mock_executor, \
		     patch("internal_bot.bot.nodes.query_planner.frappe.get_meta") as mock_get_meta:
			mock_generate.return_value = intent
			mock_perm.check_doctype_read_access.return_value = True
			mock_executor.execute_query_intent.return_value = ([{"name": "CUST-001"}], None)
			mock_get_meta.return_value = MagicMock(istable=False)

			result = query_planner.run(state)

		self.assertTrue(result["query_is_valid"])
		self.assertEqual(mock_generate.call_args.kwargs["presentation_plan"], presentation_plan)
