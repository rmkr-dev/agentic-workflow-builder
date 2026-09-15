"""Architect multi-intent composition tests."""

from __future__ import annotations

from agentforge.architect import Architect
from agentforge.parser.loader import SpecLoader
from agentforge.schema import NodeType
from agentforge.validator.engine import ValidationEngine


def test_multi_intent_research_write_approval():
    doc = Architect().design("Research then write a summary with human approval")
    ir = SpecLoader().load(doc)
    report = ValidationEngine().validate(ir)
    assert not report.has_errors, report.format()

    agent_ids = set(ir.agents)
    assert "researcher" in agent_ids
    assert "writer" in agent_ids  # must not drop writer when HITL wins
    types = {n.type for n in ir.nodes}
    assert NodeType.HUMAN_APPROVAL in types
    assert NodeType.AGENT in types
    node_ids = {n.id for n in ir.nodes}
    assert "researcher" in node_ids
    assert "writer" in node_ids
    assert "approve" in node_ids


def test_multi_intent_parallel_and_eval():
    doc = Architect().design("Run research and writing in parallel then evaluate quality")
    ir = SpecLoader().load(doc)
    report = ValidationEngine().validate(ir)
    assert not report.has_errors, report.format()
    assert "researcher" in ir.agents
    assert "writer" in ir.agents
    assert any(n.type == NodeType.EVALUATOR for n in ir.nodes)


def test_intents_list_composition():
    intents = Architect()._infer_intents("Research then write with approval and evaluate")
    assert "hitl" in intents or "approve" in "research then write with approval"
    assert "sequential" in intents or "hitl" in intents
