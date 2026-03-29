import frappe


# DocTypes whose data must never be exposed
_ALWAYS_BLOCKED = {
	"Salary Slip",
	"Salary Structure",
	"Salary Structure Assignment",
	"Employee",
	"Leave Application",
	"Attendance",
	"Payroll Entry",
	"Employee Tax Exemption Declaration",
	"Employee Tax Exemption Proof Submission",
	"Appraisal",
	"Employee Advance",
	"Expense Claim",
}


def discover_doctypes(keywords: list, blocked_doctypes: list | None = None) -> list[dict]:
	"""
	Return a list of {name, module, description} dicts for DocTypes whose
	name matches any of the given keywords (case-insensitive substring match).

	Blocked DocTypes (from settings + hardcoded set) are excluded.
	"""
	blocked = set(_ALWAYS_BLOCKED)
	if blocked_doctypes:
		blocked.update(blocked_doctypes)

	if not keywords:
		return []

	# Build OR conditions for keyword matching
	conditions = " OR ".join([f"name LIKE %s" for _ in keywords])
	values = [f"%{kw}%" for kw in keywords]

	rows = frappe.db.sql(
		f"""
		SELECT name, module, description
		FROM `tabDocType`
		WHERE ({conditions})
		  AND issingle = 0
		  AND istable = 0
		  AND hide_toolbar = 0
		ORDER BY name
		LIMIT 20
		""",
		values=values,
		as_dict=True,
	)

	return [r for r in rows if r.name not in blocked]


def get_doctype_fields(doctype: str) -> list[dict]:
	"""
	Return field metadata for a DocType via frappe.get_meta().
	Excludes layout/break fields; returns fieldname, fieldtype, label, options, reqd.
	"""
	_assert_not_blocked(doctype)

	meta = frappe.get_meta(doctype)
	exclude_types = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Fold"}

	result = []
	for f in meta.fields:
		if f.fieldtype in exclude_types:
			continue
		result.append(
			{
				"fieldname": f.fieldname,
				"fieldtype": f.fieldtype,
				"label": f.label or f.fieldname,
				"options": f.options or "",
				"reqd": bool(f.reqd),
			}
		)
	return result


def get_doctype_links(doctype: str) -> list[dict]:
	"""Return link fields in this DocType (fields that reference other DocTypes)."""
	_assert_not_blocked(doctype)

	meta = frappe.get_meta(doctype)
	links = []
	for f in meta.fields:
		if f.fieldtype in ("Link", "Dynamic Link") and f.options:
			links.append(
				{
					"fieldname": f.fieldname,
					"label": f.label or f.fieldname,
					"links_to": f.options,
				}
			)
	return links


def get_sample_rows(doctype: str, limit: int = 3) -> list[dict]:
	"""Return a few sample rows to help the LLM understand value formats."""
	_assert_not_blocked(doctype)

	meta = frappe.get_meta(doctype)
	# Pick a small set of scalar fields for sampling
	sample_fieldnames = []
	for f in meta.fields:
		if f.fieldtype in ("Data", "Int", "Float", "Currency", "Date", "Datetime", "Select", "Link"):
			sample_fieldnames.append(f.fieldname)
		if len(sample_fieldnames) >= 6:
			break

	if not sample_fieldnames:
		return []

	fields_csv = ", ".join(f"`{fn}`" for fn in sample_fieldnames)
	table = f"tab{doctype}"

	try:
		rows = frappe.db.sql(
			f"SELECT {fields_csv} FROM `{table}` LIMIT %s",
			values=(limit,),
			as_dict=True,
		)
		return rows
	except Exception:
		return []


def build_schema_context(discovered: list[dict]) -> str:
	"""
	Build a Markdown-formatted schema context string from a list of
	{name, fields, links, sample_rows} dicts.  Used as LLM prompt context.
	"""
	if not discovered:
		return "No relevant DocTypes found."

	lines = []
	for entry in discovered:
		doctype = entry["name"]
		lines.append(f"## {doctype}  (table: `tab{doctype}`)")

		fields = entry.get("fields", [])
		if fields:
			lines.append("| Field | Type | Label |")
			lines.append("|---|---|---|")
			for f in fields:
				lines.append(f"| `{f['fieldname']}` | {f['fieldtype']} | {f['label']} |")

		links = entry.get("links", [])
		if links:
			lines.append("\nLinks:")
			for lnk in links:
				lines.append(f"- `{lnk['fieldname']}` → {lnk['links_to']}")

		samples = entry.get("sample_rows", [])
		if samples:
			lines.append("\nSample rows (first few):")
			for row in samples:
				lines.append(f"  {dict(row)}")

		lines.append("")

	return "\n".join(lines)


def _assert_not_blocked(doctype: str) -> None:
	if doctype in _ALWAYS_BLOCKED:
		frappe.throw(f"Access to DocType '{doctype}' is restricted.")
