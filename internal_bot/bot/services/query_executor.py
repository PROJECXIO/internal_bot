"""
Query execution dispatcher.

Routes validated QueryIntent dicts to the appropriate execution path:
  - List mode    → frappe.get_list() (permission-enforced automatically)
  - Analytics mode → query_compiler → parameterised frappe.db.sql()

This module is the only place where user-facing data is fetched.
ignore_permissions=True must never appear here.
"""
import frappe

from internal_bot.bot.services import permission_service, query_compiler


def execute_list_query(intent: dict, user: str, max_rows: int) -> list[dict]:
    """
    Execute a list-mode intent using frappe.get_list().

    frappe.get_list() with ignore_permissions=False automatically enforces:
    - DocType-level read permissions (Gate 1)
    - Field-level permissions (Gate 2)
    - User Permissions / row-scope (Gate 3)
    """
    doctype = intent["doctype"]
    requested_fields = intent.get("fields") or ["name"]

    # Gate 2: silently drop fields the user cannot see; raise if none remain
    permitted_fields = permission_service.assert_fields_permitted(
        doctype, requested_fields, user
    )

    # Ensure "name" is always included
    if "name" not in permitted_fields:
        permitted_fields = ["name"] + permitted_fields

    limit = min(int(intent.get("limit", max_rows)), max_rows)
    order_by = intent.get("order_by") or "creation desc"
    filters = intent.get("filters") or []

    rows = frappe.get_list(
        doctype,
        fields=permitted_fields,
        filters=filters,
        order_by=order_by,
        limit=limit,
        ignore_permissions=False,  # CRITICAL: never bypass
    )
    return [dict(r) for r in rows]


def execute_analytics_query(
    intent: dict, user: str, max_rows: int
) -> tuple[list[dict], str]:
    """
    Execute an analytics-mode intent via the SQL compiler.

    Returns (rows, compiled_sql_for_logging).
    The compiled_sql is for audit/debug purposes only — it is stored in
    state and logged, but never returned to the client.
    """
    sql, params = query_compiler.compile_analytics_intent(intent, user, max_rows)
    rows = frappe.db.sql(sql, values=params, as_dict=True)
    return [dict(r) for r in rows[:max_rows]], sql


def execute_query_intent(
    intent: dict, user: str, max_rows: int
) -> tuple[list[dict], str | None]:
    """
    Top-level dispatcher.  Returns (rows, compiled_sql_or_None).

    compiled_sql is populated only for analytics mode.
    """
    mode = intent.get("mode")
    if mode == "list":
        rows = execute_list_query(intent, user, max_rows)
        return rows, None
    elif mode == "analytics":
        rows, sql = execute_analytics_query(intent, user, max_rows)
        return rows, sql
    else:
        raise ValueError(
            f"Unknown query mode: '{mode}'. Must be 'list' or 'analytics'."
        )
