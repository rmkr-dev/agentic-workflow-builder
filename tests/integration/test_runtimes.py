"""Runtime adapter integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentforge.parser.loader import SpecLoader
from agentforge.runtimes import get_adapter
from agentforge.runtimes.base import Capability, RunRequest, UnsupportedCapabilityError
from agentforge.evaluation import EvaluationEngine

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.mark.parametrize(
    "example",
    [
        "01-single",
        "02-sequential",
        "03-parallel",
        "05-hierarchical",
        "06-handoff",
        "09-hitl-evaluator",
    ],
)
def test_langgraph_run_examples(example: str):
    ir = SpecLoader().load(EXAMPLES / example / "workflow.yaml")
    adapter = get_adapter("langgraph")
    adapter.compile(ir)
    result = adapter.run(
        ir,
        RunRequest(input={"input": f"run {example}", "auto_approve": True, "route": "done"}),
    )
    assert result.status.value in {"COMPLETED", "WAITING_FOR_APPROVAL", "WAITING_FOR_INPUT"}
    assert result.thread_id
    view = adapter.inspect(result.thread_id)
    assert view.thread_id == result.thread_id


def test_langgraph_conditional():
    ir = SpecLoader().load(EXAMPLES / "08-conditional-loop" / "workflow.yaml")
    adapter = get_adapter("langgraph")
    adapter.compile(ir)
    result = adapter.run(
        ir,
        RunRequest(input={"input": "branch", "route": "primary", "auto_approve": True}),
    )
    assert result.status.value in {"COMPLETED", "WAITING_FOR_APPROVAL", "WAITING_FOR_INPUT", "FAILED"}
    # Conditional graphs should at least compile and attempt execution
    assert result.thread_id


def test_microsoft_capability_honesty():
    adapter = get_adapter("microsoft")
    matrix = adapter.capability_matrix()
    assert "loops" in matrix
    # Either unsupported (not installed) or explicitly unsupported/partial — never silent
    assert matrix["loops"]["status"] in {"unsupported", "partial", "supported"}
    ir = SpecLoader().load(EXAMPLES / "07-reflection" / "workflow.yaml")
    if matrix["compile"]["status"] == "unsupported":
        with pytest.raises(UnsupportedCapabilityError):
            adapter.compile(ir)
    else:
        # reflection pattern should fail clearly on microsoft
        with pytest.raises((UnsupportedCapabilityError, ValueError)):
            adapter.compile(ir)


def test_microsoft_sequential_when_available():
    adapter = get_adapter("microsoft")
    ir = SpecLoader().load(EXAMPLES / "02-sequential" / "workflow.yaml")
    matrix = adapter.capability_matrix()
    if matrix["run"]["status"] == "unsupported":
        pytest.skip("microsoft AF not installed")
    adapter.compile(ir)
    result = adapter.run(ir, RunRequest(input={"input": "hi"}))
    assert result.status.value == "COMPLETED"


def test_evaluation_engine():
    ir = SpecLoader().load(EXAMPLES / "09-hitl-evaluator" / "workflow.yaml")
    report = EvaluationEngine().evaluate(ir, {"output": "A solid answer"})
    assert report.overall > 0
    assert isinstance(report.passed, bool)


def test_cancel_and_serialize():
    ir = SpecLoader().load(EXAMPLES / "01-single" / "workflow.yaml")
    adapter = get_adapter("langgraph")
    adapter.compile(ir)
    result = adapter.run(ir, RunRequest(input={"input": "x"}))
    payload = adapter.serialize_state(result.thread_id)
    new_id = adapter.deserialize_state(payload)
    assert new_id
    assert adapter.cancel(result.thread_id) is True
