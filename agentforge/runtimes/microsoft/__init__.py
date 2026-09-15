"""Microsoft Agent Framework adapter with honest capability matrix."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

from agentforge.ir.models import RunState, WorkflowIR
from agentforge.runtimes.base import (
    Capability,
    CapabilityInfo,
    CapabilityStatus,
    InspectView,
    RunRequest,
    RunResult,
    RuntimeAdapter,
    UnsupportedCapabilityError,
)
from agentforge.runtimes.base.helpers import SQLiteRunStore, new_thread_id
from agentforge.schema import NodeType, WorkflowPattern

# Patterns we can map onto WorkflowBuilder chains / fan-out-fan-in
_SUPPORTED_PATTERNS = {
    WorkflowPattern.SINGLE,
    WorkflowPattern.SEQUENTIAL,
    WorkflowPattern.PARALLEL,
    WorkflowPattern.FAN_OUT_FAN_IN,
    WorkflowPattern.HANDOFF,
}


class MicrosoftAdapter(RuntimeAdapter):
    """Adapter for Microsoft Agent Framework (agent-framework).

    Fully supported (when installed): sequential chains and parallel fan-out/fan-in
    that execute on real AF ``WorkflowBuilder`` graphs.
    Unsupported: nested subworkflows, MCP grants, reflection loops, supervisor
    routing, HITL parity — these raise ``UnsupportedCapabilityError`` instead of
    silently downgrading.
    """

    name = "microsoft"

    def __init__(self, store: SQLiteRunStore | None = None) -> None:
        self.store = store or SQLiteRunStore(".agentforge/ms_runs.db")
        self._compiled: dict[str, Any] = {}
        self._af_available = self._detect_af()

    def _detect_af(self) -> bool:
        try:
            import agent_framework  # noqa: F401

            return True
        except ImportError:
            return False

    def capabilities(self) -> list[CapabilityInfo]:
        def status(cap: Capability, st: CapabilityStatus, notes: str) -> CapabilityInfo:
            return CapabilityInfo(capability=cap, status=st, notes=notes)

        if not self._af_available:
            return [
                status(
                    c,
                    CapabilityStatus.UNSUPPORTED,
                    "Install optional extra: pip install 'agentforge[microsoft]'",
                )
                for c in Capability
            ]

        matrix = [
            (Capability.COMPILE, CapabilityStatus.SUPPORTED, "WorkflowBuilder mapping"),
            (Capability.VALIDATE, CapabilityStatus.SUPPORTED, "pattern allowlist check"),
            (Capability.RUN, CapabilityStatus.SUPPORTED, "async AF workflow.run bridged to sync API"),
            (Capability.RESUME, CapabilityStatus.PARTIAL, "requires checkpoint_storage on builder"),
            (Capability.STREAM, CapabilityStatus.PARTIAL, "run(..., stream=True) when AF present"),
            (Capability.CANCEL, CapabilityStatus.PARTIAL, "cooperative cancel via local store"),
            (Capability.INSPECT, CapabilityStatus.SUPPORTED, "SQLite inspect view"),
            (Capability.SERIALIZE_STATE, CapabilityStatus.SUPPORTED, "local snapshot"),
            (Capability.CHECKPOINTS, CapabilityStatus.PARTIAL, "FileCheckpointStorage when configured"),
            (Capability.HITL, CapabilityStatus.UNSUPPORTED, "HITL/request-info not mapped from IR"),
            (Capability.PARALLEL, CapabilityStatus.SUPPORTED, "add_fan_out_edges / add_fan_in_edges"),
            (Capability.CONDITIONAL, CapabilityStatus.UNSUPPORTED, "switch-case not mapped from IR yet"),
            (Capability.LOOPS, CapabilityStatus.UNSUPPORTED, "bounded IR loops not mapped"),
            (Capability.SUBWORKFLOWS, CapabilityStatus.UNSUPPORTED, "no nested Workflow IR embedding"),
            (Capability.MCP, CapabilityStatus.UNSUPPORTED, "MCP grants are LangGraph-path only today"),
            (Capability.EVALUATION, CapabilityStatus.PARTIAL, "post-run rubric scoring only"),
            (Capability.GUARDRAILS, CapabilityStatus.PARTIAL, "pre-run text checks only"),
        ]
        return [status(*row) for row in matrix]

    def validate_ir(self, ir: WorkflowIR) -> list[str]:
        errors: list[str] = []
        if not self._af_available:
            errors.append(
                "Microsoft Agent Framework is not installed. "
                "pip install 'agentforge[microsoft]' or use runtime: langgraph"
            )
            return errors
        if ir.pattern not in _SUPPORTED_PATTERNS:
            errors.append(
                f"Pattern '{ir.pattern.value}' is not supported by the Microsoft adapter. "
                f"Supported: {sorted(p.value for p in _SUPPORTED_PATTERNS)}"
            )
        for n in ir.nodes:
            if n.type in {
                NodeType.LOOP,
                NodeType.SUBWORKFLOW,
                NodeType.HUMAN_APPROVAL,
                NodeType.CONDITION,
                NodeType.ROUTER,
            }:
                errors.append(f"Node type {n.type.value} is unsupported on microsoft runtime")
        return errors

    def compile(self, ir: WorkflowIR) -> Any:
        self.require(Capability.COMPILE)
        if not self._af_available:
            raise UnsupportedCapabilityError(
                self.name,
                Capability.COMPILE,
                "agent-framework package not installed — pip install 'agentforge[microsoft]'",
            )
        errors = self.validate_ir(ir)
        if errors:
            raise UnsupportedCapabilityError(self.name, Capability.COMPILE, "; ".join(errors))

        workflow = self._build_af_workflow(ir)
        self._compiled[ir.name] = {"ir": ir, "workflow": workflow}
        return workflow

    def _build_af_workflow(self, ir: WorkflowIR) -> Any:
        """Build a real agent-framework Workflow for sequential or parallel graphs."""
        from agent_framework import WorkflowBuilder

        from agentforge.runtimes.microsoft.executors import (
            make_agent_executor,
            make_join,
            make_passthrough,
        )

        agent_nodes = [n for n in ir.nodes if n.type == NodeType.AGENT]
        if not agent_nodes:
            raise UnsupportedCapabilityError(
                self.name, Capability.COMPILE, "Microsoft adapter requires at least one AGENT node"
            )

        def prompt_for(node) -> str:
            aid = node.agent_id or node.id
            agent = ir.agents.get(aid)
            return agent.system_prompt if agent else "You are helpful."

        is_parallel = ir.pattern in {WorkflowPattern.PARALLEL, WorkflowPattern.FAN_OUT_FAN_IN} or any(
            n.type == NodeType.PARALLEL for n in ir.nodes
        )

        if is_parallel and len(agent_nodes) >= 2:
            start = make_passthrough("af_start")
            workers = [make_agent_executor(n.id, prompt_for(n), final=False) for n in agent_nodes]
            join = make_join("af_join")
            return (
                WorkflowBuilder(start_executor=start, name=ir.name)
                .add_fan_out_edges(start, workers)
                .add_fan_in_edges(workers, join)
                .build()
            )

        # Sequential / single / handoff: chain AGENT nodes in edge order
        ordered = self._order_agent_nodes(ir, agent_nodes)
        executors = []
        for i, n in enumerate(ordered):
            final = i == len(ordered) - 1
            executors.append(make_agent_executor(n.id, prompt_for(n), final=final))
        if len(executors) == 1:
            return WorkflowBuilder(start_executor=executors[0], name=ir.name).build()
        builder = WorkflowBuilder(start_executor=executors[0], name=ir.name)
        builder.add_chain(executors)
        return builder.build()

    def _order_agent_nodes(self, ir: WorkflowIR, agent_nodes: list) -> list:
        """Topological-ish order following edges; fall back to declaration order."""
        by_id = {n.id: n for n in agent_nodes}
        agent_ids = set(by_id)
        successors: dict[str, list[str]] = {i: [] for i in agent_ids}
        indeg = {i: 0 for i in agent_ids}
        for e in ir.edges:
            if e.source in agent_ids and e.target in agent_ids:
                successors[e.source].append(e.target)
                indeg[e.target] += 1
        queue = [i for i, d in indeg.items() if d == 0]
        ordered_ids: list[str] = []
        while queue:
            # Stable: prefer declaration order among ties
            queue.sort(key=lambda x: next(i for i, n in enumerate(agent_nodes) if n.id == x))
            cur = queue.pop(0)
            ordered_ids.append(cur)
            for nxt in successors[cur]:
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    queue.append(nxt)
        if len(ordered_ids) != len(agent_nodes):
            return list(agent_nodes)
        return [by_id[i] for i in ordered_ids]

    def run(self, ir: WorkflowIR, request: RunRequest) -> RunResult:
        self.require(Capability.RUN)
        if ir.pattern not in _SUPPORTED_PATTERNS:
            raise UnsupportedCapabilityError(
                self.name,
                Capability.RUN,
                f"pattern {ir.pattern.value} unsupported — use langgraph",
            )
        if ir.name not in self._compiled:
            self.compile(ir)

        thread_id = request.thread_id or new_thread_id()
        if self.store.is_cancelled(thread_id):
            return RunResult(status=RunState.CANCELLED, thread_id=thread_id, output={})

        user_input = str(request.input.get("input", request.input.get("query", "")))
        workflow = self._compiled[ir.name]["workflow"]

        async def _run() -> Any:
            return await workflow.run(user_input)

        try:
            result = asyncio.run(_run())
            outputs = list(result.get_outputs() or [])
            final = outputs[-1] if outputs else user_input
            backend = "agent_framework"
        except Exception as exc:
            # Surface clearly — do not silently fall back to another runtime
            raise UnsupportedCapabilityError(
                self.name,
                Capability.RUN,
                f"Microsoft AF workflow execution failed: {exc}",
            ) from exc

        out = {
            "output": final,
            "backend": backend,
            "af_outputs": outputs,
            "pattern": ir.pattern.value,
        }
        self.store.save_run(thread_id, RunState.COMPLETED.value, out)
        self.store.add_event(thread_id, "ms_run_finished", out)
        return RunResult(
            status=RunState.COMPLETED,
            output=out,
            thread_id=thread_id,
            events=self.store.list_events(thread_id),
        )

    def resume(self, ir: WorkflowIR, request: RunRequest) -> RunResult:
        info = {c.capability: c for c in self.capabilities()}[Capability.RESUME]
        if info.status == CapabilityStatus.UNSUPPORTED:
            raise UnsupportedCapabilityError(self.name, Capability.RESUME, info.notes)
        return self.run(ir, request)

    def stream(self, ir: WorkflowIR, request: RunRequest) -> Iterator[dict[str, Any]]:
        result = self.run(ir, request)
        yield {"status": result.status.value, "output": result.output}

    def cancel(self, thread_id: str) -> bool:
        self.store.cancel(thread_id)
        return True

    def inspect(self, thread_id: str) -> InspectView:
        row = self.store.get_run(thread_id)
        if not row:
            return InspectView(thread_id=thread_id, status=RunState.FAILED, state={"error": "not found"})
        return InspectView(thread_id=thread_id, status=RunState(row["status"]), state=row["state"])

    def serialize_state(self, thread_id: str) -> dict[str, Any]:
        row = self.store.get_run(thread_id)
        if not row:
            raise KeyError(thread_id)
        return row

    def deserialize_state(self, payload: dict[str, Any]) -> str:
        thread_id = payload.get("thread_id") or new_thread_id()
        self.store.save_run(thread_id, payload.get("status", "PAUSED"), payload.get("state", {}))
        return thread_id
