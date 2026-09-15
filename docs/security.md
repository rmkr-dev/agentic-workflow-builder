# Security

See also [SECURITY.md](../SECURITY.md).

## Defaults

- `policies.tool.default_deny: true`
- `policies.security.allow_unrestricted_shell: false`
- MCP requires explicit grants (`granted_tools`) — never auto-grant-all
- Secret-like output redaction available
- Guardrail actions: allow / block / modify / escalate

## Fail-closed demo

See [`examples/11-security`](../examples/11-security): ungated CLI (`allow_shell: false`)
and tools missing from `allowed_tools` raise `ToolPermissionError` / fail the run.

```bash
agentforge validate examples/11-security/workflow.yaml
agentforge run examples/11-security/workflow.yaml --input "probe" --non-interactive
# expect non-zero exit / FAILED status
```

## MCP grants

```yaml
mcp_servers:
  - id: echo_server
    transport: stdio
    command: python
    args: [examples/mcp_echo_server.py]
    granted_tools: [echo]   # explicit only
```

Calling a tool not listed in `granted_tools` raises `MCPGrantError`.

## LLM configuration

Only environment variables:

- `AGENTFORGE_LLM_PROVIDER`
- `AGENTFORGE_LLM_MODEL`
- `AGENTFORGE_LLM_API_KEY`
- `AGENTFORGE_LLM_BASE_URL`
- `AGENTFORGE_LLM_MOCK` (default `1` for local/CI)
