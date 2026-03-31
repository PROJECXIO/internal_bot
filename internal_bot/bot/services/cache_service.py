"""
Query cache: store/retrieve successful SQL query results by normalized question hash.
"""
import hashlib
import json

import frappe
import frappe.utils


def make_query_hash(normalized_question: str, user: str | None = None) -> str:
	"""
	Return SHA256 hex digest of the (user, normalized_question) pair.

	User-scoping prevents a cached result from User A being served to User B,
	who may have different permissions and therefore different visible data.
	"""
	payload = f"{user or ''}:{normalized_question}"
	return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def lookup_query_cache(query_hash: str) -> dict | None:
	"""
	Return cached result dict if an unexpired record exists, else None.
	Increments hit_count on a cache hit.
	"""
	record = frappe.db.get_value(
		"AI Query Cache",
		{"query_hash": query_hash},
		["name", "result_json", "expires_at", "hit_count"],
		as_dict=True,
	)

	if not record:
		return None

	# Check expiry
	if record.expires_at and frappe.utils.now_datetime() > record.expires_at:
		# Expired — delete and return None
		frappe.delete_doc("AI Query Cache", record.name, ignore_permissions=True, force=True)
		return None

	# Increment hit count
	frappe.db.set_value(
		"AI Query Cache",
		record.name,
		"hit_count",
		(record.hit_count or 0) + 1,
		update_modified=False,
	)

	try:
		return json.loads(record.result_json)
	except Exception:
		return None


def save_query_cache(
	query_hash: str,
	normalized_question: str,
	sql: str,
	result: dict,
	ttl_hours: int = 24,
	user: str | None = None,
) -> None:
	"""
	Insert a new cache record.  If a record with the same hash already exists
	(race condition), silently ignore the duplicate.
	"""
	# Avoid duplicate inserts (can happen under concurrent requests)
	if frappe.db.exists("AI Query Cache", {"query_hash": query_hash}):
		return

	expires_at = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=ttl_hours)

	doc = frappe.get_doc(
		{
			"doctype": "AI Query Cache",
			"query_hash": query_hash,
			"normalized_question": normalized_question,
			"generated_sql": sql,
			"result_json": json.dumps(result, default=str),
			"hit_count": 0,
			"expires_at": expires_at,
			"created_by_user": frappe.session.user,
		}
	)
	try:
		doc.insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		pass


def purge_expired_cache() -> None:
	"""Scheduled daily task: delete all expired cache records."""
	expired = frappe.get_all(
		"AI Query Cache",
		filters={"expires_at": ["<", frappe.utils.now_datetime()]},
		pluck="name",
		limit=500,
	)
	for name in expired:
		frappe.delete_doc("AI Query Cache", name, ignore_permissions=True, force=True)

	if expired:
		frappe.db.commit()
