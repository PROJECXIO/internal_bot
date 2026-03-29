"""
Analytics: record every bot interaction for monitoring and debugging.
All writes are wrapped in try/except so analytics never block a response.
"""
import frappe


def save_analytics(
	user: str,
	event_type: str,
	session: str | None = None,
	message: str | None = None,
	status: str | None = None,
	provider: str | None = None,
	model: str | None = None,
	input_tokens: int = 0,
	output_tokens: int = 0,
	response_time_ms: int = 0,
	retries: int = 0,
	sql_executed: str | None = None,
	result_row_count: int = 0,
) -> None:
	"""
	Insert an AI Bot Analytics record.
	Silently swallows all exceptions — analytics must never break the user response.
	"""
	try:
		doc = frappe.get_doc(
			{
				"doctype": "AI Bot Analytics",
				"user": user,
				"session": session,
				"message": message,
				"event_type": event_type,
				"status": status or "",
				"provider": provider or "",
				"model": model or "",
				"input_tokens": input_tokens or 0,
				"output_tokens": output_tokens or 0,
				"response_time_ms": response_time_ms or 0,
				"retries": retries or 0,
				"sql_executed": sql_executed or "",
				"result_row_count": result_row_count or 0,
			}
		)
		doc.insert(ignore_permissions=True)
	except Exception:
		pass  # Analytics must never break the user-facing response
