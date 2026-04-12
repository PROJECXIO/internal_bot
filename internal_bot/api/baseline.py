"""
Baseline dashboard API.

All endpoints require System Manager role.
"""

from __future__ import annotations

import json

import frappe
from frappe import _

from internal_bot.baseline.service import ALLOWED_FIXTURES


def _require_system_manager() -> None:
    if frappe.session.user == "Guest":
        frappe.throw(_("You must be logged in."), frappe.AuthenticationError)
    frappe.only_for("System Manager")


@frappe.whitelist()
def can_access_dashboard() -> dict:
    """Return whether the current user can access the baseline dashboard."""
    if frappe.session.user == "Guest":
        return {"allowed": False}
    try:
        frappe.only_for("System Manager")
        return {"allowed": True}
    except frappe.PermissionError:
        return {"allowed": False}


@frappe.whitelist(methods=["POST"])
def start_run(fixture_name: str = "baseline_queries.json") -> dict:
    """
    Create an AI Baseline Run record and enqueue the background job.

    Accepts only 'baseline_queries.json' or 'golden_queries.json'.
    """
    _require_system_manager()

    if fixture_name not in ALLOWED_FIXTURES:
        frappe.throw(
            _(
                "Invalid fixture name. Allowed values: {0}"
            ).format(", ".join(sorted(ALLOWED_FIXTURES))),
            frappe.ValidationError,
        )

    user = frappe.session.user
    doc = frappe.get_doc(
        {
            "doctype": "AI Baseline Run",
            "status": "Queued",
            "fixture_name": fixture_name,
            "run_user": user,
        }
    )
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    run_id = doc.name

    job = frappe.enqueue(
        "internal_bot.baseline.service.run_baseline_to_record",
        queue="long",
        timeout=1800,
        run_id=run_id,
        fixture_name=fixture_name,
        user=user,
    )
    job_id = getattr(job, "id", None) or ""

    frappe.db.set_value("AI Baseline Run", run_id, "job_id", job_id)
    frappe.db.commit()

    return {"run_id": run_id, "job_id": job_id, "status": "Queued"}


@frappe.whitelist()
def list_runs(limit: int = 20) -> dict:
    """Return compact list of recent baseline runs, newest first."""
    _require_system_manager()

    runs = frappe.get_all(
        "AI Baseline Run",
        fields=[
            "name",
            "status",
            "fixture_name",
            "run_user",
            "started_at",
            "finished_at",
            "duration_ms",
            "total_queries",
            "success_count",
            "clarification_count",
            "blocked_count",
            "greeting_count",
            "error_count",
            "status_mismatch_count",
            "no_row_count",
            "average_retries",
            "average_timing_ms",
            "total_input_tokens",
            "total_output_tokens",
            "average_input_tokens",
            "average_output_tokens",
            "creation",
        ],
        order_by="creation desc",
        limit=int(limit),
    )
    return {"runs": runs}


@frappe.whitelist()
def get_run(run_id: str = None) -> dict:
    """
    Return full run details including parsed summary and report.

    If run_id is omitted, returns the latest run.
    """
    _require_system_manager()

    if not run_id:
        latest = frappe.get_all(
            "AI Baseline Run",
            fields=["name"],
            order_by="creation desc",
            limit=1,
        )
        if not latest:
            return {"run": None, "summary": None, "report": None}
        run_id = latest[0]["name"]

    doc = frappe.get_doc("AI Baseline Run", run_id)
    run_dict = doc.as_dict()

    summary = None
    if doc.summary_json:
        try:
            summary = frappe.parse_json(doc.summary_json)
        except Exception:
            summary = None

    report = None
    if doc.report_json:
        try:
            report = frappe.parse_json(doc.report_json)
        except Exception:
            report = None

    # Remove raw json blobs from the run dict to keep response lean
    run_dict.pop("summary_json", None)
    run_dict.pop("report_json", None)

    return {"run": run_dict, "summary": summary, "report": report}


@frappe.whitelist()
def get_run_status(run_id: str) -> dict:
    """Return lightweight status fields for polling during an active run."""
    _require_system_manager()

    if not run_id:
        frappe.throw(_("run_id is required."), frappe.ValidationError)

    fields = frappe.db.get_value(
        "AI Baseline Run",
        run_id,
        [
            "name",
            "status",
            "completed_queries",
            "total_queries",
            "summary_json",
            "error_detail",
        ],
        as_dict=True,
    )
    if not fields:
        frappe.throw(_("Baseline run not found."), frappe.DoesNotExistError)

    summary = None
    if fields.get("summary_json"):
        try:
            summary = frappe.parse_json(fields["summary_json"])
        except Exception:
            summary = None

    return {
        "run_id": fields["name"],
        "status": fields["status"],
        "completed_queries": fields["completed_queries"] or 0,
        "total_queries": fields["total_queries"] or 0,
        "summary": summary,
        "error_detail": fields.get("error_detail") or "",
    }
