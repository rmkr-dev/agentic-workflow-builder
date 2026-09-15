"""CLI smoke tests."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from agentforge.cli.app import app, normalize_cli_argv

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
    assert '"mode"' in result.output or "mode" in result.output


def test_cli_run_mode_banner():
    result = runner.invoke(
        app,
        ["run", str(EXAMPLES / "01-single" / "workflow.yaml"), "--input", "banner"],
    )
    assert result.exit_code == 0, result.output
    assert "mode=mock" in result.output


def test_cli_global_flag_after_subcommand():
    """Global flags after the subcommand are accepted via argv normalization."""
    args = normalize_cli_argv(
        [
            "run",
            str(EXAMPLES / "01-single" / "workflow.yaml"),
            "--non-interactive",
            "--input",
            "after-flag",
        ]
    )
    assert args[0] == "--non-interactive"
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert "mode=mock" in result.output


def test_cli_help_ascii_safe():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "non-interactive" in result.output
    assert "Compile" in result.output


def test_cli_doctor_includes_mode():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "mode=mock" in result.output or "llm_mode" in result.output


def test_cli_doctor_json_mode():
    result = runner.invoke(app, ["--json", "doctor"])
    assert result.exit_code == 0, result.output
    assert "mode" in result.output


def test_cli_supervisor_run_executes_workers():
    result = runner.invoke(
        app,
        [
            "--json",
            "run",
            str(EXAMPLES / "04-supervisor" / "workflow.yaml"),
            "--input",
            "research then write",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "worker_research" in result.output
    assert "worker_write" in result.output


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
