"""Runtime adapter interface and capability discovery."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, AsyncIterator, Iterator

from pydantic import BaseModel, Field

from agentforge.ir.models import RunState, WorkflowIR


class Capability(str, Enum):
    COMPILE = "compile"
    VALIDATE = "validate"
    RUN = "run"
    RESUME = "resume"
    STREAM = "stream"
    CANCEL = "cancel"
    INSPECT = "inspect"
    SERIALIZE_STATE = "serialize_state"
    CHECKPOINTS = "checkpoints"
    HITL = "hitl"
    PARALLEL = "parallel"
    CONDITIONAL = "conditional"
    LOOPS = "loops"
    SUBWORKFLOWS = "subworkflows"
    MCP = "mcp"
    EVALUATION = "evaluation"
    GUARDRAILS = "guardrails"


class CapabilityStatus(str, Enum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"


class CapabilityInfo(BaseModel):
    capability: Capability
    status: CapabilityStatus
    notes: str = ""


class UnsupportedCapabilityError(RuntimeError):
    """Raised when a runtime cannot fulfill a requested capability.

    AgentForge never silently downgrades — callers must handle this explicitly.
    """

    def __init__(self, runtime: str, capability: Capability, notes: str = "") -> None:
        self.runtime = runtime
        self.capability = capability
        self.notes = notes
        msg = f"Runtime '{runtime}' does not support capability '{capability.value}'"
        if notes:
            msg = f"{msg}: {notes}"
        super().__init__(msg)


class RunRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    thread_id: str | None = None
    resume_value: Any = None
    approval: bool | None = None
    dry_run: bool = False


class RunResult(BaseModel):
    status: RunState
    output: dict[str, Any] = Field(default_factory=dict)
    thread_id: str
    checkpoint_id: str | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    interrupt: dict[str, Any] | None = None


class InspectView(BaseModel):
    thread_id: str
    status: RunState
    state: dict[str, Any] = Field(default_factory=dict)
    next_nodes: list[str] = Field(default_factory=list)
    checkpoints: list[dict[str, Any]] = Field(default_factory=list)


class RuntimeAdapter(ABC):
    """Port implemented by LangGraph, Microsoft AF, and mock runtimes."""

    name: str = "base"

    @abstractmethod
    def capabilities(self) -> list[CapabilityInfo]:
        ...

    def require(self, capability: Capability) -> None:
        info = {c.capability: c for c in self.capabilities()}.get(capability)
        if info is None or info.status == CapabilityStatus.UNSUPPORTED:
            raise UnsupportedCapabilityError(
                self.name,
                capability,
                notes=info.notes if info else "not listed",
            )

    def capability_matrix(self) -> dict[str, dict[str, str]]:
        return {
            c.capability.value: {"status": c.status.value, "notes": c.notes}
            for c in self.capabilities()
        }

    @abstractmethod
    def compile(self, ir: WorkflowIR) -> Any:
        ...

    @abstractmethod
    def validate_ir(self, ir: WorkflowIR) -> list[str]:
        ...

    @abstractmethod
    def run(self, ir: WorkflowIR, request: RunRequest) -> RunResult:
        ...

    @abstractmethod
    def resume(self, ir: WorkflowIR, request: RunRequest) -> RunResult:
        ...

    @abstractmethod
    def stream(self, ir: WorkflowIR, request: RunRequest) -> Iterator[dict[str, Any]]:
        ...

    @abstractmethod
    def cancel(self, thread_id: str) -> bool:
        ...

    @abstractmethod
    def inspect(self, thread_id: str) -> InspectView:
        ...

    @abstractmethod
    def serialize_state(self, thread_id: str) -> dict[str, Any]:
        ...

    @abstractmethod
    def deserialize_state(self, payload: dict[str, Any]) -> str:
        ...
