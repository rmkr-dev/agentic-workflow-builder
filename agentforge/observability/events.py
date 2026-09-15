"""Observability: events, JSONL traces, OpenTelemetry-compatible spans."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
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
        branch = "L-" if i == len(events) - 1 else "|-"
        payload = ev.get("payload", {})
        summary = payload.get("status") or payload.get("output") or payload
        if isinstance(summary, dict):
            summary = ", ".join(f"{k}={v}" for k, v in list(summary.items())[:3])
        lines.append(f"  {branch} {ev.get('type')} @ {ev.get('at', '?')} - {summary}")
    return "\n".join(lines)


def format_trace_jsonl(events: list[dict[str, Any]], *, thread_id: str | None = None) -> str:
    """Serialize events as newline-delimited JSON (one span-like record per line)."""
    lines: list[str] = []
    for ev in events:
        record = {
            "trace_id": thread_id or ev.get("thread_id") or "unknown",
            "span_id": ev.get("id") or str(uuid.uuid4()),
            "name": ev.get("type") or "event",
            "timestamp": ev.get("at"),
            "attributes": ev.get("payload") or {},
            "status": (ev.get("payload") or {}).get("status", "OK"),
        }
        lines.append(json.dumps(record, default=str))
    return "\n".join(lines) + ("\n" if lines else "")


@dataclass
class Span:
    """Thin OpenTelemetry-compatible span abstraction."""

    name: str
    kind: str = "INTERNAL"  # INTERNAL | CLIENT | SERVER | PRODUCER | CONSUMER
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    parent_span_id: str | None = None
    start_time_unix_nano: int = 0
    end_time_unix_nano: int | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "UNSET"
    events: list[dict[str, Any]] = field(default_factory=list)

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self.events.append({"name": name, "attributes": attributes or {}, "ts": time.time_ns()})

    def end(self, status: str = "OK") -> None:
        self.end_time_unix_nano = time.time_ns()
        self.status = status

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "start_time_unix_nano": self.start_time_unix_nano,
            "end_time_unix_nano": self.end_time_unix_nano,
            "attributes": self.attributes,
            "status": self.status,
            "events": self.events,
        }

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), default=str)


class SpanExporter:
    """Exporter interface for spans."""

    def export(self, spans: list[Span]) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class ConsoleSpanExporter(SpanExporter):
    def export(self, spans: list[Span]) -> None:
        for span in spans:
            print(span.to_jsonl())


class JsonlSpanExporter(SpanExporter):
    def __init__(self, path: str | None = None) -> None:
        self.path = path
        self.buffer: list[Span] = []

    def export(self, spans: list[Span]) -> None:
        self.buffer.extend(spans)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as fh:
                for span in spans:
                    fh.write(span.to_jsonl() + "\n")

    def dumps(self) -> str:
        return "\n".join(s.to_jsonl() for s in self.buffer) + ("\n" if self.buffer else "")


class Tracer:
    """Minimal tracer producing node/tool/LLM spans."""

    def __init__(self, exporter: SpanExporter | None = None, *, trace_id: str | None = None) -> None:
        self.exporter = exporter or JsonlSpanExporter()
        self.trace_id = trace_id or uuid.uuid4().hex
        self._spans: list[Span] = []

    @contextmanager
    def span(
        self,
        name: str,
        *,
        kind: str = "INTERNAL",
        attributes: dict[str, Any] | None = None,
        parent: Span | None = None,
    ) -> Iterator[Span]:
        sp = Span(
            name=name,
            kind=kind,
            trace_id=self.trace_id,
            parent_span_id=parent.span_id if parent else None,
            start_time_unix_nano=time.time_ns(),
            attributes=dict(attributes or {}),
        )
        try:
            yield sp
            if sp.end_time_unix_nano is None:
                sp.end("OK")
        except Exception as exc:
            sp.set_attribute("exception.message", str(exc))
            sp.end("ERROR")
            raise
        finally:
            self._spans.append(sp)
            self.exporter.export([sp])

    def node_span(self, node_id: str, **attrs: Any) -> Any:
        return self.span(f"node:{node_id}", kind="INTERNAL", attributes={"agentforge.node_id": node_id, **attrs})

    def tool_span(self, tool_id: str, **attrs: Any) -> Any:
        return self.span(f"tool:{tool_id}", kind="CLIENT", attributes={"agentforge.tool_id": tool_id, **attrs})

    def llm_span(self, agent_id: str, **attrs: Any) -> Any:
        return self.span(f"llm:{agent_id}", kind="CLIENT", attributes={"agentforge.agent_id": agent_id, **attrs})
