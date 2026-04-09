import frappe

from internal_bot.bot.services import permission_service

# Re-export for any code that imported _ALWAYS_BLOCKED from here
from internal_bot.bot.services.permission_service import _ALWAYS_BLOCKED  # noqa: F401


def discover_doctypes(keywords: list, blocked_doctypes: list | None = None) -> list[dict]:
    """
    Return a list of {name, module, description} dicts for DocTypes whose
    name matches any of the given keywords (case-insensitive substring match).

    Blocked DocTypes (from settings + hardcoded set) are excluded.
    This function does NOT enforce Frappe role permissions — use
    discover_permitted_doctypes() for permission-gated discovery.
    """
    blocked = set(_ALWAYS_BLOCKED)
    if blocked_doctypes:
        blocked.update(blocked_doctypes)

    if not keywords:
        return []

    conditions = " OR ".join(["name LIKE %s" for _ in keywords])
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


def discover_permitted_doctypes(
    keywords: list,
    user: str,
    blocked_doctypes: list | None = None,
) -> list[dict]:
    """
    Like discover_doctypes but additionally enforces Frappe read permission
    for the given user (Gate 1).  Only DocTypes the user can actually read
    are returned — nothing is shown to the LLM that the user cannot access.
    """
    rows = discover_doctypes(keywords, blocked_doctypes)
    permitted_names = set(
        permission_service.filter_permitted_doctypes([r["name"] for r in rows], user)
    )
    return [r for r in rows if r["name"] in permitted_names]


def get_doctype_fields(doctype: str, user: str | None = None) -> list[dict]:
    """
    Return field metadata for a DocType via frappe.get_meta().
    Excludes layout/break fields; returns fieldname, fieldtype, label, options, reqd.

    If user is provided, also strips fields the user cannot see due to permlevel
    restrictions (Gate 2).  The LLM never learns a field exists if the user
    cannot see it.
    """
    meta = frappe.get_meta(doctype)
    exclude_types = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Fold"}

    # Gate 2: get permitted fieldnames if user provided
    permitted_names: set[str] | None = None
    if user:
        permitted_names = set(permission_service.get_permitted_field_names(doctype, user))

    result = []
    for f in meta.fields:
        if f.fieldtype in exclude_types:
            continue
        if permitted_names is not None and f.fieldname not in permitted_names:
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
    # Prepend standard system fields that aren't returned by meta.fields
    result.insert(0, {
        "fieldname": "docstatus",
        "fieldtype": "Int",
        "label": "Document Status (0=Draft, 1=Submitted, 2=Cancelled)",
        "options": "",
        "reqd": False,
    })
    return result


def get_doctype_links(doctype: str) -> list[dict]:
    """Return link fields in this DocType (fields that reference other DocTypes)."""
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


def get_child_tables(doctype: str, user: str | None = None) -> list[dict]:
    """Return the primary child tables for a parent DocType with their fields.

    Each entry: {name, fieldname, fields} where fieldname is the Table field
    on the parent that holds this child table.
    """
    meta = frappe.get_meta(doctype)
    children = []
    for f in meta.fields:
        if f.fieldtype != "Table" or not f.options:
            continue
        try:
            child_fields = get_doctype_fields(f.options, user=user)
        except Exception:
            child_fields = []
        children.append({
            "name": f.options,
            "fieldname": f.fieldname,
            "fields": child_fields,
        })
    return children


def build_schema_context(discovered: list[dict]) -> str:
    """
    Build a Markdown-formatted schema context string from a list of
    {name, fields, links} dicts.  Used as LLM prompt context.

    Sample rows are intentionally excluded (privacy — they could expose
    real business data to the LLM).  Field type and label convey enough
    context for value format inference.
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

        child_tables = entry.get("child_tables", [])
        for child in child_tables:
            child_name = child["name"]
            child_fields = child.get("fields", [])
            if child_fields:
                lines.append(f"\n### Child: {child_name}  (table: `tab{child_name}`, join via parent)")
                lines.append("| Field | Type | Label |")
                lines.append("|---|---|---|")
                for f in child_fields:
                    lines.append(f"| `{f['fieldname']}` | {f['fieldtype']} | {f['label']} |")

        lines.append("")

    return "\n".join(lines)
