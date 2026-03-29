"""
Level 2 — Integration tests for cache_service.

Run with bench:
  bench --site <site> run-tests --app internal_bot --module internal_bot.tests.test_cache_service
"""
import frappe
from frappe.tests.utils import FrappeTestCase

from internal_bot.bot.services.cache_service import (
	lookup_query_cache,
	make_query_hash,
	purge_expired_cache,
	save_query_cache,
)


class TestQueryCacheService(FrappeTestCase):
	def tearDown(self):
		# Clean up any test cache records
		frappe.db.delete("AI Query Cache", {"created_by_user": "test@internal-bot.test"})
		frappe.db.commit()

	def _seed_user(self):
		frappe.session.user = "test@internal-bot.test"

	def test_make_query_hash_deterministic(self):
		h1 = make_query_hash("show all customers")
		h2 = make_query_hash("show all customers")
		self.assertEqual(h1, h2)

	def test_make_query_hash_different_for_different_inputs(self):
		h1 = make_query_hash("show all customers")
		h2 = make_query_hash("show all suppliers")
		self.assertNotEqual(h1, h2)

	def test_lookup_returns_none_on_miss(self):
		result = lookup_query_cache("nonexistent_hash_xyz123")
		self.assertIsNone(result)

	def test_save_and_lookup_roundtrip(self):
		question = "test cache roundtrip question"
		qhash = make_query_hash(question)
		payload = {"status": "success", "rows": [{"name": "CUST-001"}]}

		save_query_cache(
			query_hash=qhash,
			normalized_question=question,
			sql="SELECT name FROM `tabCustomer` LIMIT 1",
			result=payload,
			ttl_hours=1,
		)
		frappe.db.commit()

		retrieved = lookup_query_cache(qhash)
		self.assertIsNotNone(retrieved)
		self.assertEqual(retrieved["status"], "success")
		self.assertEqual(retrieved["rows"][0]["name"], "CUST-001")

	def test_hit_count_increments(self):
		question = "test hit count question"
		qhash = make_query_hash(question)
		save_query_cache(
			query_hash=qhash,
			normalized_question=question,
			sql="SELECT 1",
			result={"status": "success"},
			ttl_hours=1,
		)
		frappe.db.commit()

		# First hit
		lookup_query_cache(qhash)
		frappe.db.commit()
		count1 = frappe.db.get_value("AI Query Cache", {"query_hash": qhash}, "hit_count")

		# Second hit
		lookup_query_cache(qhash)
		frappe.db.commit()
		count2 = frappe.db.get_value("AI Query Cache", {"query_hash": qhash}, "hit_count")

		self.assertGreater(count2, count1)

	def test_expired_cache_returns_none(self):
		import frappe.utils
		question = "test expired cache"
		qhash = make_query_hash(question)

		# Insert a record that expired yesterday
		doc = frappe.get_doc({
			"doctype": "AI Query Cache",
			"query_hash": qhash,
			"normalized_question": question,
			"generated_sql": "SELECT 1",
			"result_json": '{"status": "success"}',
			"hit_count": 0,
			"expires_at": frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-1),
			"created_by_user": "test@internal-bot.test",
		})
		doc.insert(ignore_permissions=True)
		frappe.db.commit()

		result = lookup_query_cache(qhash)
		self.assertIsNone(result)

	def test_duplicate_save_is_idempotent(self):
		question = "test duplicate save"
		qhash = make_query_hash(question)
		save_query_cache(qhash, question, "SELECT 1", {"status": "success"}, 1)
		frappe.db.commit()
		# Second save should not raise
		save_query_cache(qhash, question, "SELECT 1", {"status": "success"}, 1)
		frappe.db.commit()

		count = frappe.db.count("AI Query Cache", {"query_hash": qhash})
		self.assertEqual(count, 1)
