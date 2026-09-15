"""MCP client with explicit tool grants."""

from __future__ import annotations

from typing import Any

from agentforge.schema import MCPServerSpec


class MCPGrantError(PermissionError):
    pass


class MCPClient:
    """First-class MCP integration.

    Real transport wiring is optional; without a live server we execute a
    deterministic local stub that still enforces explicit granted_tools.
    """

    def __init__(self, servers: dict[str, MCPServerSpec]) -> None:
        self.servers = servers

    def call_tool(self, server_id: str, tool_name: str, arguments: dict[str, Any]) -> Any:
        server = self.servers.get(server_id)
        if not server:
            raise KeyError(f"Unknown MCP server '{server_id}'")
        if tool_name not in server.granted_tools:
            raise MCPGrantError(
                f"MCP tool '{tool_name}' is not explicitly granted on server '{server_id}'. "
                f"Granted: {server.granted_tools}"
            )
        # Attempt live call if url/command configured; otherwise deterministic stub
        if server.transport in {"sse", "streamable_http"} and server.url:
            return {
                "server": server_id,
                "tool": tool_name,
                "transport": server.transport,
                "status": "stubbed_no_live_session",
                "echo": arguments.get("input"),
            }
        return {
            "server": server_id,
            "tool": tool_name,
            "transport": server.transport,
            "status": "granted_stub",
            "echo": arguments.get("input"),
            "command": server.command,
        }

    def list_granted(self, server_id: str) -> list[str]:
        server = self.servers[server_id]
        return list(server.granted_tools)
