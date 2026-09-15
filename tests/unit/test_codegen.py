"""Codegen IR fidelity tests."""

from __future__ import annotations

from pathlib import Path

from agentforge.generator.project import ProjectGenerator
from agentforge.parser.loader import SpecLoader

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def test_generated_docs_mention_agents_and_tools(tmp_path: Path):
    ir = SpecLoader().load(EXAMPLES / "02-sequential" / "workflow.yaml")
    project = ProjectGenerator().generate(ir, output_dir=tmp_path / "seq")
    readme = (project.path / "README.md").read_text(encoding="utf-8")
    assert "researcher" in readme
    assert "writer" in readme
    agents_md = (project.path / "docs" / "AGENTS.md").read_text(encoding="utf-8")
    assert "researcher" in agents_md


def test_generated_hitl_tests(tmp_path: Path):
    ir = SpecLoader().load(EXAMPLES / "09-hitl-evaluator" / "workflow.yaml")
    project = ProjectGenerator().generate(ir, output_dir=tmp_path / "hitl")
    tests = (project.path / "tests" / "test_workflow.py").read_text(encoding="utf-8")
    assert "test_hitl_auto_approve" in tests or "test_run_completes" in tests
    graph = (project.path / "src" / "workflow_app" / "graph.py").read_text(encoding="utf-8")
    assert "approved" in graph
