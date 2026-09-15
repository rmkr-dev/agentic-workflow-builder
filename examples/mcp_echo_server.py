#!/usr/bin/env python3
"""Minimal in-repo MCP stdio server exposing an ``echo`` tool.

Used by ``examples/10-mcp`` (and unit tests) so AgentForge can exercise a
real MCP transport without external dependencies beyond the ``mcp`` package.
"""

from __future__ import annotations

import anyio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool


app = Server("agentforge-echo")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="echo",
            description="Echo back the provided input text",
            inputSchema={
                "type": "object",
                "properties": {
                    "input": {"type": "string", "description": "Text to echo"},
                    "text": {"type": "string", "description": "Alias for input"},
                },
            },
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "echo":
        raise ValueError(f"Unknown tool: {name}")
    text = arguments.get("input") or arguments.get("text") or ""
    return [TextContent(type="text", text=str(text))]


async def _main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    anyio.run(_main)
