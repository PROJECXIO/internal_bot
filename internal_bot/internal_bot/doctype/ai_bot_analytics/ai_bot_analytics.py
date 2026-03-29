import frappe
from frappe.model.document import Document


class AIBotAnalytics(Document):
	# begin: auto-generated types
	from frappe.types import DF

	event_type: DF.Literal["ask", "cache_hit", "cache_miss", "blocked", "error", "sql_retry"]
	input_tokens: DF.Int
	message: DF.Link | None
	model: DF.Data | None
	output_tokens: DF.Int
	provider: DF.Data | None
	response_time_ms: DF.Int
	result_row_count: DF.Int
	retries: DF.Int
	session: DF.Link | None
	sql_executed: DF.LongText | None
	status: DF.Literal["", "success", "blocked", "error"] | None
	user: DF.Link
	# end: auto-generated types
	pass
