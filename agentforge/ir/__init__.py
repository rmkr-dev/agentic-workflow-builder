"""Canonical Workflow Intermediate Representation."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agentforge.schema import (
    AgentSpec,
    EvaluationSpec,
    GuardrailSpec,
    MCPServerSpec,
    MemorySpec,
    NodeType,
    ObservabilitySpec,
    PoliciesSpec,
    ToolSpec,
    WorkflowPattern,
)


class RunState(str, Enum):
    RUNNING = "RUNNING"
    WAITING_FOR_INPUT = "WAITING_FOR_INPUT"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    PAUSED = "PAUSED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class IRNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: NodeType
    agent_id: str | None = None
    tool_id: str | None = None
    subworkflow_id: str | None = None
    condition_expr: str | None = None
    routes: dict[str, str] = Field(default_factory=dict)
    join_of: list[str] = Field(default_factory=list)
    parallel_of: list[str] = Field(default_factory=list)
    loop_body: str | None = None
    loop_condition: str | None = None
    max_iterations: int = 5
    transform_expr: str | None = None
    prompt: str | None = None
    approval_message: str | None = None
    guardrail_action: str | None = None
    guardrail_rules: list[str] = Field(default_factory=list)
    evaluator_rubric: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class IREdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    condition_expr: str | None = None
    label: str | None = None


class WorkflowIR(BaseModel):
    """Canonical graph IR consumed by runtimes and the code generator."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    version: str = "0.1.0"
    pattern: WorkflowPattern = WorkflowPattern.SEQUENTIAL
    runtime: str = "langgraph"
    entry: str = "start"
    nodes: list[IRNode] = Field(default_factory=list)
    edges: list[IREdge] = Field(default_factory=list)
    agents: dict[str, AgentSpec] = Field(default_factory=dict)
    tools: dict[str, ToolSpec] = Field(default_factory=dict)
    mcp_servers: dict[str, MCPServerSpec] = Field(default_factory=dict)
    policies: PoliciesSpec = Field(default_factory=PoliciesSpec)
    guardrails: list[GuardrailSpec] = Field(default_factory=list)
    evaluation: EvaluationSpec = Field(default_factory=EvaluationSpec)
    memory: MemorySpec = Field(default_factory=MemorySpec)
    observability: ObservabilitySpec = Field(default_factory=ObservabilitySpec)
    state_schema: dict[str, Any] = Field(default_factory=dict)
    subworkflows: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    source_path: str | None = None

    def node_map(self) -> dict[str, IRNode]:
        return {n.id: n for n in self.nodes}

    def start_nodes(self) -> list[IRNode]:
        return [n for n in self.nodes if n.type == NodeType.START]

    def end_nodes(self) -> list[IRNode]:
        return [n for n in self.nodes if n.type == NodeType.END]

    def to_mermaid(self) -> str:
        lines = ["flowchart TD"]
        for n in self.nodes:
            shape = {
                NodeType.START: (f"{n.id}([START])"),
                NodeType.END: (f"{n.id}([END])"),
                NodeType.CONDITION: (f"{n.id}{{{n.id}}}"),
                NodeType.PARALLEL: (f"{n.id}[[{n.id}]]"),
                NodeType.JOIN: (f"{n.id}[[{n.id}]]"),
                NodeType.HUMAN_APPROVAL: (f"{n.id}[/{n.id}/]"),
                NodeType.GUARDRAIL: (f"{n.id}> {n.id} ]"),
            }.get(n.type, f"{n.id}[{n.type.value}:{n.id}]")
            lines.append(f"  {shape}")
        for e in self.edges:
            label = f"|{e.label or e.condition_expr}|" if (e.label or e.condition_expr) else ""
            lines.append(f"  {e.source} -->{label} {e.target}")
        return "\n".join(lines)
