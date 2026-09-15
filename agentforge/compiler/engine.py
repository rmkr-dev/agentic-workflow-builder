"""Compiler engine — bind IR to a runtime adapter."""

from __future__ import annotations

from agentforge.ir.models import WorkflowIR
from agentforge.runtimes import get_adapter


class CompilerEngine:
    def compile(self, ir: WorkflowIR, runtime: str | None = None) -> WorkflowIR:
        rt = runtime or ir.runtime or "langgraph"
        adapter = get_adapter(rt)
        errors = adapter.validate_ir(ir)
        if errors:
            raise ValueError("; ".join(errors))
        adapter.compile(ir)
        # Return IR annotated with chosen runtime
        return ir.model_copy(update={"runtime": adapter.name})
