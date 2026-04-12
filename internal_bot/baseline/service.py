"""
Baseline service layer.

Wraps the Phase 0 baseline runner so it can be called from both:
  - the bench CLI via internal_bot.tests.run_baseline.run
  - the background job queue via internal_bot.api.baseline.start_run

This module does NOT change bot behavior, graph routing, prompts, query
compilation, permissions, or the existing chat flow.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import frappe

# Re-use all logic from the existing runner (imports are internal only).
from internal_bot.tests.run_baseline import (
    SESSION_PREFIX,
    FIXTURE_DIR,
    DEFAULT_FIXTURE,
    DEFAULT_OUTPUT_DIR,
    REPORT_FILE,
    SUMMARY_FILE,
    _resolve_fixture_path,
    _load_queries,
    _expand_dependencies,
    _prepare_user,
    _reset_baseline_sessions,
    _load_settings,
    _load_llm_client,
    _run_query,
    _print_progress,
    _build_summary,
    _write_json,
    _json_safe,
    _display_path,
)

ALLOWED_FIXTURES = {"baseline_queries.json", "golden_queries.json"}


def run_baseline_to_record(
    run_id: str,
    fixture_name: str = "baseline_queries.json",
    user: str = "Administrator",
    output_dir: str | None = None,
    include_trace_output: bool = True,
) -> None:
    """
    Run the baseline fixture and persist results to an AI Baseline Run record.

    Designed to be called from frappe.enqueue (background RQ worker).
    Updates run_id in-place as queries complete so the UI can poll progress.

    Per-query errors are stored as report rows (not global failure).
    Only unrecoverable startup errors or unhandled exceptions trigger global
    failure and set status to Failed.
    """
    started_wall = time.monotonic()

    def _update_run(**kwargs):
        frappe.db.set_value("AI Baseline Run", run_id, kwargs)
        frappe.db.commit()

    try:
        _update_run(status="Running", started_at=frappe.utils.now_datetime())

        fixture_path = _resolve_fixture_path(fixture_name)
        output_path = (
            Path(output_dir).expanduser().resolve() if output_dir else DEFAULT_OUTPUT_DIR
        )
        output_path.mkdir(parents=True, exist_ok=True)

        queries = _load_queries(fixture_path)
        queries = _expand_dependencies(queries, fixture_path)
        _prepare_user(user)
        _reset_baseline_sessions()

        settings, settings_error = _load_settings()
        llm_client, llm_error = _load_llm_client()
        startup_error = settings_error or llm_error

        total = len(queries)
        _update_run(total_queries=total)

        results: list[dict] = []
        for index, query in enumerate(queries, start=1):
            result = _run_query(
                query=query,
                index=index,
                total=total,
                user=user,
                settings=settings,
                llm_client=llm_client,
                startup_error=startup_error,
                include_trace_output=include_trace_output,
            )
            results.append(result)
            _print_progress(result, index, total)
            _update_run(completed_queries=index)

        report = {
            "fixture": _display_path(fixture_path),
            "output_files": {
                "report": _display_path(output_path / REPORT_FILE),
                "summary": _display_path(output_path / SUMMARY_FILE),
            },
            "session_prefix": SESSION_PREFIX,
            "user": user,
            "results": results,
        }
        summary = _build_summary(results)

        _write_json(output_path / REPORT_FILE, report)
        _write_json(output_path / SUMMARY_FILE, summary)
        frappe.db.commit()

        finished_wall = time.monotonic()
        duration_ms = round((finished_wall - started_wall) * 1000)

        no_row_ids: list = summary.get("queries_with_no_rows") or []

        frappe.db.set_value(
            "AI Baseline Run",
            run_id,
            {
                "status": "Completed",
                "finished_at": frappe.utils.now_datetime(),
                "duration_ms": duration_ms,
                "total_queries": summary.get("total_queries") or 0,
                "completed_queries": summary.get("total_queries") or 0,
                "success_count": summary.get("success_count") or 0,
                "clarification_count": summary.get("clarification_count") or 0,
                "blocked_count": summary.get("blocked_count") or 0,
                "greeting_count": summary.get("greeting_count") or 0,
                "error_count": summary.get("error_count") or 0,
                "status_mismatch_count": len(summary.get("status_mismatches") or []),
                "no_row_count": len(no_row_ids),
                "average_retries": summary.get("average_retries") or 0.0,
                "average_timing_ms": summary.get("average_timing_ms") or 0.0,
                "summary_json": json.dumps(_json_safe(summary), ensure_ascii=False),
                "report_json": json.dumps(_json_safe(report), ensure_ascii=False),
                "error_detail": "",
            },
        )
        frappe.db.commit()

    except Exception as exc:
        frappe.log_error(
            message=frappe.get_traceback(),
            title=f"AI Baseline Run {run_id}: global failure",
        )
        try:
            frappe.db.set_value(
                "AI Baseline Run",
                run_id,
                {
                    "status": "Failed",
                    "finished_at": frappe.utils.now_datetime(),
                    "error_detail": str(exc),
                },
            )
            frappe.db.commit()
        except Exception:
            pass
