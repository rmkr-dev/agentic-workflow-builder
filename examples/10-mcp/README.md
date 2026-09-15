# MCP live echo example

Demonstrates **live MCP stdio transport** against the in-repo echo server
(`examples/mcp_echo_server.py`) with **explicit grants** (no auto-grant-all).

## Requirements

```bash
pip install -e ".[dev]"   # includes mcp
# or: pip install mcp
```

## Validate + run

```bash
agentforge validate examples/10-mcp/workflow.yaml
agentforge run examples/10-mcp/workflow.yaml --input "hello mcp" --non-interactive
```

Expected: tool node invokes MCP `echo` and returns a live result payload.

## Grants

Only `echo` is listed under `mcp_servers[].granted_tools`. Calling any other
MCP tool name raises `MCPGrantError`.
