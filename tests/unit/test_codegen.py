"""Codegen IR fidelity tests."""

from __future__ import annotations

import tomllib
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
    assert "interrupt" in graph


def test_generated_security_fixtures(tmp_path: Path):
    ir = SpecLoader().load(EXAMPLES / "12-security-incident" / "workflow.yaml")
    project = ProjectGenerator().generate(ir, output_dir=tmp_path / "cve")
    tools = (project.path / "src" / "workflow_app" / "tools.py").read_text(encoding="utf-8")
    assert "nvd_lookup" in tools
    assert "assemble_cve_report" in tools
    graph = (project.path / "src" / "workflow_app" / "graph.py").read_text(encoding="utf-8")
    assert "interrupt" in graph
    assert "add_conditional_edges" in graph
    assert "needs_revision" in graph
    state_py = (project.path / "src" / "workflow_app" / "state.py").read_text(encoding="utf-8")
    assert "_last" in state_py
    assert "_merge_dicts" in state_py
    pyproject = (project.path / "pyproject.toml").read_text(encoding="utf-8")
    parsed = tomllib.loads(pyproject)
    assert parsed["project"]["name"] == "cve-incident-pipeline"
    assert "\n" not in parsed["project"]["description"]
