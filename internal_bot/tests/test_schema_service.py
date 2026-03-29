"""
Level 2 — Integration tests for schema discovery service.

Run with bench:
  bench --site <site> run-tests --app internal_bot --module internal_bot.tests.test_schema_service
"""
import frappe
from frappe.tests.utils import FrappeTestCase

from internal_bot.bot.services.schema import (
	build_schema_context,
	discover_doctypes,
	get_doctype_fields,
	get_doctype_links,
)


class TestSchemaDiscovery(FrappeTestCase):
	def test_discover_customer_doctype(self):
		results = discover_doctypes(["customer"])
		names = [r["name"] for r in results]
		self.assertIn("Customer", names)

	def test_blocked_doctypes_excluded(self):
		results = discover_doctypes(["salary"], blocked_doctypes=["Salary Slip"])
		names = [r["name"] for r in results]
		self.assertNotIn("Salary Slip", names)

	def test_hardcoded_blocked_doctypes_always_excluded(self):
		# Even without explicit blocked list, Salary Slip should be excluded
		results = discover_doctypes(["salary"])
		names = [r["name"] for r in results]
		self.assertNotIn("Salary Slip", names)

	def test_discover_returns_empty_for_no_keywords(self):
		results = discover_doctypes([])
		self.assertEqual(results, [])

	def test_get_doctype_fields_returns_fields(self):
		fields = get_doctype_fields("Customer")
		fieldnames = [f["fieldname"] for f in fields]
		self.assertIn("customer_name", fieldnames)

	def test_get_doctype_fields_excludes_layout_types(self):
		fields = get_doctype_fields("Customer")
		fieldtypes = {f["fieldtype"] for f in fields}
		self.assertNotIn("Section Break", fieldtypes)
		self.assertNotIn("Column Break", fieldtypes)

	def test_get_doctype_links_returns_link_fields(self):
		links = get_doctype_links("Sales Invoice")
		link_to_targets = [lnk["links_to"] for lnk in links]
		self.assertIn("Customer", link_to_targets)

	def test_get_doctype_fields_blocked_raises(self):
		with self.assertRaises(Exception):
			get_doctype_fields("Salary Slip")

	def test_build_schema_context_contains_table_name(self):
		enriched = [{
			"name": "Customer",
			"fields": [{"fieldname": "customer_name", "fieldtype": "Data", "label": "Customer Name"}],
			"links": [],
			"sample_rows": [],
		}]
		ctx = build_schema_context(enriched)
		self.assertIn("tabCustomer", ctx)
		self.assertIn("customer_name", ctx)

	def test_build_schema_context_empty_returns_message(self):
		ctx = build_schema_context([])
		self.assertIn("No relevant", ctx)
