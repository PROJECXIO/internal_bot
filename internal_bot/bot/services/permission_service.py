"""
Permission enforcement — central gate for all query operations.

Four enforcement gates (in order):
1. DocType Access  — frappe.has_permission(doctype, "read")
2. Field Visibility — permlevel-based field filtering (DocPerm table)
3. Row Scope        — user permission conditions injected into analytics SQL
4. Sensitivity Block — _ALWAYS_BLOCKED (hardcoded, defense-in-depth)

INVARIANT: ignore_permissions=True must never appear in query_executor.py
or query_compiler.py.
"""
import frappe

# DocTypes whose data must never be exposed, regardless of Frappe role permissions.
# This is defense-in-depth — the authoritative gate is frappe.has_permission().
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

_EXCLUDE_FIELD_TYPES = frozenset({
    "Section Break", "Column Break", "Tab Break", "HTML", "Button", "Fold",
    "Heading", "HTML Editor",
})


def check_doctype_read_access(doctype: str, user: str) -> bool:
    """
    Return True if the user may read this DocType.
    Checks both the static sensitivity block (Gate 4) and Frappe role
    permissions (Gate 1).  Never raises.
    """
    if doctype in _ALWAYS_BLOCKED:
        return False
    return bool(frappe.has_permission(doctype, ptype="read", user=user, raise_exception=False))


def filter_permitted_doctypes(doctypes: list[str], user: str) -> list[str]:
    """Return only the DocTypes the user is permitted to read."""
    return [dt for dt in doctypes if check_doctype_read_access(dt, user)]


def get_permitted_field_names(doctype: str, user: str) -> list[str]:
    """
    Return the fieldnames the user can read, filtered by permlevel (Gate 2).

    Frappe field-level permissions:
    - permlevel=0 fields are visible to anyone with DocType read access.
    - permlevel>0 fields require the user's role to have explicit access at
      that level, as recorded in the DocPerm table.
    """
    meta = frappe.get_meta(doctype)
    user_roles = frappe.get_roles(user)

    accessible_permlevels = {0}  # level-0 is always accessible with read permission

    if user_roles:
        high_perm_records = frappe.db.get_all(
            "DocPerm",
            filters={
                "parent": doctype,
                "permlevel": [">", 0],
                "read": 1,
                "role": ["in", user_roles],
            },
            pluck="permlevel",
        )
        accessible_permlevels.update(high_perm_records)

    return [
        f.fieldname
        for f in meta.fields
        if f.fieldtype not in _EXCLUDE_FIELD_TYPES
        and (f.permlevel or 0) in accessible_permlevels
    ]


def assert_fields_permitted(doctype: str, fieldnames: list[str], user: str) -> list[str]:
    """
    Return only the fieldnames the user is permitted to read.
    Silently drops disallowed fields.
    Raises frappe.PermissionError if no permitted fields remain after filtering.
    """
    permitted = set(get_permitted_field_names(doctype, user))
    permitted.add("name")  # primary key is always accessible

    filtered = [fn for fn in fieldnames if fn in permitted]

    if not filtered:
        frappe.throw(
            f"No permitted fields remain after permission filter for DocType '{doctype}'.",
            frappe.PermissionError,
        )

    return filtered


def get_row_scope_condition(doctype: str, user: str) -> str | None:
    """
    Return the SQL WHERE fragment encoding the user's row-scope permissions
    (Frappe User Permissions).  Returns None if no restrictions apply.

    Uses Frappe's DatabaseQuery internals to generate the match condition.
    If Frappe internals change and this breaks, it degrades gracefully by
    returning None — analytics queries will run without row-scope filtering.

    # FIXME: monitor Frappe upgrades — DatabaseQuery.build_match_conditions()
    # is an internal API. Breakage is surfaced via frappe.log_error so it is
    # visible in the Error Log, but analytics will silently lose row-scope
    # filtering until this is fixed.
    """
    try:
        from frappe.model.db_query import DatabaseQuery  # noqa: PLC0415

        query = DatabaseQuery(doctype, user=user)
        condition = query.build_match_conditions()
        return condition if condition else None
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            "permission_service.get_row_scope_condition failed — "
            "analytics query running without row-scope filtering",
        )
        return None
