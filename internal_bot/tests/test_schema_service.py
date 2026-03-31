"""
Level 2 — Integration tests for schema discovery service.

Run with bench:
  bench --site <site> run-tests --app internal_bot --module internal_bot.tests.test_schema_service
"""
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from internal_bot.bot.services.schema import (
	build_schema_context,
	discover_doctypes,
	discover_permitted_doctypes,
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

	def test_get_doctype_fields_with_user_strips_permitted(self):
		"""When user is provided, only fields in the permitted set are returned."""
		with patch(
			"internal_bot.bot.services.schema.permission_service.get_permitted_field_names"
		) as mock_permitted:
			# Only allow one field
			mock_permitted.return_value = ["customer_name"]
			fields = get_doctype_fields("Customer", user="test@example.com")

		fieldnames = [f["fieldname"] for f in fields]
		self.assertIn("customer_name", fieldnames)
		# Other fields should be stripped
		self.assertNotIn("customer_group", fieldnames)

	def test_get_doctype_fields_without_user_returns_all(self):
		"""Without user, all non-layout fields are returned (no permission filtering)."""
		fields_no_user = get_doctype_fields("Customer")
		fields_all_fieldnames = {f["fieldname"] for f in fields_no_user}
		self.assertIn("customer_name", fields_all_fieldnames)
		self.assertIn("customer_group", fields_all_fieldnames)

	def test_build_schema_context_contains_table_name(self):
		enriched = [{
			"name": "Customer",
			"fields": [{"fieldname": "customer_name", "fieldtype": "Data", "label": "Customer Name"}],
			"links": [],
		}]
		ctx = build_schema_context(enriched)
		self.assertIn("tabCustomer", ctx)
		self.assertIn("customer_name", ctx)

	def test_build_schema_context_empty_returns_message(self):
		ctx = build_schema_context([])
		self.assertIn("No relevant", ctx)

	def test_build_schema_context_does_not_include_sample_rows(self):
		"""Sample rows must not appear in schema context (privacy gate)."""
		enriched = [{
			"name": "Customer",
			"fields": [{"fieldname": "customer_name", "fieldtype": "Data", "label": "Customer Name"}],
			"links": [],
		}]
		ctx = build_schema_context(enriched)
		self.assertNotIn("Sample rows", ctx)
		self.assertNotIn("sample_rows", ctx)

	def test_discover_permitted_doctypes_excludes_inaccessible(self):
		"""discover_permitted_doctypes should exclude DocTypes not in filter_permitted result."""
		with patch(
			"internal_bot.bot.services.schema.permission_service.filter_permitted_doctypes"
		) as mock_filter:
			mock_filter.return_value = []  # user has access to nothing
			results = discover_permitted_doctypes(["customer"], user="limited@example.com")

		self.assertEqual(results, [])

	def test_discover_permitted_doctypes_keeps_accessible(self):
		"""discover_permitted_doctypes should keep DocTypes the user can access."""
		with patch(
			"internal_bot.bot.services.schema.permission_service.filter_permitted_doctypes"
		) as mock_filter:
			mock_filter.side_effect = lambda names, user: names  # allow all
			results = discover_permitted_doctypes(["customer"], user="admin@example.com")

		names = [r["name"] for r in results]
		self.assertIn("Customer", names)
