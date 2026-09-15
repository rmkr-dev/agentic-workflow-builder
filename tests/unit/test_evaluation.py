"""Golden-file / schema evaluation tests."""

from __future__ import annotations

import json
from pathlib import Path

from agentforge.evaluation import EvaluationEngine
from agentforge.parser.loader import SpecLoader

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_golden_pass():
    ir = SpecLoader().load(EXAMPLES / "01-single" / "workflow.yaml")
    report = EvaluationEngine().evaluate(
        ir,
        {"output": "[assistant] You are a concise assistant: hello"},
        golden=FIXTURES / "golden_pass.json",
    )
    assert report.passed
    assert "golden" in report.mode
    assert report.details["golden"]["passed"] is True


def test_golden_fail():
    ir = SpecLoader().load(EXAMPLES / "01-single" / "workflow.yaml")
    report = EvaluationEngine().evaluate(
        ir,
        {"output": "short ok text"},
        golden=FIXTURES / "golden_fail.json",
    )
    assert not report.passed
    assert report.details["golden"]["passed"] is False


def test_nested_report_schema():
    ir = SpecLoader().load(EXAMPLES / "01-single" / "workflow.yaml")
    ir = ir.model_copy(
        update={
            "evaluation": ir.evaluation.model_copy(
                update={
                    "output_schema": {
                        "type": "object",
                        "required": ["cve_id", "severity"],
                        "properties": {
                            "cve_id": {"type": "string"},
                            "severity": {"type": "string"},
                        },
                    }
                }
            )
        }
    )
    report = EvaluationEngine().evaluate(
        ir,
        {
            "output": json.dumps({"cve_id": "CVE-2024-3094", "severity": "CRITICAL"}),
            "report": {"cve_id": "CVE-2024-3094", "severity": "CRITICAL"},
        },
    )
    assert report.details["schema"]["passed"] is True


def test_llm_judge_mock_safe(monkeypatch):
    monkeypatch.setenv("AGENTFORGE_LLM_MOCK", "1")
    monkeypatch.delenv("AGENTFORGE_LLM_API_KEY", raising=False)
    ir = SpecLoader().load(EXAMPLES / "01-single" / "workflow.yaml")
    report = EvaluationEngine().evaluate(
        ir,
        {"output": "A solid answer"},
        use_llm_judge=True,
    )
    assert "llm_judge" in report.mode
    assert any(s.metric == "llm_judge" for s in report.scores)
