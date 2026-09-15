"""DSL schema models (Pydantic v2)."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class WorkflowPattern(str, Enum):
    SINGLE = "single"
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    FAN_OUT_FAN_IN = "fan_out_fan_in"
    SUPERVISOR = "supervisor"
    HIERARCHICAL = "hierarchical"
    HANDOFF = "handoff"
    REFLECTION = "reflection"
    CONDITIONAL = "conditional"
    BOUNDED_LOOP = "bounded_loop"
    SUBWORKFLOW = "subworkflow"
    AGENT_AS_TOOL = "agent_as_tool"
    HITL = "hitl"
    EVALUATOR = "evaluator"


class NodeType(str, Enum):
    START = "START"
    END = "END"
    AGENT = "AGENT"
    TOOL = "TOOL"
    SUBWORKFLOW = "SUBWORKFLOW"
    HUMAN_APPROVAL = "HUMAN_APPROVAL"
    CONDITION = "CONDITION"
    PARALLEL = "PARALLEL"
    JOIN = "JOIN"
    LOOP = "LOOP"
    EVALUATOR = "EVALUATOR"
    TRANSFORM = "TRANSFORM"
    ROUTER = "ROUTER"
    GUARDRAIL = "GUARDRAIL"


class GuardrailAction(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    MODIFY = "modify"
    ESCALATE = "escalate"


class ToolKind(str, Enum):
    PYTHON = "python"
    REST = "rest"
    CLI = "cli"
    DETERMINISTIC = "deterministic"
    MCP = "mcp"


class LLMConfig(StrictModel):
    """Provider-neutral LLM config — values resolved from env at runtime."""

    provider: str = Field(default="openai", description="Logical provider name")
    model: str = Field(default="gpt-4o-mini")
    temperature: float = 0.0
    max_tokens: int | None = None
    # Env var names only — never hardcoded secrets
    api_key_env: str = "AGENTFORGE_LLM_API_KEY"
    base_url_env: str = "AGENTFORGE_LLM_BASE_URL"
    model_env: str = "AGENTFORGE_LLM_MODEL"


class AgentSpec(StrictModel):
    id: str
    role: str = "assistant"
    system_prompt: str = "You are a helpful assistant."
    tools: list[str] = Field(default_factory=list)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    as_tool: bool = False
    description: str | None = None


class ToolPermission(StrictModel):
    allow_network: bool = False
    allow_filesystem: bool = False
    allow_shell: bool = False
    allowed_hosts: list[str] = Field(default_factory=list)
    allowed_paths: list[str] = Field(default_factory=list)
    allowed_commands: list[str] = Field(default_factory=list)


class ToolSpec(StrictModel):
    id: str
    kind: ToolKind
    description: str = ""
    entrypoint: str | None = None
    url: str | None = None
    method: str = "GET"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    mcp_server: str | None = None
    mcp_tool: str | None = None
    permissions: ToolPermission = Field(default_factory=ToolPermission)
    deterministic_fn: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_kind_fields(self) -> ToolSpec:
        if self.kind == ToolKind.REST and not self.url:
            raise ValueError(f"tool '{self.id}': REST tools require 'url'")
        if self.kind == ToolKind.CLI and not self.command:
            raise ValueError(f"tool '{self.id}': CLI tools require 'command'")
        if self.kind == ToolKind.CLI and self.permissions.allow_shell is False:
            # Explicit opt-in required
            pass
        if self.kind == ToolKind.MCP and (not self.mcp_server or not self.mcp_tool):
            raise ValueError(f"tool '{self.id}': MCP tools require mcp_server and mcp_tool")
        if self.kind == ToolKind.PYTHON and not self.entrypoint:
            raise ValueError(f"tool '{self.id}': Python tools require 'entrypoint'")
        if self.kind == ToolKind.DETERMINISTIC and not self.deterministic_fn:
            raise ValueError(f"tool '{self.id}': deterministic tools require 'deterministic_fn'")
        return self


class MCPServerSpec(StrictModel):
    id: str
    transport: Literal["stdio", "sse", "streamable_http"] = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    granted_tools: list[str] = Field(default_factory=list, description="Explicit tool grants")


class NodeSpec(StrictModel):
    id: str
    type: NodeType
    agent: str | None = None
    tool: str | None = None
    subworkflow: str | None = None
    condition: str | None = None
    routes: dict[str, str] = Field(default_factory=dict)
    join_of: list[str] = Field(default_factory=list)
    parallel_of: list[str] = Field(default_factory=list)
    loop_body: str | None = None
    loop_condition: str | None = None
    max_iterations: int = 5
    transform: str | None = None
    prompt: str | None = None
    approval_message: str | None = None
    guardrail_action: GuardrailAction | None = None
    guardrail_rules: list[str] = Field(default_factory=list)
    evaluator_rubric: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class EdgeSpec(StrictModel):
    source: str
    target: str
    condition: str | None = None
    label: str | None = None


class BudgetPolicy(StrictModel):
    max_steps: int = 100
    max_llm_calls: int = 50
    max_tool_calls: int = 50
    max_cost_usd: float | None = None
    timeout_seconds: float = 300.0


class ToolPolicy(StrictModel):
    default_deny: bool = True
    allowed_tools: list[str] = Field(default_factory=list)
    require_explicit_grants: bool = True


class ModelPolicy(StrictModel):
    allowed_providers: list[str] = Field(default_factory=lambda: ["openai", "azure", "anthropic", "mock"])
    allowed_models: list[str] = Field(default_factory=list)
    require_env_keys: bool = True


class ApprovalPolicy(StrictModel):
    require_for_tools: list[str] = Field(default_factory=list)
    require_for_nodes: list[str] = Field(default_factory=list)
    auto_approve_in_tests: bool = True


class SecurityPolicy(StrictModel):
    block_secrets_in_prompts: bool = True
    redact_outputs: bool = True
    allow_unrestricted_shell: bool = False


class ExecutionPolicy(StrictModel):
    allow_parallel: bool = True
    deterministic_seed: int | None = 42
    fail_fast: bool = True


class PoliciesSpec(StrictModel):
    budget: BudgetPolicy = Field(default_factory=BudgetPolicy)
    tool: ToolPolicy = Field(default_factory=ToolPolicy)
    model: ModelPolicy = Field(default_factory=ModelPolicy)
    approval: ApprovalPolicy = Field(default_factory=ApprovalPolicy)
    security: SecurityPolicy = Field(default_factory=SecurityPolicy)
    execution: ExecutionPolicy = Field(default_factory=ExecutionPolicy)


class GuardrailSpec(StrictModel):
    id: str
    rules: list[str] = Field(default_factory=list)
    on_match: GuardrailAction = GuardrailAction.BLOCK
    message: str | None = None


class EvaluationSpec(StrictModel):
    enabled: bool = False
    rubric: str = "Correctness, completeness, safety"
    pass_threshold: float = 0.7
    metrics: list[str] = Field(default_factory=lambda: ["correctness", "safety"])


class MemorySpec(StrictModel):
    kind: Literal["none", "buffer", "sqlite"] = "sqlite"
    max_messages: int = 50


class ObservabilitySpec(StrictModel):
    emit_events: bool = True
    sqlite_path: str = ".agentforge/events.db"


class WorkflowMetadata(StrictModel):
    name: str
    description: str = ""
    version: str = "0.1.0"
    tags: list[str] = Field(default_factory=list)


class WorkflowSpec(StrictModel):
    pattern: WorkflowPattern = WorkflowPattern.SEQUENTIAL
    runtime: str = "langgraph"
    entry: str | None = None
    agents: list[AgentSpec] = Field(default_factory=list)
    tools: list[ToolSpec] = Field(default_factory=list)
    mcp_servers: list[MCPServerSpec] = Field(default_factory=list)
    nodes: list[NodeSpec] = Field(default_factory=list)
    edges: list[EdgeSpec] = Field(default_factory=list)
    policies: PoliciesSpec = Field(default_factory=PoliciesSpec)
    guardrails: list[GuardrailSpec] = Field(default_factory=list)
    evaluation: EvaluationSpec = Field(default_factory=EvaluationSpec)
    memory: MemorySpec = Field(default_factory=MemorySpec)
    observability: ObservabilitySpec = Field(default_factory=ObservabilitySpec)
    state_schema: dict[str, Any] = Field(default_factory=dict)
    subworkflows: dict[str, Any] = Field(default_factory=dict)

    @field_validator("runtime")
    @classmethod
    def _normalize_runtime(cls, v: str) -> str:
        return v.strip().lower()


class WorkflowDocument(StrictModel):
    apiVersion: Literal["agentforge/v1"] = "agentforge/v1"
    kind: Literal["Workflow"] = "Workflow"
    metadata: WorkflowMetadata
    spec: WorkflowSpec
