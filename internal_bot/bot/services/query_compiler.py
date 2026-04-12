"""
Analytics SQL compiler.

Translates a validated AnalyticsIntent dict into permission-scoped,
parameterised SQL.  This is the ONLY place in the new architecture where
SELECT SQL is assembled for analytics queries.

Key invariants:
- All table/field names come from the validated intent, never from
  free-form LLM text.
- All filter values are parameterised (%s) — no string interpolation.
- Row-scope conditions (User Permissions) are injected here, not by the LLM.
- ignore_permissions=True must never appear in this module.
"""
import datetime
import re

import frappe
import frappe.utils

from internal_bot.bot.services import permission_service

_ALLOWED_FUNCS = frozenset({"SUM", "COUNT", "AVG", "MAX", "MIN", "COUNT_DISTINCT"})
_DATE_EXTRACT_RE = re.compile(r"^(YEAR_MONTH|YEAR|MONTH|DAY|WEEK|DATE)\((.+)\)$", re.IGNORECASE)
_ALLOWED_OPERATORS = frozenset({
    "=", "!=", ">", "<", ">=", "<=", "like", "in", "not in", "between", "is",
})
_STANDARD_CHILD_FIELDS = {"parent", "parenttype", "parentfield", "idx"}


def compile_analytics_intent(
    intent: dict, user: str, max_rows: int = 100
) -> tuple[str, list]:
    """
    Compile an AnalyticsIntent dict into (parameterised_sql, params_list).

    Raises:
        frappe.PermissionError — user cannot read a required DocType or field
        ValueError             — invalid operator, func, join type, or date preset
    """
    primary = intent["primary_doctype"]

    # Gate 1: primary DocType access
    if not permission_service.check_doctype_read_access(primary, user):
        frappe.throw(f"Access denied to DocType '{primary}'.", frappe.PermissionError)

    # Gate 1: join DocType access
    for join in intent.get("joins", []):
        _validate_join(join, primary)
        child_dt = join["child_doctype"]
        if not _is_child_table(child_dt):
            # Independent DocType joined via Link field — needs separate permission check
            if not permission_service.check_doctype_read_access(child_dt, user):
                frappe.throw(
                    f"Access denied to DocType '{child_dt}'.", frappe.PermissionError
                )

    # Gate 2: get permitted fields for the primary DocType
    permitted_fields = set(permission_service.get_permitted_field_names(primary, user))
    permitted_fields.add("name")  # primary key always accessible
    join_field_permissions = _get_join_field_permissions(intent.get("joins", []), user)

    # Ranked primary dimension mode — generates a CTE-based query.
    # Used for "top-X-and-their-Y" patterns, e.g. "top items by purchase amount
    # and their suppliers". The CTE ranks the first dimension by the first metric's
    # total, then the main query shows all secondary dimensions for those top items.
    if (
        intent.get("rank_by_primary_dimension")
        and len(intent.get("dimensions", [])) >= 2
        and intent.get("metrics")
    ):
        return _compile_ranked_analytics_intent(
            intent, primary, user, max_rows, permitted_fields, join_field_permissions
        )

    select_parts = []
    group_by_parts = []
    metric_aliases = []
    dimension_aliases = []

    # Dimensions → SELECT + GROUP BY
    for dim in intent.get("dimensions", []):
        # Support date extraction: YEAR(fieldname), MONTH(fieldname), etc.
        date_match = _DATE_EXTRACT_RE.match(dim)
        if date_match:
            func, field = date_match.group(1).upper(), date_match.group(2).strip()
            field_expr, _ = _resolve_field_reference(
                field, primary, permitted_fields, join_field_permissions
            )
            expr = (
                f"DATE_FORMAT({field_expr}, '%%Y-%%m')"
                if func == "YEAR_MONTH"
                else f"{func}({field_expr})"
            )
            select_parts.append(f"{expr} AS `{dim}`")
            group_by_parts.append(expr)
            dimension_aliases.append(dim)
        else:
            dim_expr, dim_alias = _resolve_field_reference(
                dim, primary, permitted_fields, join_field_permissions
            )
            select_parts.append(f"{dim_expr} AS `{dim_alias}`")
            group_by_parts.append(dim_expr)
            dimension_aliases.append(dim_alias)

    # Metrics → SELECT
    for metric in intent.get("metrics", []):
        func = metric["func"].upper()
        field = metric["field"]
        alias = metric["alias"]

        if func not in _ALLOWED_FUNCS:
            raise ValueError(f"Unsupported aggregate function: '{func}'")

        if func == "COUNT_DISTINCT":
            if field == "*":
                expr = "COUNT(DISTINCT *)"
            else:
                field_expr, _ = _resolve_field_reference(
                    field, primary, permitted_fields, join_field_permissions
                )
                expr = f"COUNT(DISTINCT {field_expr})"
        elif func == "COUNT" and field == "*":
            expr = "COUNT(*)"
        else:
            field_expr, _ = _resolve_field_reference(
                field, primary, permitted_fields, join_field_permissions
            )
            expr = f"{func}({field_expr})"

        select_parts.append(f"{expr} AS `{alias}`")
        metric_aliases.append(alias)

    if not select_parts:
        raise ValueError("AnalyticsIntent must have at least one dimension or metric.")

    # FROM + JOINs
    sql = f"SELECT {', '.join(select_parts)}\n"
    sql += _build_from_joins_sql(primary, intent.get("joins", []))

    # WHERE + params
    where_parts, params = _build_where_clause(
        intent, primary, permitted_fields, join_field_permissions, user
    )
    if where_parts:
        sql += "\nWHERE " + "\n  AND ".join(where_parts)

    # GROUP BY — only when aggregating (i.e. there are metrics).
    # If there are only dimensions and no metrics, we want a flat JOIN result
    # (e.g. list all Sales Invoice Items), so skip GROUP BY to avoid deduplication.
    if group_by_parts and metric_aliases:
        sql += "\nGROUP BY " + ", ".join(group_by_parts)

    # ORDER BY (validated — only permitted fields or metric aliases)
    order_by = intent.get("order_by")
    if order_by:
        order_by = _validate_order_by(order_by, permitted_fields, metric_aliases + dimension_aliases)
    if order_by:
        sql += f"\nORDER BY {order_by}"

    # LIMIT (hard cap)
    limit = min(int(intent.get("limit", max_rows)), max_rows)
    sql += "\nLIMIT %s"
    params.append(limit)

    return sql, params


def _compile_ranked_analytics_intent(
    intent: dict,
    primary: str,
    user: str,
    max_rows: int,
    permitted_fields: set,
    join_field_permissions: dict,
) -> tuple[str, list]:
    """
    Generate a CTE-based query for "top-X-and-their-Y" patterns.

    Example: "top items by purchase amount and their suppliers"

    The CTE ranks the first dimension (e.g. item_code) by the first metric's
    aggregate total across ALL values of the secondary dimensions. The main query
    then shows ALL secondary dimensions for only those top-ranked items, ordered
    by the CTE rank so items always appear grouped by their rank.

    This correctly answers questions like:
      - "top purchased items and their suppliers"
      - "top selling items and who sold them"
      - "top customers and their sales reps"

    Requires intent["rank_by_primary_dimension"] = true, at least 2 dimensions,
    and at least 1 metric.
    """
    dimensions = intent.get("dimensions", [])
    metrics = intent.get("metrics", [])
    limit = min(int(intent.get("limit", max_rows)), max_rows)

    # ── Resolve first dimension (the one to rank by) ──────────────────
    primary_dim = dimensions[0]
    date_match = _DATE_EXTRACT_RE.match(primary_dim)
    if date_match:
        func, field = date_match.group(1).upper(), date_match.group(2).strip()
        field_expr, _ = _resolve_field_reference(
            field, primary, permitted_fields, join_field_permissions
        )
        primary_dim_expr = (
            f"DATE_FORMAT({field_expr}, '%%Y-%%m')"
            if func == "YEAR_MONTH"
            else f"{func}({field_expr})"
        )
    else:
        primary_dim_expr, _ = _resolve_field_reference(
            primary_dim, primary, permitted_fields, join_field_permissions
        )

    # CTE column alias is the bare fieldname (e.g. "item_code")
    _, primary_dim_fieldname = _split_field_reference(primary_dim)

    # ── Resolve first metric (used to rank in the CTE) ────────────────
    first_metric = metrics[0]
    mfunc = first_metric["func"].upper()
    mfield = first_metric["field"]
    if mfunc not in _ALLOWED_FUNCS:
        raise ValueError(f"Unsupported aggregate function: '{mfunc}'")
    if mfunc == "COUNT_DISTINCT":
        if mfield == "*":
            metric_agg_expr = "COUNT(DISTINCT *)"
        else:
            mf_expr, _ = _resolve_field_reference(
                mfield, primary, permitted_fields, join_field_permissions
            )
            metric_agg_expr = f"COUNT(DISTINCT {mf_expr})"
    elif mfunc == "COUNT" and mfield == "*":
        metric_agg_expr = "COUNT(*)"
    else:
        mf_expr, _ = _resolve_field_reference(
            mfield, primary, permitted_fields, join_field_permissions
        )
        metric_agg_expr = f"{mfunc}({mf_expr})"

    # ── FROM + JOINs (shared between CTE and main query) ─────────────
    from_joins_sql = _build_from_joins_sql(primary, intent.get("joins", []))

    # ── WHERE (shared between CTE and main query; params duplicated) ──
    where_parts, where_params = _build_where_clause(
        intent, primary, permitted_fields, join_field_permissions, user
    )
    where_sql = ("\nWHERE " + "\n  AND ".join(where_parts)) if where_parts else ""

    # ── CTE: rank first dimension by first metric ─────────────────────
    cte = (
        f"WITH `_ranked_primary` AS (\n"
        f"  SELECT {primary_dim_expr} AS `{primary_dim_fieldname}`,\n"
        f"         {metric_agg_expr} AS `_rank_val`\n"
        f"  {from_joins_sql}"
        f"  {where_sql}\n"
        f"  GROUP BY {primary_dim_expr}\n"
        f"  ORDER BY `_rank_val` DESC\n"
        f"  LIMIT %s\n"
        f")"
    )
    cte_params = list(where_params) + [limit]

    # ── Main query: all dimensions + metrics, filtered to top items ───
    select_parts = []
    group_by_parts = []
    metric_aliases = []
    dimension_aliases = []

    for dim in dimensions:
        d_date_match = _DATE_EXTRACT_RE.match(dim)
        if d_date_match:
            func, field = d_date_match.group(1).upper(), d_date_match.group(2).strip()
            field_expr, _ = _resolve_field_reference(
                field, primary, permitted_fields, join_field_permissions
            )
            expr = (
                f"DATE_FORMAT({field_expr}, '%%Y-%%m')"
                if func == "YEAR_MONTH"
                else f"{func}({field_expr})"
            )
            select_parts.append(f"{expr} AS `{dim}`")
            group_by_parts.append(expr)
            dimension_aliases.append(dim)
        else:
            dim_expr, dim_alias = _resolve_field_reference(
                dim, primary, permitted_fields, join_field_permissions
            )
            select_parts.append(f"{dim_expr} AS `{dim_alias}`")
            group_by_parts.append(dim_expr)
            dimension_aliases.append(dim_alias)

    for metric in metrics:
        func = metric["func"].upper()
        field = metric["field"]
        alias = metric["alias"]
        if func not in _ALLOWED_FUNCS:
            raise ValueError(f"Unsupported aggregate function: '{func}'")
        if func == "COUNT_DISTINCT":
            if field == "*":
                expr = "COUNT(DISTINCT *)"
            else:
                field_expr, _ = _resolve_field_reference(
                    field, primary, permitted_fields, join_field_permissions
                )
                expr = f"COUNT(DISTINCT {field_expr})"
        elif func == "COUNT" and field == "*":
            expr = "COUNT(*)"
        else:
            field_expr, _ = _resolve_field_reference(
                field, primary, permitted_fields, join_field_permissions
            )
            expr = f"{func}({field_expr})"
        select_parts.append(f"{expr} AS `{alias}`")
        metric_aliases.append(alias)

    # The INNER JOIN on _ranked_primary filters the main query to only top items
    # and provides _rank_val for ordering. The main LIMIT is generous (top-N items
    # can each have multiple secondary dimension values).
    main_limit = min(limit * 10, 500)

    main_sql = (
        f"SELECT {', '.join(select_parts)}\n"
        f"{from_joins_sql}\n"
        f"INNER JOIN `_ranked_primary`\n"
        f"  ON `_ranked_primary`.`{primary_dim_fieldname}` = {primary_dim_expr}"
        f"{where_sql}\n"
        f"GROUP BY {', '.join(group_by_parts)}\n"
        f"ORDER BY `_ranked_primary`.`_rank_val` DESC\n"
        f"LIMIT %s"
    )
    main_params = list(where_params) + [main_limit]

    full_sql = cte + "\n" + main_sql
    full_params = cte_params + main_params

    return full_sql, full_params


def _build_from_joins_sql(primary: str, joins: list[dict]) -> str:
    """Build the FROM + JOIN SQL fragment for a primary DocType and its joins.

    Standard join: ON child.parent_link_field = primary.name
    Cross-join (join_on set): ON child.parent_link_field = OtherJoinedTable.field
      Used when the join key is a field from another joined table rather than the
      primary DocType's name.  Example:
        Sales Invoice → Sales Invoice Item (standard)
        Item Supplier → join_on: "Sales Invoice Item.item_code"
          generates: ON `tabItem Supplier`.`parent` = `tabSales Invoice Item`.`item_code`
    """
    sql = f"FROM `tab{primary}`"
    for join in joins:
        child_dt = join["child_doctype"]
        parent_link = join["parent_link_field"]
        join_type = join.get("join_type", "LEFT").upper()
        if join_type not in ("INNER", "LEFT"):
            raise ValueError(f"Unsupported join type: '{join_type}'")

        join_on = join.get("join_on")
        if join_on:
            # Cross-join: right-hand side is a field from another joined DocType.
            explicit_dt, field = _split_field_reference(join_on)
            if explicit_dt:
                rhs_expr = f"`tab{explicit_dt}`.`{field}`"
            else:
                rhs_expr = f"`tab{primary}`.`{field}`"
        else:
            rhs_expr = f"`tab{primary}`.`name`"

        sql += (
            f"\n{join_type} JOIN `tab{child_dt}` "
            f"ON `tab{child_dt}`.`{parent_link}` = {rhs_expr}"
        )
    return sql


def _build_where_clause(
    intent: dict,
    primary: str,
    permitted_fields: set,
    join_field_permissions: dict,
    user: str,
) -> tuple[list[str], list]:
    """
    Build the WHERE clause parts and params from intent filters, date_range,
    and the row-scope permission check.

    Returns (where_parts, params) — both can be reused for CTE + main query
    by duplicating params.
    """
    where_parts = []
    params: list = []

    for filt in intent.get("filters", []):
        # Handle both 3-element [field, op, value] and 4-element [doctype, field, op, value]
        if len(filt) == 4:
            dt, field, op, value = filt[0], filt[1], filt[2], filt[3]
            fieldname = f"{dt}.{field}" if "." not in field else field
        else:
            fieldname, op, value = filt[0], filt[1], filt[2]
        if op.lower() not in _ALLOWED_OPERATORS:
            raise ValueError(f"Unsupported filter operator: '{op}'")
        col, _ = _resolve_field_reference(
            fieldname, primary, permitted_fields, join_field_permissions
        )
        if op.lower() in ("in", "not in"):
            values_list = value if isinstance(value, (list, tuple)) else [value]
            placeholders = ", ".join(["%s"] * len(values_list))
            where_parts.append(f"{col} {op} ({placeholders})")
            params.extend(values_list)
        elif op.lower() == "between":
            _DATE_PRESETS = {
                "today", "yesterday", "this_week", "this_month",
                "last_month", "this_year", "last_30_days",
            }
            v0, v1 = str(value[0]).lower(), str(value[1]).lower()
            if v0 in _DATE_PRESETS or v1 in _DATE_PRESETS:
                continue  # date_range block will handle this correctly
            where_parts.append(f"{col} BETWEEN %s AND %s")
            params.extend([value[0], value[1]])
        else:
            where_parts.append(f"{col} {op} %s")
            params.append(value)

    # Date range
    date_range = intent.get("date_range")
    if date_range:
        dr_field = date_range["field"]
        from_date, to_date = _resolve_date_preset(date_range)
        col, _ = _resolve_field_reference(
            dr_field, primary, permitted_fields, join_field_permissions
        )
        if from_date and to_date:
            where_parts.append(f"{col} BETWEEN %s AND %s")
            params.extend([from_date, to_date])
        elif from_date:
            where_parts.append(f"{col} = %s")
            params.append(from_date)

    # Gate 3: Row-scope — frappe.get_list() respects ALL Frappe permission mechanisms
    # (User Permissions, if_owner, role-based restrictions, etc.).
    # This is more reliable than build_match_conditions() which only covers User Permissions.
    try:
        permitted_names = [
            r.name
            for r in frappe.get_list(primary, fields=["name"], ignore_permissions=False, limit=0)
        ]
        if not permitted_names:
            where_parts.append("1=0")
        else:
            placeholders = ", ".join(["%s"] * len(permitted_names))
            where_parts.append(f"`tab{primary}`.`name` IN ({placeholders})")
            params.extend(permitted_names)
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            "query_compiler: row-scope permission check failed",
        )

    return where_parts, params


def _validate_join(join: dict, primary_doctype: str) -> None:
    """
    Verify the join spec refers to a valid relationship.
    Raises ValueError if the join cannot be validated.

    Three valid patterns:
    1. Child table (istable=1): parent_link_field must exist on the child.
    2. Non-child with join_on: cross-join via another joined table's field —
       skip Link-field check since the ON clause references a secondary table.
    3. Non-child without join_on: must be via a declared Link field on the primary.
    """
    child_dt = join["child_doctype"]
    parent_link = join["parent_link_field"]

    child_meta = frappe.get_meta(child_dt)
    if child_meta.istable:
        # Child table: verify the parent_link_field exists on the child
        if parent_link not in _STANDARD_CHILD_FIELDS and not child_meta.get_field(parent_link):
            raise ValueError(
                f"Field '{parent_link}' not found on child DocType '{child_dt}'."
            )
        return

    if join.get("join_on"):
        # Cross-join to a non-child-table via another joined table's field.
        # The ON clause is built from join_on — no Link-field validation needed.
        return

    # Non-child-table without join_on: must be via a declared Link field on primary_doctype
    primary_meta = frappe.get_meta(primary_doctype)
    link_field = primary_meta.get_field(parent_link)
    if not link_field or link_field.fieldtype != "Link":
        raise ValueError(
            f"'{parent_link}' is not a Link field on '{primary_doctype}'. "
            "Joins must go through declared Link fields or use join_on."
        )
    if link_field.options != child_dt:
        raise ValueError(
            f"Link field '{parent_link}' on '{primary_doctype}' points to "
            f"'{link_field.options}', not '{child_dt}'."
        )


def _is_child_table(child_doctype: str) -> bool:
    """Return True if the DocType is a child table (istable=1)."""
    try:
        return bool(frappe.get_meta(child_doctype).istable)
    except Exception:
        return False


def _get_join_field_permissions(joins: list[dict], user: str) -> dict[str, set[str]]:
    permissions: dict[str, set[str]] = {}
    for join in joins or []:
        child_dt = join["child_doctype"]
        permitted = set(permission_service.get_permitted_field_names(child_dt, user))
        permitted.add("name")
        if _is_child_table(child_dt):
            permitted.update(_STANDARD_CHILD_FIELDS)
        permissions[child_dt] = permitted
    return permissions


def _resolve_field_reference(
    raw_field: str,
    primary_doctype: str,
    primary_permitted_fields: set[str],
    join_field_permissions: dict[str, set[str]],
) -> tuple[str, str]:
    field = (raw_field or "").strip()
    if not field:
        raise ValueError("Field reference cannot be empty.")

    explicit_doctype, fieldname = _split_field_reference(field)
    alias = fieldname

    if explicit_doctype:
        if explicit_doctype == primary_doctype:
            if fieldname not in primary_permitted_fields:
                frappe.throw(
                    f"Field '{fieldname}' is not accessible on '{primary_doctype}'.",
                    frappe.PermissionError,
                )
            return f"`tab{primary_doctype}`.`{fieldname}`", alias

        permitted = join_field_permissions.get(explicit_doctype)
        if not permitted:
            raise ValueError(f"DocType '{explicit_doctype}' is not part of the declared joins.")
        if fieldname not in permitted:
            # LLMs often misattribute parent fields to child doctypes.
            # If the field exists on the primary doctype, use it from there silently.
            if fieldname in primary_permitted_fields:
                return f"`tab{primary_doctype}`.`{fieldname}`", alias
            frappe.throw(
                f"Field '{fieldname}' is not accessible on '{explicit_doctype}'.",
                frappe.PermissionError,
            )
        return f"`tab{explicit_doctype}`.`{fieldname}`", alias

    if fieldname in primary_permitted_fields:
        return f"`tab{primary_doctype}`.`{fieldname}`", alias

    matches = [dt for dt, permitted in join_field_permissions.items() if fieldname in permitted]
    if len(matches) == 1:
        return f"`tab{matches[0]}`.`{fieldname}`", alias
    if len(matches) > 1:
        raise ValueError(
            f"Field '{fieldname}' is ambiguous across joined DocTypes: {', '.join(matches)}."
        )

    frappe.throw(
        f"Field '{fieldname}' is not accessible on '{primary_doctype}' or joined DocTypes.",
        frappe.PermissionError,
    )


def _split_field_reference(raw_field: str) -> tuple[str | None, str]:
    field = raw_field.strip()
    match = re.match(r"^`?tab([^`]+)`?\.`?([^`]+)`?$", field)
    if match:
        return match.group(1), match.group(2)

    match = re.match(r"^([^.`]+)\.([^.`]+)$", field)
    if match:
        return match.group(1), match.group(2)

    return None, field.strip("`")


def _resolve_date_preset(date_range: dict) -> tuple[str | None, str | None]:
    """Resolve a date_range spec to (from_date_str, to_date_str)."""
    # Explicit dates take priority over presets
    if date_range.get("from_date") and date_range.get("to_date"):
        return date_range["from_date"], date_range["to_date"]

    preset = date_range.get("preset")
    today = frappe.utils.nowdate()

    if preset == "today":
        return today, None
    elif preset == "yesterday":
        return frappe.utils.add_days(today, -1), None
    elif preset == "this_week":
        d = datetime.date.today()
        monday = d - datetime.timedelta(days=d.weekday())
        sunday = monday + datetime.timedelta(days=6)
        return str(monday), str(sunday)
    elif preset == "this_month":
        return (
            str(frappe.utils.get_first_day(today)),
            str(frappe.utils.get_last_day(today)),
        )
    elif preset == "last_month":
        last_month = frappe.utils.add_months(today, -1)
        return (
            str(frappe.utils.get_first_day(last_month)),
            str(frappe.utils.get_last_day(last_month)),
        )
    elif preset == "this_year":
        year = datetime.date.today().year
        return f"{year}-01-01", f"{year}-12-31"
    elif preset == "last_30_days":
        return frappe.utils.add_days(today, -30), today
    else:
        raise ValueError(f"Unknown date preset: '{preset}'")


def _validate_order_by(
    order_by: str, permitted_fields: set[str], metric_aliases: list[str]
) -> str:
    """
    Validate and return a safe ORDER BY clause.
    Only permitted field names and metric aliases are allowed.
    Returns empty string if the order_by cannot be validated (silently dropped).
    """
    parts = order_by.strip().split()
    if not parts:
        return ""
    field_part = parts[0].strip("`")
    direction = parts[1].upper() if len(parts) > 1 else "ASC"
    if direction not in ("ASC", "DESC"):
        direction = "ASC"
    if field_part in permitted_fields or field_part in metric_aliases:
        return f"`{field_part}` {direction}"
    # Unrecognised field — silently drop rather than raise (avoids retry loop for edge cases)
    return ""
