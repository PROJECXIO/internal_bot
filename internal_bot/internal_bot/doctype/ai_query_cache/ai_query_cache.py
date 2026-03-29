import frappe
from frappe.model.document import Document


class AIQueryCache(Document):
	# begin: auto-generated types
	from frappe.types import DF

	created_by_user: DF.Data | None
	expires_at: DF.Datetime
	generated_sql: DF.LongText
	hit_count: DF.Int
	normalized_question: DF.SmallText
	query_hash: DF.Data
	result_json: DF.LongText
	# end: auto-generated types
	pass
