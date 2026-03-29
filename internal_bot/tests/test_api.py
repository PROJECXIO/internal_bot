"""
Level 4 — API smoke tests.

Run with bench:
  bench --site <site> run-tests --app internal_bot --module internal_bot.tests.test_api
"""
import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import MagicMock, patch

from internal_bot.api.chat import ask, _get_or_create_session


class TestChatAPI(FrappeTestCase):
	def setUp(self):
		frappe.session.user = "Administrator"

	def tearDown(self):
		frappe.db.delete("AI Chat Message", {"session": "Administrator"})
		if frappe.db.exists("AI Chat Session", "Administrator"):
			frappe.db.set_value("AI Chat Session", "Administrator", "total_messages", 0)
		frappe.db.commit()

	def test_empty_message_returns_error(self):
		response = ask(message="", debug=False)
		self.assertEqual(response["status"], "error")
		self.assertIn("empty", response["reason"].lower())

	def test_whitespace_only_message_returns_error(self):
		response = ask(message="   ", debug=False)
		self.assertEqual(response["status"], "error")

	def test_session_created_for_user(self):
		_get_or_create_session("Administrator")
		frappe.db.commit()
		self.assertTrue(frappe.db.exists("AI Chat Session", "Administrator"))

	def test_session_creation_is_idempotent(self):
		_get_or_create_session("Administrator")
		frappe.db.commit()
		_get_or_create_session("Administrator")
		frappe.db.commit()
		count = frappe.db.count("AI Chat Session", {"name": "Administrator"})
		self.assertEqual(count, 1)

	def test_ask_requires_login(self):
		frappe.session.user = "Guest"
		with self.assertRaises(frappe.exceptions.AuthenticationError):
			ask(message="show customers")

	def test_ask_with_mock_graph_returns_valid_structure(self):
		"""Smoke test: mock the graph and verify the API wraps the response correctly."""
		fake_response = {
			"status": "success",
			"response_type": "table",
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

	def test_response_has_meta_field(self):
		fake_response = {
			"status": "success",
			"response_type": "empty",
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
