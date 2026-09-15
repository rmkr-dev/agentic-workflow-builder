# DSL Reference

Documents use:

```yaml
apiVersion: agentforge/v1
kind: Workflow
metadata:
  name: my-flow
  description: ...
spec:
  pattern: sequential
  runtime: langgraph
  agents: [...]
  tools: [...]
  mcp_servers: [...]
  nodes: [...]
  edges: [...]
  policies: {...}
  guardrails: [...]
  evaluation: {...}
```

## Node types

`START` `END` `AGENT` `TOOL` `SUBWORKFLOW` `HUMAN_APPROVAL` `CONDITION` `PARALLEL` `JOIN` `LOOP` `EVALUATOR` `TRANSFORM` `ROUTER` `GUARDRAIL`

## Tool kinds

`python` `rest` `cli` `deterministic` `mcp`

CLI tools require explicit `permissions.allow_shell: true` and an `allowed_commands` allowlist when unrestricted shell is disabled (default).

## MCP

```yaml
mcp_servers:
  - id: local
    transport: stdio
    command: my-server
    granted_tools: [summarize]
tools:
  - id: mcp_summarize
    kind: mcp
    mcp_server: local
    mcp_tool: summarize
```

Calls fail if the tool is not in `granted_tools`.
