import frappe
from frappe.model.document import Document


class AIChatMessage(Document):
	# begin: auto-generated types
	from frappe.types import DF

	cache_hit: DF.Check
	content: DF.LongText
	discovered_entities: DF.SmallText | None
	error_detail: DF.SmallText | None
	generated_sql: DF.LongText | None
	llm_model: DF.Data | None
	llm_provider: DF.Data | None
	node_trace: DF.LongText | None
	normalized_question: DF.SmallText | None
	response_time_ms: DF.Int
	retries: DF.Int
	role: DF.Literal["user", "assistant", "system"]
	session: DF.Link
	status: DF.Literal["success", "clarification_needed", "blocked", "error", "greeting"]
	structured_response: DF.LongText | None
	user: DF.Link
	validated_sql: DF.LongText | None
	# end: auto-generated types
	pass
