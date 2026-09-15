# Security hardening demo (`default_deny`)

This example **fails closed** when tools are not explicitly allowed.

## Policy

```yaml
policies:
  tool:
    default_deny: true
    allowed_tools: [safe_echo]
  security:
    allow_unrestricted_shell: false
```

- `ungated_shell` has `allow_shell: false` → `ToolPermissionError`
- `unlisted_cli` is not on the allowlist → blocked by `default_deny`
- Only `safe_echo` is allowlisted

## Expected failure

```bash
agentforge validate examples/11-security/workflow.yaml
agentforge run examples/11-security/workflow.yaml --input "probe" --non-interactive
```

The run should fail (non-zero exit) when the ungated CLI tool node executes.
Use unit tests in `tests/unit/test_security_demo.py` for precise deny assertions.
