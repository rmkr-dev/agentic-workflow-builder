"""Fixture tools and CVE example tests."""

from __future__ import annotations

from pathlib import Path

from agentforge.architect import Architect
from agentforge.parser.loader import SpecLoader
from agentforge.runtimes.base import RunRequest
from agentforge.runtimes.base.helpers import SQLiteRunStore
from agentforge.runtimes.langgraph import LangGraphAdapter
from agentforge.runtimes.langgraph.checkpointer import DurableMemorySaver
from agentforge.schema import NodeType
from agentforge.tools.fixtures import cloud_exposure, extract_cve_id, iam_impact, nvd_lookup
from agentforge.tools.registry import ToolRegistry
from agentforge.validator.engine import ValidationEngine

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "12-security-incident"
WF = EXAMPLE / "workflow.yaml"
INPUT = EXAMPLE / "input.json"


def test_nvd_fixture_catalog():
    rec = nvd_lookup({"cve_id": "CVE-2024-3094"})
    assert rec["cve_id"] == "CVE-2024-3094"
    assert rec["source"] == "fixture_catalog"
    assert rec["severity"] == "CRITICAL"
    unknown = nvd_lookup({"cve_id": "CVE-2099-0001"})
    assert unknown["in_catalog"] is False


def test_extract_cve_from_text_and_payload():
    assert extract_cve_id({"input": "please look at CVE-2024-3400 today"}) == "CVE-2024-3400"
    assert extract_cve_id({"payload": {"cve_id": "cve-2021-44228"}}) == "CVE-2021-44228"


def test_cloud_and_iam_fixtures():
    state = {
        "payload": {
            "cve_id": "CVE-2024-3094",
            "cloud": {"provider": "aws", "assets": [{"type": "ec2", "public": True}]},
            "identity": {"roles": ["Admin"], "overprivileged": True},
        }
    }
    cloud = cloud_exposure(state)
    assert cloud["exposure_severity"] == "critical"
    iam = iam_impact(state)
    assert iam["admin_equivalent"] is True


def test_example_12_validates():
    ir = SpecLoader().load(WF)
    report = ValidationEngine().validate(ir)
    assert not report.has_errors, report.format()
    assert "nvd_lookup" in ir.tools
    assert any(n.type == NodeType.HUMAN_APPROVAL for n in ir.nodes)
    assert any(n.type == NodeType.PARALLEL for n in ir.nodes)
    assert any(n.type == NodeType.EVALUATOR for n in ir.nodes)


def test_example_12_tools_invoke():
    ir = SpecLoader().load(WF)
    registry = ToolRegistry(ir)
    state = {"cve_id": "CVE-2024-3094", "payload": {"cve_id": "CVE-2024-3094"}}
    rec = registry.invoke("nvd_lookup", state)
    assert rec["cve_id"] == "CVE-2024-3094"


def test_architect_cve_pipeline():
    doc = Architect().design(
        "Analyze a CVE with parallel vulnerability, cloud, and IAM specialists, "
        "critic review, quality evaluation, and human approval before remediation"
    )
    ir = SpecLoader().load(doc)
    report = ValidationEngine().validate(ir)
    assert not report.has_errors, report.format()
    assert "planner" in ir.agents
    assert "vuln_researcher" in ir.agents
    assert "cloud_analyst" in ir.agents
    assert "iam_analyst" in ir.agents
    assert "critic" in ir.agents
    assert "finalizer" in ir.agents
    types = {n.type for n in ir.nodes}
    assert NodeType.PARALLEL in types
    assert NodeType.JOIN in types
    assert NodeType.HUMAN_APPROVAL in types
    assert NodeType.EVALUATOR in types
    assert "nvd_lookup" in ir.tools
    assert ir.policies.tool.default_deny is True


def test_example_12_hitl_pause_and_resume_across_adapters(tmp_path: Path):
    ir = SpecLoader().load(WF)
    ckpt = tmp_path / "ckpt.pkl"
    store = SQLiteRunStore(tmp_path / "runs.db")
    adapter1 = LangGraphAdapter(store=store, checkpointer=DurableMemorySaver(ckpt))
    adapter1.compile(ir)
    paused = adapter1.run(
        ir,
        RunRequest(
            input={
                "cve_id": "CVE-2024-3094",
                "cloud": {"provider": "aws", "assets": [{"type": "ec2", "public": True}]},
                "identity": {"roles": ["Admin"], "overprivileged": True},
                "auto_approve": False,
            }
        ),
    )
    assert paused.status.value == "WAITING_FOR_APPROVAL", paused.error
    assert paused.thread_id

    adapter2 = LangGraphAdapter(store=store, checkpointer=DurableMemorySaver(ckpt))
    adapter2.compile(ir)
    resumed = adapter2.resume(ir, RunRequest(thread_id=paused.thread_id, approval=True))
    assert resumed.status.value == "COMPLETED", resumed.error
    report = (resumed.output or {}).get("report") or {}
    assert report.get("cve_id") == "CVE-2024-3094"
    assert report.get("approval", {}).get("approved") is True
    assert report.get("remediation_actions")
