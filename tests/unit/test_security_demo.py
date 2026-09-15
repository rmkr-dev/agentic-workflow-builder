"""Security demo: fail-closed on ungated CLI / default_deny."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentforge.parser.loader import SpecLoader
from agentforge.runtimes import get_adapter
from agentforge.runtimes.base import RunRequest
from agentforge.tools.registry import ToolPermissionError, ToolRegistry
from agentforge.validator.engine import ValidationEngine

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "11-security" / "workflow.yaml"


def test_security_example_validates():
    ir = SpecLoader().load(EXAMPLE)
    report = ValidationEngine().validate(ir)
    assert not report.has_errors, report.format()
    assert ir.policies.tool.default_deny is True


def test_ungated_cli_denied():
    ir = SpecLoader().load(EXAMPLE)
    registry = ToolRegistry(ir)
    with pytest.raises(ToolPermissionError):
        registry.invoke("ungated_shell", {"input": "probe"})


def test_unlisted_tool_default_deny():
    ir = SpecLoader().load(EXAMPLE)
    registry = ToolRegistry(ir)
    with pytest.raises(ToolPermissionError):
        registry.invoke("unlisted_cli", {"input": "probe"})


def test_allowlisted_echo_ok():
    ir = SpecLoader().load(EXAMPLE)
    registry = ToolRegistry(ir)
    assert registry.invoke("safe_echo", {"input": "ok"}) == "ok"


def test_security_run_fails_closed():
    ir = SpecLoader().load(EXAMPLE)
    adapter = get_adapter("langgraph")
    adapter.compile(ir)
    result = adapter.run(ir, RunRequest(input={"input": "probe", "auto_approve": True}))
    # Tool permission errors should surface as FAILED (or error in output)
    assert result.status.value == "FAILED" or "error" in str(result.output).lower() or (
        result.output or {}
    ).get("error")
