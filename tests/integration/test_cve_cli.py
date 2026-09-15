"""CLI coverage for inspect-spec, input-file, HITL resume, compile compatibility."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentforge.cli.app import app

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
CVE = EXAMPLES / "12-security-incident"
runner = CliRunner()


def test_cli_inspect_workflow_spec():
    result = runner.invoke(app, ["inspect", str(CVE / "workflow.yaml")])
    assert result.exit_code == 0, result.output
    assert "cve-incident-pipeline" in result.output
    assert "nvd_lookup" in result.output
    assert "compatibility" in result.output.lower() or "langgraph" in result.output


def test_cli_compile_json_includes_compatibility(tmp_path: Path):
    out = tmp_path / "ir.json"
    result = runner.invoke(
        app,
        ["--json", "compile", str(CVE / "workflow.yaml"), "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["compatibility"]["ok"] is True
    assert "hitl" in payload["compatibility"]["required"]


def test_cli_cve_run_auto_approve():
    result = runner.invoke(
        app,
        [
            "--json",
            "run",
            str(CVE / "workflow.yaml"),
            "--input-file",
            str(CVE / "input.json"),
            "--auto-approve",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] in {"COMPLETED", "WAITING_FOR_APPROVAL"}
    if payload["status"] == "COMPLETED":
        report = (payload.get("output") or {}).get("report") or {}
        assert report.get("cve_id") == "CVE-2024-3094"


def test_cli_cve_pause_and_resume(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENTFORGE_DATA_DIR", str(tmp_path / "af"))
    paused = runner.invoke(
        app,
        [
            "--json",
            "run",
            str(CVE / "workflow.yaml"),
            "--input-file",
            str(CVE / "input.json"),
        ],
    )
    assert paused.exit_code == 0, paused.output
    payload = json.loads(paused.output)
    assert payload["status"] == "WAITING_FOR_APPROVAL", payload
    tid = payload["thread_id"]
    resumed = runner.invoke(
        app,
        [
            "--json",
            "resume",
            str(CVE / "workflow.yaml"),
            "--thread-id",
            tid,
            "--approve",
        ],
    )
    assert resumed.exit_code == 0, resumed.output
    done = json.loads(resumed.output)
    assert done["status"] == "COMPLETED", done
    report = (done.get("output") or {}).get("report") or {}
    assert report.get("cve_id") == "CVE-2024-3094"
    assert report.get("remediation_actions")
