"""CLI smoke tests."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from agentforge.cli.app import app

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
runner = CliRunner()


def test_cli_validate():
    result = runner.invoke(app, ["validate", str(EXAMPLES / "01-single" / "workflow.yaml")])
    assert result.exit_code == 0, result.output


def test_cli_compile_and_export(tmp_path: Path):
    out = tmp_path / "ir.json"
    result = runner.invoke(
        app,
        ["compile", str(EXAMPLES / "01-single" / "workflow.yaml"), "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    result = runner.invoke(
        app,
        ["export", str(EXAMPLES / "01-single" / "workflow.yaml"), "--format", "mermaid"],
    )
    assert result.exit_code == 0
    assert "flowchart TD" in result.output


def test_cli_design(tmp_path: Path):
    out = tmp_path / "workflow.yaml"
    result = runner.invoke(
        app,
        ["design", "--task", "sequential research and write a report", "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()


def test_cli_run_json():
    result = runner.invoke(
        app,
        [
            "--json",
            "run",
            str(EXAMPLES / "01-single" / "workflow.yaml"),
            "--input",
            "hello cli",
        ],
    )
    assert result.exit_code == 0, result.output


def test_cli_doctor():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output


def test_cli_generate(tmp_path: Path):
    out = tmp_path / "gen"
    result = runner.invoke(
        app,
        [
            "generate",
            str(EXAMPLES / "01-single" / "workflow.yaml"),
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (out / "README.md").exists()
