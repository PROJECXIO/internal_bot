"""
Console trace helpers for bench-visible graph debugging.

These helpers write directly to stdout so the execution path is visible
in `bench start` logs for both sync and async requests.
"""
from __future__ import annotations

import json
import os
import sys
import textwrap
import time


_LINE_WIDTH = 56
_ANSI = (
    {"bold": "\x1b[1m", "dim": "\x1b[2m", "reset": "\x1b[0m"}
    if getattr(sys.stdout, "isatty", lambda: False)()
    else {"bold": "", "dim": "", "reset": ""}
)


def _write(line: str = "") -> None:
    sys.stdout.write(f"{line}\n")
    sys.stdout.flush()


def _session_id(state: dict) -> str:
    return (
        state.get("_job_id")
        or state.get("session_name")
        or state.get("user")
        or "unknown-session"
    )


def _is_truthy_env(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def langsmith_enabled() -> bool:
    return _is_truthy_env(os.getenv("LANGSMITH_TRACING")) or _is_truthy_env(
        os.getenv("LANGCHAIN_TRACING_V2")
    )


def _stringify(value) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=True, indent=2)
    except Exception:
        return str(value)


def _format_duration(total_ms: int) -> str:
    if total_ms < 1000:
        return f"{total_ms}ms"
    return f"{total_ms / 1000:.1f}s"


def request_start(state: dict, extra_lines: list[str] | None = None) -> None:
    session_id = _session_id(state)
    _write(f"[{session_id}] ╔{'═' * 50}╗")
    _write(f"[{session_id}] ║         INTERNAL BOT GRAPH REQUEST START         ║")
    _write(f"[{session_id}] ╚{'═' * 50}╝")
    for line in extra_lines or []:
        _write(f"[{session_id}]   {line}")


def request_complete(state: dict, response: dict | None = None) -> None:
    session_id = _session_id(state)
    total_ms = round((time.monotonic() - state.get("start_time", time.monotonic())) * 1000)
    _write(f"[{session_id}] ╔{'═' * 50}╗")
    _write(f"[{session_id}] ║        INTERNAL BOT GRAPH REQUEST COMPLETE       ║")
    _write(f"[{session_id}] ╚{'═' * 50}╝")
    _write(f"[{session_id}]   Total time: {_format_duration(total_ms)}")
    _write(f"[{session_id}]   Node trace: {(state.get('node_trace') or [])}")
    if response:
        _write(f"[{session_id}]   Final status: {response.get('status', 'unknown')}")


def request_error(state: dict, error: str | None = None) -> None:
    session_id = _session_id(state)
    _write(f"[{session_id}] !!! INTERNAL BOT GRAPH REQUEST FAILED")
    if error:
        _write(f"[{session_id}]   Error: {error}")


def node_start(state: dict, node_name: str, extra: str | None = None) -> float:
    session_id = _session_id(state)
    suffix = f"  {extra}" if extra else ""
    plain_len = len(node_name) + len(suffix)
    fill = "─" * max(2, _LINE_WIDTH - plain_len)
    _write()
    _write(f"[{session_id}] ┌─ {_ANSI['bold']}{node_name}{_ANSI['reset']}{suffix} {fill}")
    return time.monotonic()


def node_end(state: dict, node_name: str, start_time: float) -> None:
    session_id = _session_id(state)
    elapsed = round((time.monotonic() - start_time) * 1000)
    plain = f"{node_name}  {elapsed}ms"
    fill = "─" * max(2, _LINE_WIDTH - len(plain))
    _write(f"[{session_id}] └─ {_ANSI['dim']}{node_name}  {elapsed}ms{_ANSI['reset']} {fill}")


def detail(state: dict, message: str, value=None) -> None:
    session_id = _session_id(state)
    if value is None:
        _write(f"[{session_id}]   {message}")
        return

    rendered = _stringify(value)
    _write_block(session_id, message, rendered)


def _write_block(session_id: str, label: str, rendered: str) -> None:
    rendered = (rendered or "").strip()
    if not rendered:
        _write(f"[{session_id}]   {label}:")
        return

    lines = []
    for raw_line in rendered.splitlines():
        if not raw_line:
            lines.append("")
            continue
        wrapped = textwrap.wrap(
            raw_line,
            width=96,
            break_long_words=False,
            break_on_hyphens=False,
        )
        lines.extend(wrapped or [""])

    if len(lines) == 1:
        _write(f"[{session_id}]   {label}: {lines[0]}")
        return

    _write(f"[{session_id}]   {label}:")
    for line in lines:
        if line:
            _write(f"[{session_id}]     {line}")
        else:
            _write(f"[{session_id}]")


def route(state: dict, destination: str) -> None:
    session_id = _session_id(state)
    _write(f"[{session_id}]   ⟹  ROUTING TO: {destination}")


def retry_banner(state: dict, node_name: str, attempt: int, max_attempts: int, prev_error: str | None = None) -> None:
    session_id = _session_id(state)
    _write(f"[{session_id}] ┌─ RETRY {attempt}/{max_attempts} ─ {node_name} {'─' * 24}")
    if prev_error:
        _write(f"[{session_id}] │  Error: {prev_error[:180]}")
    _write(f"[{session_id}] └{'─' * 52}")


def graph_invoke_config(state: dict, run_name: str) -> dict:
    session_id = _session_id(state)
    tags = ["internal_bot", "langgraph", "async" if state.get("_job_id") else "sync"]
    metadata = {
        "app": "internal_bot",
        "session_name": state.get("session_name"),
        "job_id": state.get("_job_id"),
        "user": state.get("user"),
        "debug": bool(state.get("debug")),
    }
    return {
        "run_name": run_name,
        "tags": tags,
        "metadata": {k: v for k, v in metadata.items() if v not in (None, "")},
        "configurable": {"thread_id": session_id},
    }


def llm_trace_context(state: dict, node_name: str, purpose: str) -> dict:
    tags = ["internal_bot", "llm", f"node:{node_name}"]
    tags.append("async" if state.get("_job_id") else "sync")
    metadata = {
        "app": "internal_bot",
        "node": node_name,
        "purpose": purpose,
        "session_name": state.get("session_name"),
        "job_id": state.get("_job_id"),
        "user": state.get("user"),
    }
    return {
        "trace_metadata": {k: v for k, v in metadata.items() if v not in (None, "")},
        "trace_tags": tags,
    }


def flush_langsmith() -> None:
    if not langsmith_enabled():
        return

    try:
        from langchain_core.tracers.langchain import wait_for_all_tracers
    except Exception:
        return

    try:
        wait_for_all_tracers()
    except Exception as exc:
        _write(f"[trace] LangSmith flush failed: {exc}")
