import frappe


def get_user_context(user: str) -> dict:
	"""Return basic user context: full_name, roles, timezone."""
	doc = frappe.get_doc("User", user)
	roles = frappe.get_roles(user)
	return {
		"user": user,
		"full_name": doc.full_name or user,
		"roles": roles,
		"timezone": doc.time_zone or frappe.utils.get_system_timezone(),
	}
