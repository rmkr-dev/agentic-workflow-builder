"""Observability JSONL / span tests."""

from __future__ import annotations

import json

from agentforge.observability import JsonlSpanExporter, Tracer, format_trace_jsonl


def test_format_trace_jsonl_shape():
    events = [
        {"type": "node_start", "at": "2026-01-01T00:00:00Z", "payload": {"status": "OK", "node": "a"}},
        {"type": "llm_call", "at": "2026-01-01T00:00:01Z", "payload": {"output": "hi"}},
    ]
    text = format_trace_jsonl(events, thread_id="t-1")
    lines = [ln for ln in text.strip().splitlines() if ln]
    assert len(lines) == 2
    for ln in lines:
        obj = json.loads(ln)
        assert "trace_id" in obj
        assert obj["trace_id"] == "t-1"
        assert "span_id" in obj
        assert "name" in obj
        assert "attributes" in obj


def test_tracer_jsonl_exporter():
    exporter = JsonlSpanExporter()
    tracer = Tracer(exporter, trace_id="abc123")
    with tracer.node_span("researcher", pattern="sequential") as span:
        span.set_attribute("agentforge.role", "researcher")
    with tracer.tool_span("echo") as span:
        span.add_event("invoked")
    with tracer.llm_span("writer"):
        pass
    dumped = exporter.dumps()
    records = [json.loads(ln) for ln in dumped.strip().splitlines()]
    assert len(records) == 3
    assert records[0]["name"] == "node:researcher"
    assert records[1]["kind"] == "CLIENT"
    assert all(r["trace_id"] == "abc123" for r in records)
    assert all(r["status"] == "OK" for r in records)
