"""MCP client with live stdio/SSE transport and explicit tool grants."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from agentforge.schema import MCPServerSpec


class MCPGrantError(PermissionError):
    """Raised when a tool is invoked without an explicit grant."""


class MCPTransportError(RuntimeError):
    """Raised when a live MCP session cannot be established or used."""


class MCPClient:
    """First-class MCP integration with grant enforcement.

    - Always enforces ``granted_tools`` (no auto-grant-all).
    - Uses the official ``mcp`` Python SDK for stdio (and SSE when configured).
    - Falls back to a deterministic local stub only when no command/url is set
      (useful for unit tests without spawning a server).
    """

    def __init__(self, servers: dict[str, MCPServerSpec]) -> None:
        self.servers = servers

    def list_granted(self, server_id: str) -> list[str]:
        server = self.servers[server_id]
        return list(server.granted_tools)

    def list_tools(self, server_id: str) -> list[dict[str, Any]]:
        """Discover tools from a live server (filtered to grants when present)."""
        server = self._require_server(server_id)
        if not self._has_live_config(server):
            return [
                {"name": name, "description": "granted (stub)", "granted": True}
                for name in server.granted_tools
            ]
        tools = self._run_async(self._alist_tools(server))
        granted = set(server.granted_tools)
        return [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "granted": t["name"] in granted,
            }
            for t in tools
            if not granted or t["name"] in granted
        ]

    def call_tool(self, server_id: str, tool_name: str, arguments: dict[str, Any]) -> Any:
        server = self._require_server(server_id)
        if tool_name not in server.granted_tools:
            raise MCPGrantError(
                f"MCP tool '{tool_name}' is not explicitly granted on server '{server_id}'. "
                f"Granted: {server.granted_tools}"
            )
        if not self._has_live_config(server):
            return {
                "server": server_id,
                "tool": tool_name,
                "transport": server.transport,
                "status": "granted_stub",
                "echo": arguments.get("input", arguments.get("text")),
                "command": server.command,
            }
        return self._run_async(self._acall_tool(server, server_id, tool_name, arguments))

    def _require_server(self, server_id: str) -> MCPServerSpec:
        server = self.servers.get(server_id)
        if not server:
            raise KeyError(f"Unknown MCP server '{server_id}'")
        return server

    @staticmethod
    def _has_live_config(server: MCPServerSpec) -> bool:
        if server.transport == "stdio" and server.command:
            return True
        if server.transport in {"sse", "streamable_http"} and server.url:
            return True
        return False

    @staticmethod
    def _run_async(coro: Any) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        # Already inside an event loop — run in a fresh thread/loop
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()

    async def _alist_tools(self, server: MCPServerSpec) -> list[dict[str, Any]]:
        if server.transport == "stdio":
            return await self._stdio_list_tools(server)
        if server.transport in {"sse", "streamable_http"}:
            return await self._sse_list_tools(server)
        raise MCPTransportError(f"Unsupported MCP transport: {server.transport}")

    async def _acall_tool(
        self,
        server: MCPServerSpec,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        if server.transport == "stdio":
            return await self._stdio_call_tool(server, server_id, tool_name, arguments)
        if server.transport in {"sse", "streamable_http"}:
            return await self._sse_call_tool(server, server_id, tool_name, arguments)
        raise MCPTransportError(f"Unsupported MCP transport: {server.transport}")

    async def _stdio_session(self, server: MCPServerSpec):
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:  # pragma: no cover
            raise MCPTransportError(
                "Live MCP requires the 'mcp' package. Install with: pip install mcp"
            ) from exc

        env = {**os.environ, **(server.env or {})}
        params = StdioServerParameters(
            command=server.command or "python",
            args=list(server.args or []),
            env=env,
        )
        return stdio_client(params), ClientSession

    async def _stdio_list_tools(self, server: MCPServerSpec) -> list[dict[str, Any]]:
        stdio_cm, ClientSession = await self._stdio_session(server)
        async with stdio_cm as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [
                    {"name": t.name, "description": getattr(t, "description", "") or ""}
                    for t in (result.tools or [])
                ]

    async def _stdio_call_tool(
        self,
        server: MCPServerSpec,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        stdio_cm, ClientSession = await self._stdio_session(server)
        async with stdio_cm as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=arguments)
                return self._normalize_result(server_id, tool_name, server.transport, result)

    async def _sse_list_tools(self, server: MCPServerSpec) -> list[dict[str, Any]]:
        try:
            from mcp import ClientSession
            from mcp.client.sse import sse_client
        except ImportError as exc:  # pragma: no cover
            raise MCPTransportError(
                "Live MCP SSE requires the 'mcp' package. Install with: pip install mcp"
            ) from exc
        async with sse_client(server.url or "") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [
                    {"name": t.name, "description": getattr(t, "description", "") or ""}
                    for t in (result.tools or [])
                ]

    async def _sse_call_tool(
        self,
        server: MCPServerSpec,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        try:
            from mcp import ClientSession
            from mcp.client.sse import sse_client
        except ImportError as exc:  # pragma: no cover
            raise MCPTransportError(
                "Live MCP SSE requires the 'mcp' package. Install with: pip install mcp"
            ) from exc
        async with sse_client(server.url or "") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=arguments)
                return self._normalize_result(server_id, tool_name, server.transport, result)

    @staticmethod
    def _normalize_result(server_id: str, tool_name: str, transport: str, result: Any) -> Any:
        content = getattr(result, "content", None) or []
        texts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if text is not None:
                texts.append(str(text))
            else:
                texts.append(str(item))
        payload: Any
        if len(texts) == 1:
            payload = texts[0]
            try:
                payload = json.loads(payload)
            except (TypeError, json.JSONDecodeError):
                pass
        else:
            payload = texts
        return {
            "server": server_id,
            "tool": tool_name,
            "transport": transport,
            "status": "live",
            "result": payload,
            "isError": bool(getattr(result, "isError", False)),
        }
