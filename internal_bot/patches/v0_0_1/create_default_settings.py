"""
Patch: create_default_settings
Creates the AI Provider Settings singleton with safe default values
if it does not already exist.
"""
import frappe


def execute():
	# For Single DocTypes, check if any value has been set already
	existing_model = frappe.db.get_single_value("AI Provider Settings", "model")
	if existing_model:
		return  # Already seeded

	# Single DocTypes are updated via frappe.db.set_value or by saving the doc
	doc = frappe.get_doc("AI Provider Settings")
	doc.update(
		{
			"provider": "OpenAI",
			"model": "gpt-4o",
			"api_key": "",  # Must be configured by System Manager via the Settings form
			"max_tokens": 2000,
			"temperature": 0.0,
			"request_timeout": 30,
			"memory_window": 10,
			"summary_threshold": 20,
			"enable_cache": 1,
			"cache_ttl_hours": 24,
			"max_result_rows": 100,
			"blocked_doctypes": (
				"Salary Slip\n"
				"Salary Structure\n"
				"Salary Structure Assignment\n"
				"Payroll Entry\n"
				"Employee Tax Exemption Declaration\n"
				"Employee Tax Exemption Proof Submission"
			),
		}
	)
	doc.save(ignore_permissions=True, ignore_mandatory=True)
	frappe.db.commit()
