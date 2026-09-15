# Changelog

## 0.1.1 — 2026-09-15

- Live MCP stdio/SSE client with explicit grants + `examples/10-mcp`
- NL architect multi-intent composition (research+write+HITL, etc.)
- Golden-file / schema evaluation + optional LLM-as-judge (`--llm-judge`)
- Microsoft AF real sequential + parallel `WorkflowBuilder` slice
- Codegen IR fidelity (tools, HITL, pattern-specific tests, agent/tool docs)
- `agentforge trace --format jsonl` + OTEL-compatible span abstractions
- `examples/11-security` fail-closed `default_deny` demo

## 0.1.0 — 2026-09-15

Initial release of AgentForge:

- YAML/JSON DSL → parser → validator → Workflow IR → compiler
- LangGraph runtime adapter (primary)
- Microsoft Agent Framework adapter with honest capability matrix
- CLI + SDK + Jinja2/project generator
- Tools (python/REST/CLI/deterministic/MCP), policies, guardrails, evaluation, observability
- Nine pattern examples and CI via `make verify`
