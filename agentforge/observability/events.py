"""Observability event emitter."""

from __future__ import annotations

from typing import Any

from agentforge.runtimes.base.helpers import SQLiteRunStore


class EventEmitter:
    def __init__(self, store: SQLiteRunStore) -> None:
        self.store = store

    def emit(self, thread_id: str, event_type: str, payload: dict[str, Any]) -> None:
        self.store.add_event(thread_id, event_type, payload)


def format_trace_tree(events: list[dict[str, Any]]) -> str:
    if not events:
        return "(no events)"
    lines = ["run"]
    for i, ev in enumerate(events):
        branch = "└─" if i == len(events) - 1 else "├─"
        payload = ev.get("payload", {})
        summary = payload.get("status") or payload.get("output") or payload
        if isinstance(summary, dict):
            summary = ", ".join(f"{k}={v}" for k, v in list(summary.items())[:3])
        lines.append(f"  {branch} {ev.get('type')} @ {ev.get('at', '?')} — {summary}")
    return "\n".join(lines)
