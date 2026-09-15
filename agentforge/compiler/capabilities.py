"""Map Workflow IR features to runtime capabilities (honest, fail-closed)."""

from __future__ import annotations

from typing import Any

from agentforge.ir.models import WorkflowIR
from agentforge.runtimes.base import (
    Capability,
    CapabilityStatus,
    RuntimeAdapter,
    UnsupportedCapabilityError,
)
from agentforge.schema import NodeType, ToolKind


def required_capabilities(ir: WorkflowIR) -> list[Capability]:
    """Capabilities the IR actually needs (not the full adapter matrix)."""
    needed: list[Capability] = [
        Capability.COMPILE,
        Capability.VALIDATE,
        Capability.RUN,
    ]
    types = {n.type for n in ir.nodes}
    if NodeType.HUMAN_APPROVAL in types:
        needed.extend([Capability.HITL, Capability.RESUME, Capability.CHECKPOINTS])
    if NodeType.PARALLEL in types or NodeType.JOIN in types:
        needed.append(Capability.PARALLEL)
    if NodeType.CONDITION in types or NodeType.ROUTER in types:
        needed.append(Capability.CONDITIONAL)
    if NodeType.LOOP in types:
        needed.append(Capability.LOOPS)
    if NodeType.SUBWORKFLOW in types:
        needed.append(Capability.SUBWORKFLOWS)
    if NodeType.EVALUATOR in types or ir.evaluation.enabled:
        needed.append(Capability.EVALUATION)
    if NodeType.GUARDRAIL in types or ir.guardrails:
        needed.append(Capability.GUARDRAILS)
    if any(t.kind == ToolKind.MCP for t in ir.tools.values()) or ir.mcp_servers:
        needed.append(Capability.MCP)
    # Deduplicate, preserve order
    seen: set[Capability] = set()
    ordered: list[Capability] = []
    for cap in needed:
        if cap not in seen:
            seen.add(cap)
            ordered.append(cap)
    return ordered


def describe_compatibility(ir: WorkflowIR, adapter: RuntimeAdapter) -> dict[str, Any]:
    matrix = adapter.capability_matrix()
    required = required_capabilities(ir)
    rows: list[dict[str, str]] = []
    unsupported: list[str] = []
    for cap in required:
        info = matrix.get(cap.value) or {"status": "unsupported", "notes": "not listed"}
        status = info.get("status", "unsupported")
        rows.append(
            {
                "capability": cap.value,
                "status": status,
                "notes": info.get("notes", ""),
            }
        )
        if status == CapabilityStatus.UNSUPPORTED.value:
            unsupported.append(cap.value)
    supported = sum(1 for r in rows if r["status"] == CapabilityStatus.SUPPORTED.value)
    return {
        "runtime": adapter.name,
        "required": [c.value for c in required],
        "rows": rows,
        "supported": supported,
        "total": len(rows),
        "unsupported": unsupported,
        "ok": not unsupported,
        "pattern": ir.pattern.value,
        "nodes": len(ir.nodes),
    }


def assert_runtime_supports(ir: WorkflowIR, adapter: RuntimeAdapter) -> dict[str, Any]:
    report = describe_compatibility(ir, adapter)
    if report["unsupported"]:
        first = report["unsupported"][0]
        notes = next((r["notes"] for r in report["rows"] if r["capability"] == first), "")
        raise UnsupportedCapabilityError(adapter.name, Capability(first), notes=notes)
    return report
