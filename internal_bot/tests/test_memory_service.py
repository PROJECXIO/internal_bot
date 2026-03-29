"""
Level 2 — Integration tests for memory service.

Run with bench:
  bench --site <site> run-tests --app internal_bot --module internal_bot.tests.test_memory_service
"""
import frappe
from frappe.tests.utils import FrappeTestCase

from internal_bot.bot.services.memory import load_chat_memory, save_message


_TEST_USER = "test-memory@internal-bot.test"
_TEST_SESSION = "AICS-TEST-MEMORY"


class TestMemoryService(FrappeTestCase):
	def setUp(self):
		# Ensure a clean test session exists
		if frappe.db.exists("AI Chat Session", _TEST_SESSION):
			frappe.db.delete("AI Chat Message", {"session": _TEST_SESSION})
			frappe.db.delete("AI Chat Session", {"name": _TEST_SESSION})
			frappe.db.commit()

		frappe.get_doc({
			"doctype": "AI Chat Session",
			"name": _TEST_SESSION,
			"user": "Administrator",  # link to a real user
			"is_active": 1,
			"total_messages": 0,
		}).insert(ignore_permissions=True)
		frappe.db.commit()

		frappe.session.user = "Administrator"

	def tearDown(self):
		frappe.db.delete("AI Chat Message", {"session": _TEST_SESSION})
		frappe.db.delete("AI Chat Session", {"name": _TEST_SESSION})
		frappe.db.commit()

	def test_load_empty_session(self):
		mem = load_chat_memory(_TEST_SESSION, window_size=10)
		self.assertEqual(mem["messages"], [])
		self.assertEqual(mem["summary"], "")
		self.assertEqual(mem["total_messages"], 0)

	def test_save_and_load_message(self):
		save_message(_TEST_SESSION, "user", "show me all customers", status="success")
		frappe.db.commit()

		mem = load_chat_memory(_TEST_SESSION, window_size=10)
		self.assertEqual(len(mem["messages"]), 1)
		self.assertEqual(mem["messages"][0]["role"], "user")
		self.assertEqual(mem["messages"][0]["content"], "show me all customers")

	def test_save_assistant_message(self):
		save_message(_TEST_SESSION, "user", "question", status="success")
		save_message(_TEST_SESSION, "assistant", "answer", status="success")
		frappe.db.commit()

		mem = load_chat_memory(_TEST_SESSION, window_size=10)
		self.assertEqual(len(mem["messages"]), 2)
		roles = [m["role"] for m in mem["messages"]]
		self.assertIn("user", roles)
		self.assertIn("assistant", roles)

	def test_window_size_limits_messages(self):
		for i in range(5):
			save_message(_TEST_SESSION, "user", f"question {i}", status="success")
		frappe.db.commit()

		mem = load_chat_memory(_TEST_SESSION, window_size=3)
		self.assertLessEqual(len(mem["messages"]), 3)

	def test_total_messages_increments(self):
		save_message(_TEST_SESSION, "user", "msg1", status="success")
		frappe.db.commit()
		save_message(_TEST_SESSION, "assistant", "ans1", status="success")
		frappe.db.commit()

		total = frappe.db.get_value("AI Chat Session", _TEST_SESSION, "total_messages")
		self.assertEqual(total, 2)

	def test_save_message_with_debug_fields(self):
		name = save_message(
			_TEST_SESSION,
			"assistant",
			"result",
			status="success",
			normalized_question="show customers",
			generated_sql="SELECT name FROM `tabCustomer` LIMIT 10",
			cache_hit=0,
			retries=1,
			response_time_ms=350,
		)
		frappe.db.commit()

		msg = frappe.get_doc("AI Chat Message", name)
		self.assertEqual(msg.normalized_question, "show customers")
		self.assertEqual(msg.retries, 1)
		self.assertEqual(msg.response_time_ms, 350)
