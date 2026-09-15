# Security

See also [SECURITY.md](../SECURITY.md).

## Defaults

- `policies.tool.default_deny: true`
- `policies.security.allow_unrestricted_shell: false`
- MCP requires explicit grants
- Secret-like output redaction available
- Guardrail actions: allow / block / modify / escalate

## LLM configuration

Only environment variables:

- `AGENTFORGE_LLM_PROVIDER`
- `AGENTFORGE_LLM_MODEL`
- `AGENTFORGE_LLM_API_KEY`
- `AGENTFORGE_LLM_BASE_URL`
- `AGENTFORGE_LLM_MOCK` (default `1` for local/CI)
