"""
Level 4 — API smoke tests.

Run with bench:
  bench --site <site> run-tests --app internal_bot --module internal_bot.tests.test_api
"""
import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import MagicMock, patch

from internal_bot.api.chat import (
	ask,
	_get_or_create_session,
	create_session,
	delete_session,
	get_session_history,
	list_sessions,
)


class TestChatAPI(FrappeTestCase):
	def setUp(self):
		frappe.session.user = "Administrator"
		self._extra_session_names = []

	def tearDown(self):
		session_names = frappe.get_all(
			"AI Chat Session",
			filters={"user": "Administrator"},
			pluck="name",
		)
		session_names = list(set(session_names + self._extra_session_names))
		if session_names:
			frappe.db.delete("AI Chat Message", {"session": ["in", session_names]})
			frappe.db.delete("AI Chat Session", {"name": ["in", session_names]})
		frappe.db.commit()

	def test_empty_message_returns_error(self):
		response = ask(message="", debug=False)
		self.assertEqual(response["status"], "error")
		self.assertIn("empty", response["reason"].lower())

	def test_whitespace_only_message_returns_error(self):
		response = ask(message="   ", debug=False)
		self.assertEqual(response["status"], "error")

	def test_session_created_for_user(self):
		session_name = _get_or_create_session("Administrator")
		frappe.db.commit()
		self.assertTrue(frappe.db.exists("AI Chat Session", session_name))

	def test_get_or_create_session_reuses_latest_session(self):
		first_session = _get_or_create_session("Administrator")
		frappe.db.commit()
		second_session = _get_or_create_session("Administrator")
		frappe.db.commit()
		count = frappe.db.count("AI Chat Session", {"user": "Administrator"})
		self.assertEqual(first_session, second_session)
		self.assertEqual(count, 1)

	def test_create_session_creates_distinct_session(self):
		first = create_session()
		second = create_session()

		self.assertNotEqual(first["session_id"], second["session_id"])
		self.assertEqual(frappe.db.count("AI Chat Session", {"user": "Administrator"}), 2)

	def test_delete_session_removes_owned_session_and_messages(self):
		session = create_session()
		session_id = session["session_id"]

		frappe.get_doc(
			{
				"doctype": "AI Chat Message",
				"session": session_id,
				"user": "Administrator",
				"role": "user",
				"status": "success",
				"content": "show customers",
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

		response = delete_session(session_id)

		self.assertTrue(response["ok"])
		self.assertEqual(response["deleted_session_id"], session_id)
		self.assertFalse(frappe.db.exists("AI Chat Session", session_id))
		self.assertEqual(frappe.db.count("AI Chat Message", {"session": session_id}), 0)

	def test_deleted_session_no_longer_appears_in_session_list(self):
		session = create_session()
		session_id = session["session_id"]

		delete_session(session_id)
		session_list = list_sessions()

		self.assertFalse(any(item["session_id"] == session_id for item in session_list["sessions"]))

	def test_delete_missing_session_raises_not_found(self):
		with self.assertRaises(frappe.DoesNotExistError):
			delete_session("AICS-2099-01-01-99999")

	def test_delete_other_users_session_is_rejected_as_not_found(self):
		session = create_session()
		session_id = session["session_id"]
		frappe.db.set_value("AI Chat Session", session_id, "user", "Guest")
		frappe.db.commit()
		self._extra_session_names.append(session_id)

		with self.assertRaises(frappe.DoesNotExistError):
			delete_session(session_id)

	def test_ask_requires_login(self):
		frappe.session.user = "Guest"
		with self.assertRaises(frappe.exceptions.AuthenticationError):
			ask(message="show customers")

	def test_ask_with_mock_graph_returns_valid_structure(self):
		"""Smoke test: mock the graph and verify the API wraps the response correctly."""
		fake_response = {
			"status": "success",
			"response_type": "table",
			"visualization": None,
			"summary": "Returned 1 row across 1 column.",
			"markdown": "| name |\n| --- |\n| CUST-001 |",
			"title": "Customers",
			"columns": ["name"],
			"rows": [{"name": "CUST-001"}],
			"meta": {"confidence": 0.95, "has_more": False, "returned_rows": 1},
		}

		with patch("internal_bot.api.chat.get_graph") as mock_get_graph:
			mock_graph = MagicMock()
			mock_graph.invoke.return_value = {"formatted_response": fake_response}
			mock_get_graph.return_value = mock_graph

			with patch("internal_bot.api.chat.get_llm_client") as mock_llm_factory:
				mock_llm_factory.return_value = MagicMock()

				response = ask(message="show customers")

		self.assertEqual(response["status"], "success")
		self.assertIn("rows", response)
		self.assertEqual(response["rows"][0]["name"], "CUST-001")
		self.assertEqual(response["markdown"], "| name |\n| --- |\n| CUST-001 |")
		self.assertIn("session_id", response)

	def test_response_has_meta_field(self):
		fake_response = {
			"status": "success",
			"response_type": "empty",
			"visualization": None,
			"summary": "No results found.",
			"markdown": "No results found.",
			"title": "Result",
			"columns": [],
			"rows": [],
			"meta": {"confidence": 0.9, "has_more": False, "returned_rows": 0},
		}

		with patch("internal_bot.api.chat.get_graph") as mock_get_graph:
			mock_graph = MagicMock()
			mock_graph.invoke.return_value = {"formatted_response": fake_response}
			mock_get_graph.return_value = mock_graph

			with patch("internal_bot.api.chat.get_llm_client") as mock_llm_factory:
				mock_llm_factory.return_value = MagicMock()

				response = ask(message="show something")

		self.assertIn("meta", response)
		self.assertIn("confidence", response["meta"])
		self.assertEqual(response["markdown"], "No results found.")

	def test_visual_payload_passes_through(self):
		fake_response = {
			"status": "success",
			"response_type": "bar_chart",
			"visualization": {
				"kind": "bar",
				"label_key": "territory",
				"value_key": "total_sales",
				"series": [{"name": "Total Sales", "data": [1200, 950]}],
				"categories": ["West", "East"],
				"show_table_toggle": True,
			},
			"summary": "West is highest at 1,200 total sales.",
			"markdown": "- West leads.\n- East follows.",
			"title": "Sales by Territory",
			"columns": ["territory", "total_sales"],
			"rows": [{"territory": "West", "total_sales": 1200}, {"territory": "East", "total_sales": 950}],
			"meta": {"confidence": 0.95, "has_more": False, "returned_rows": 2},
		}

		with patch("internal_bot.api.chat.get_graph") as mock_get_graph:
			mock_graph = MagicMock()
			mock_graph.invoke.return_value = {"formatted_response": fake_response}
			mock_get_graph.return_value = mock_graph

			with patch("internal_bot.api.chat.get_llm_client") as mock_llm_factory:
				mock_llm_factory.return_value = MagicMock()
				response = ask(message="show sales by territory as a chart")

		self.assertEqual(response["response_type"], "bar_chart")
		self.assertEqual(response["visualization"]["kind"], "bar")
		self.assertEqual(response["markdown"], "- West leads.\n- East follows.")

	def test_list_and_history_include_created_session(self):
		session = create_session()
		session_id = session["session_id"]

		frappe.get_doc(
			{
				"doctype": "AI Chat Message",
				"session": session_id,
				"user": "Administrator",
				"role": "user",
				"status": "success",
				"content": "show customers",
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "AI Chat Message",
				"session": session_id,
				"user": "Administrator",
				"role": "assistant",
				"status": "success",
				"content": "Returned 1 row(s).",
				"structured_response": frappe.as_json(
					{
						"status": "success",
						"response_type": "table",
						"title": "Customers",
						"summary": "Returned 1 row across 1 column.",
						"markdown": "| name |\n| --- |\n| CUST-001 |",
						"columns": ["name"],
						"rows": [{"name": "CUST-001"}],
						"visualization": None,
						"meta": {"confidence": 0.9},
					}
				),
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

		session_list = list_sessions()
		history = get_session_history(session_id=session_id)

		self.assertTrue(any(item["session_id"] == session_id for item in session_list["sessions"]))
		self.assertEqual(history["session_id"], session_id)
		self.assertEqual(history["messages"][1]["response_type"], "table")
		self.assertEqual(history["messages"][1]["markdown"], "| name |\n| --- |\n| CUST-001 |")

	def test_history_preserves_debug_context_payload(self):
		session = create_session()
		session_id = session["session_id"]

		frappe.get_doc(
			{
				"doctype": "AI Chat Message",
				"session": session_id,
				"user": "Administrator",
				"role": "assistant",
				"status": "success",
				"content": "Returned 1 row(s).",
				"structured_response": frappe.as_json(
					{
						"status": "success",
						"response_type": "table",
						"title": "Customers",
						"summary": "Returned 1 row across 1 column.",
						"markdown": "Customers loaded.",
						"columns": ["name"],
						"rows": [{"name": "CUST-001"}],
						"visualization": None,
						"debug": {
							"context_window": {
								"history": [{"role": "user", "content": "show customers"}],
								"memory_summary": "Asked for customer data.",
								"last_result_context": "",
								"schema_context": "## Customer",
								"question_context": {
									"raw_message": "show customers",
									"normalized_question": "show customers",
									"follow_up_to_previous_result": False,
									"last_user_question": "",
									"last_non_follow_up_user_question": "",
									"discovered_doctypes": ["Customer"],
									"visualization_preference": "auto",
								},
							},
							"token_usage": {
								"input_tokens": 11,
								"output_tokens": 7,
								"total_tokens": 18,
							},
						},
						"meta": {"confidence": 0.9},
					}
				),
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

		history = get_session_history(session_id=session_id)
		self.assertEqual(history["messages"][0]["debug"]["token_usage"]["total_tokens"], 18)
		self.assertEqual(
			history["messages"][0]["debug"]["context_window"]["schema_context"],
			"## Customer",
		)
