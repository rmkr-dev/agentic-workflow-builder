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

## Deterministic fixture tools

Built-ins (offline): `echo`, `upper`, `lower`, `word_count`, `identity`,
`nvd_lookup`, `cloud_exposure`, `iam_impact`, `assemble_cve_report`, `ticket_note`.

Plug a real tool with `kind: python` and `entrypoint: module:function` (function
takes the run state dict). REST tools need `permissions.allow_network` and an
`allowed_hosts` allowlist.

`state_schema` may be a JSON Schema object; `run --input-file` is validated
against it when `type: object` + `properties` are present.

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
