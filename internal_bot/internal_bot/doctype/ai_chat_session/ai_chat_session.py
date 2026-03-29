import frappe
from frappe.model.document import Document


class AIChatSession(Document):
	# begin: auto-generated types
	from frappe.types import DF

	is_active: DF.Check
	last_summarized_at: DF.Datetime | None
	memory_summary: DF.LongText | None
	total_messages: DF.Int
	user: DF.Link
	# end: auto-generated types
	pass
