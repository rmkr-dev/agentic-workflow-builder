"""Compiler engine — bind IR to a runtime adapter."""

from __future__ import annotations

from typing import Any

from agentforge.compiler.capabilities import assert_runtime_supports, describe_compatibility
from agentforge.ir.models import WorkflowIR
from agentforge.runtimes import get_adapter
from agentforge.runtimes.base import UnsupportedCapabilityError


class CompilerEngine:
    def compile(self, ir: WorkflowIR, runtime: str | None = None) -> WorkflowIR:
        rt = runtime or ir.runtime or "langgraph"
        adapter = get_adapter(rt)
        errors = adapter.validate_ir(ir)
        if errors:
            raise ValueError("; ".join(errors))
        try:
            assert_runtime_supports(ir, adapter)
        except UnsupportedCapabilityError as exc:
            report = describe_compatibility(ir, adapter)
            missing = ", ".join(report.get("unsupported") or [exc.capability.value])
            raise UnsupportedCapabilityError(
                adapter.name,
                exc.capability,
                notes=(
                    f"IR requires unsupported capabilities: {missing}. "
                    f"{exc.notes} Use runtime: langgraph for this workflow."
                ),
            ) from exc
        adapter.compile(ir)
        # Return IR annotated with chosen runtime
        return ir.model_copy(update={"runtime": adapter.name})

    def compatibility(self, ir: WorkflowIR, runtime: str | None = None) -> dict[str, Any]:
        rt = runtime or ir.runtime or "langgraph"
        adapter = get_adapter(rt)
        return describe_compatibility(ir, adapter)
