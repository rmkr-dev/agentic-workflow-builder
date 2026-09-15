# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | yes       |

## Reporting a vulnerability

Email security reports privately to the maintainers. Do not open public issues for undisclosed vulnerabilities.

## Hardening defaults

- Tool policy defaults to deny; explicit allowlists required
- CLI/shell tools require `permissions.allow_shell: true` and `allowed_commands`
- Unrestricted shell is off (`policies.security.allow_unrestricted_shell: false`)
- MCP tools require explicit `granted_tools` on the server
- LLM credentials are read only from environment variables
- Guardrails support allow / block / modify / escalate
- Outputs can be redacted for secret-like patterns

## Secrets

Never commit `.env`, API keys, tokens, or private credentials. Use `.env.example` as a template.
