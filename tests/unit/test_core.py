"""Unit tests for parser, validator, IR, and SDK."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentforge import WorkflowCompiler
from agentforge.architect import Architect
from agentforge.linter import Linter
from agentforge.parser.loader import SpecLoader
from agentforge.schema import NodeType
from agentforge.validator.engine import ValidationEngine

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.mark.parametrize(
    "example",
    sorted(p.name for p in EXAMPLES.iterdir() if p.is_dir()),
)
def test_examples_parse_and_validate(example: str):
    path = EXAMPLES / example / "workflow.yaml"
    ir = SpecLoader().load(path)
    report = ValidationEngine().validate(ir)
    assert not report.has_errors, report.format()
    assert ir.start_nodes()
    assert ir.end_nodes()
    assert any(n.type == NodeType.START for n in ir.nodes)


def test_sdk_compile_generate(tmp_path: Path):
    compiler = WorkflowCompiler()
    ir = compiler.compile(EXAMPLES / "01-single" / "workflow.yaml")
    assert ir.name == "single-agent"
    project = compiler.generate(ir, output_dir=tmp_path / "proj")
    assert (project.path / "README.md").exists()
    assert (project.path / "src" / "workflow_app" / "graph.py").exists()
    assert (project.path / "tests" / "test_workflow.py").exists()


def test_architect_design_deterministic():
    doc = Architect().design("Build a sequential research then write pipeline")
    ir = SpecLoader().load(doc)
    report = ValidationEngine().validate(ir)
    assert not report.has_errors, report.format()


def test_linter_runs():
    ir = SpecLoader().load(EXAMPLES / "03-parallel" / "workflow.yaml")
    report = Linter().lint(ir)
    assert isinstance(report.diagnostics, list)


def test_mermaid_export():
    ir = SpecLoader().load(EXAMPLES / "02-sequential" / "workflow.yaml")
    text = ir.to_mermaid()
    assert "flowchart TD" in text
    assert "researcher" in text
