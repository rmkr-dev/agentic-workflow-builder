"""Tool registry: python, REST, CLI, deterministic, MCP."""

from __future__ import annotations

import importlib
import subprocess
from collections.abc import Callable
from typing import Any

import httpx

from agentforge.ir.models import WorkflowIR
from agentforge.mcp.client import MCPClient
from agentforge.schema import ToolKind, ToolSpec
from agentforge.tools.fixtures import (
    assemble_cve_report,
    cloud_exposure,
    iam_impact,
    nvd_lookup,
    ticket_note,
)


class ToolPermissionError(PermissionError):
    pass


class ToolRegistry:
    def __init__(self, ir: WorkflowIR) -> None:
        self.ir = ir
        self.tools = ir.tools
        self.mcp = MCPClient(ir.mcp_servers)
        self._deterministic: dict[str, Callable[[dict[str, Any]], Any]] = {
            "echo": lambda s: s.get("input", ""),
            "upper": lambda s: str(s.get("input", "")).upper(),
            "lower": lambda s: str(s.get("input", "")).lower(),
            "word_count": lambda s: len(str(s.get("input", "")).split()),
            "identity": lambda s: dict(s),
            "nvd_lookup": nvd_lookup,
            "cloud_exposure": cloud_exposure,
            "iam_impact": iam_impact,
            "assemble_cve_report": assemble_cve_report,
            "ticket_note": ticket_note,
        }

    def invoke(self, tool_id: str, state: dict[str, Any]) -> Any:
        # Agent-as-tool
        if tool_id in self.ir.agents and tool_id not in self.tools:
            agent = self.ir.agents[tool_id]
            return f"[agent-as-tool:{tool_id}] {agent.description or agent.role}: {state.get('input', '')}"

        tool = self.tools.get(tool_id)
        if not tool:
            known = sorted(self.tools) or ["(none declared in spec.tools)"]
            raise KeyError(
                f"Unknown tool '{tool_id}'. Declared tools: {known}. "
                "Add it under spec.tools and policies.tool.allowed_tools, "
                "or use kind: python with entrypoint: module:function."
            )

        self._enforce_permissions(tool)

        if tool.kind == ToolKind.DETERMINISTIC:
            fn = self._deterministic.get(tool.deterministic_fn or "")
            if not fn:
                known = sorted(self._deterministic)
                raise ValueError(
                    f"Unknown deterministic_fn '{tool.deterministic_fn}'. "
                    f"Built-ins: {known}. For custom logic use kind: python "
                    "entrypoint: your_module:function (credentials via env only)."
                )
            return fn(state)

        if tool.kind == ToolKind.REST:
            if not tool.permissions.allow_network:
                raise ToolPermissionError(f"Tool '{tool_id}' network access denied")
            url = tool.url or ""
            host_ok = not tool.permissions.allowed_hosts or any(
                h in url for h in tool.permissions.allowed_hosts
            )
            if not host_ok:
                raise ToolPermissionError(f"Host not allowlisted for tool '{tool_id}'")
            with httpx.Client(timeout=30.0) as client:
                resp = client.request(tool.method, url, json=tool.config.get("json"))
                resp.raise_for_status()
                try:
                    return resp.json()
                except Exception:
                    return resp.text

        if tool.kind == ToolKind.CLI:
            if not tool.permissions.allow_shell:
                raise ToolPermissionError(
                    f"CLI tool '{tool_id}' requires permissions.allow_shell: true "
                    "(unrestricted shell is denied by default)"
                )
            cmd = tool.command or ""
            args = list(tool.args)
            if tool.permissions.allowed_commands and cmd not in tool.permissions.allowed_commands:
                raise ToolPermissionError(f"Command '{cmd}' not in allowed_commands")
            completed = subprocess.run(  # noqa: S603
                [cmd, *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            return {
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }

        if tool.kind == ToolKind.PYTHON:
            return self._invoke_python(tool, state)

        if tool.kind == ToolKind.MCP:
            return self.mcp.call_tool(tool.mcp_server or "", tool.mcp_tool or "", state)

        raise ValueError(f"Unsupported tool kind {tool.kind}")

    def _enforce_permissions(self, tool: ToolSpec) -> None:
        pol = self.ir.policies.tool
        if pol.default_deny and pol.allowed_tools and tool.id not in pol.allowed_tools:
            raise ToolPermissionError(f"Tool '{tool.id}' blocked by tool policy allowlist")
        if tool.kind == ToolKind.CLI and self.ir.policies.security.allow_unrestricted_shell is False:
            if tool.permissions.allow_shell and not tool.permissions.allowed_commands:
                raise ToolPermissionError(
                    f"CLI tool '{tool.id}' must set allowed_commands when unrestricted shell is disabled"
                )

    def _invoke_python(self, tool: ToolSpec, state: dict[str, Any]) -> Any:
        entry = tool.entrypoint or ""
        if ":" not in entry:
            raise ValueError("Python entrypoint must be 'module:function'")
        module_name, func_name = entry.split(":", 1)
        # Restrict to generated project modules by default
        if module_name.startswith("."):
            raise ToolPermissionError("Relative imports not allowed")
        mod = importlib.import_module(module_name)
        fn = getattr(mod, func_name)
        return fn(state)
