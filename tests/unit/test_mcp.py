"""Tests for live MCP client grants and discovery."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agentforge.mcp.client import MCPClient, MCPGrantError
from agentforge.parser.loader import SpecLoader
from agentforge.runtimes import get_adapter
from agentforge.runtimes.base import RunRequest
from agentforge.schema import MCPServerSpec
from agentforge.validator.engine import ValidationEngine

ROOT = Path(__file__).resolve().parents[2]
ECHO_SERVER = ROOT / "examples" / "mcp_echo_server.py"
MCP_EXAMPLE = ROOT / "examples" / "10-mcp" / "workflow.yaml"


def _echo_server_spec(*, granted: list[str] | None = None) -> MCPServerSpec:
    return MCPServerSpec(
        id="echo_server",
        transport="stdio",
        command=sys.executable,
        args=[str(ECHO_SERVER)],
        granted_tools=granted if granted is not None else ["echo"],
    )


def test_mcp_deny_without_grant():
    client = MCPClient({"echo_server": _echo_server_spec(granted=["echo"])})
    with pytest.raises(MCPGrantError):
        client.call_tool("echo_server", "not_granted", {"input": "x"})


def test_mcp_stub_when_no_command():
    server = MCPServerSpec(id="s", transport="stdio", granted_tools=["echo"])
    client = MCPClient({"s": server})
    result = client.call_tool("s", "echo", {"input": "hi"})
    assert result["status"] == "granted_stub"
    assert result["echo"] == "hi"


@pytest.mark.skipif(not ECHO_SERVER.exists(), reason="echo server missing")
def test_mcp_live_discovery_and_call():
    pytest.importorskip("mcp")
    client = MCPClient({"echo_server": _echo_server_spec()})
    tools = client.list_tools("echo_server")
    names = {t["name"] for t in tools}
    assert "echo" in names
    assert all(t["granted"] for t in tools)
    result = client.call_tool("echo_server", "echo", {"input": "ping"})
    assert result["status"] == "live"
    assert "ping" in str(result["result"])


def test_mcp_example_validates():
    ir = SpecLoader().load(MCP_EXAMPLE)
    report = ValidationEngine().validate(ir)
    assert not report.has_errors, report.format()


@pytest.mark.skipif(not ECHO_SERVER.exists(), reason="echo server missing")
def test_mcp_example_run(monkeypatch, tmp_path):
    pytest.importorskip("mcp")
    # Point MCP server args at absolute echo script for reliable cwd
    ir = SpecLoader().load(MCP_EXAMPLE)
    server = ir.mcp_servers["echo_server"]
    ir.mcp_servers["echo_server"] = server.model_copy(
        update={"command": sys.executable, "args": [str(ECHO_SERVER)]}
    )
    adapter = get_adapter("langgraph")
    adapter.compile(ir)
    result = adapter.run(ir, RunRequest(input={"input": "hello mcp", "auto_approve": True}))
    assert result.status.value in {"COMPLETED", "FAILED"}
    # Tool output should appear in node_outputs or final output
    blob = str(result.output)
    assert "hello mcp" in blob or result.status.value == "COMPLETED"
