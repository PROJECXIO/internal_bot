import frappe
from frappe.model.document import Document


class AIBaselineRun(Document):
	# begin: auto-generated types
	from frappe.types import DF

	average_retries: DF.Float
	average_timing_ms: DF.Float
	blocked_count: DF.Int
	clarification_count: DF.Int
	completed_queries: DF.Int
	duration_ms: DF.Int
	error_count: DF.Int
	error_detail: DF.LongText | None
	finished_at: DF.Datetime | None
	fixture_name: DF.Data
	greeting_count: DF.Int
	job_id: DF.Data | None
	no_row_count: DF.Int
	report_json: DF.LongText | None
	run_user: DF.Link | None
	started_at: DF.Datetime | None
	status: DF.Literal["Queued", "Running", "Completed", "Failed"]
	status_mismatch_count: DF.Int
	success_count: DF.Int
	summary_json: DF.LongText | None
	total_queries: DF.Int
	# end: auto-generated types
	pass
