"""NL → workflow spec architect with deterministic fallback."""

from __future__ import annotations

import os
import re
from typing import Any

import yaml

from agentforge.parser.loader import SpecLoader
from agentforge.validator.engine import ValidationEngine


PATTERN_KEYWORDS: list[tuple[str, list[str]]] = [
    ("hitl", ["approve", "human", "hitl", "review gate"]),
    ("evaluator", ["evaluat", "rubric", "score", "qa check"]),
    ("reflection", ["reflect", "critique", "revise", "critic"]),
    ("supervisor", ["supervisor", "orchestrat", "delegate"]),
    ("parallel", ["parallel", "fan-out", "fan out", "concurrent"]),
    ("conditional", ["if ", "condition", "route", "branch"]),
    ("bounded_loop", ["loop", "retry", "until", "iterate"]),
    ("handoff", ["handoff", "hand off", "pass to"]),
    ("hierarchical", ["hierarch", "manager", "team"]),
    ("sequential", ["then", "pipeline", "sequential", "steps"]),
    ("single", ["single", "one agent", "simple"]),
]


class Architect:
    """Design a validated workflow YAML from a natural-language task.

    Uses an optional LLM when AGENTFORGE_LLM_API_KEY is set; otherwise a
    deterministic keyword heuristic produces a valid spec.
    """

    def __init__(self) -> None:
        self.loader = SpecLoader()
        self.validator = ValidationEngine()

    def design(self, task: str, *, pattern: str | None = None, name: str | None = None) -> dict[str, Any]:
        chosen = pattern or self._infer_pattern(task)
        wf_name = name or self._slug(task)
        doc = self._deterministic_spec(task, chosen, wf_name)

        if os.environ.get("AGENTFORGE_LLM_API_KEY") and os.environ.get("AGENTFORGE_LLM_MOCK", "1") != "1":
            # Optional LLM path — still validate; fall back on failure
            try:
                enriched = self._llm_enrich(task, doc)
                ir = self.loader.load(enriched)
                report = self.validator.validate(ir)
                if not report.has_errors:
                    return enriched
            except Exception:
                pass

        ir = self.loader.load(doc)
        report = self.validator.validate(ir)
        if report.has_errors:
            # Ensure START/END etc. via reload after minimal fix
            raise ValueError(report.format())
        return doc

    def design_yaml(self, task: str, **kwargs: Any) -> str:
        return yaml.safe_dump(self.design(task, **kwargs), sort_keys=False)

    def _infer_pattern(self, task: str) -> str:
        lower = task.lower()
        for pattern, keys in PATTERN_KEYWORDS:
            if any(k in lower for k in keys):
                return pattern
        return "sequential"

    def _slug(self, task: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", task.lower()).strip("-")
        return (slug[:40] or "workflow").strip("-")

    def _deterministic_spec(self, task: str, pattern: str, name: str) -> dict[str, Any]:
        agents = [
            {
                "id": "researcher",
                "role": "researcher",
                "system_prompt": f"Research and analyze: {task}",
                "tools": ["echo"],
            },
            {
                "id": "writer",
                "role": "writer",
                "system_prompt": "Write a concise answer from research notes.",
                "tools": [],
            },
        ]
        if pattern == "single":
            agents = [agents[0]]
        if pattern == "supervisor":
            agents = [
                {
                    "id": "supervisor",
                    "role": "supervisor",
                    "system_prompt": "Delegate work to workers, then finish.",
                    "tools": [],
                },
                *agents,
            ]
        if pattern == "reflection":
            agents = [
                agents[0],
                {
                    "id": "critic",
                    "role": "critic",
                    "system_prompt": "Critique the draft and set needs_revision.",
                    "tools": [],
                },
            ]

        nodes: list[dict[str, Any]]
        edges: list[dict[str, Any]]
        if pattern == "single":
            nodes = [
                {"id": "start", "type": "START"},
                {"id": "researcher", "type": "AGENT", "agent": "researcher"},
                {"id": "end", "type": "END"},
            ]
            edges = [
                {"source": "start", "target": "researcher"},
                {"source": "researcher", "target": "end"},
            ]
        elif pattern == "parallel":
            nodes = [
                {"id": "start", "type": "START"},
                {"id": "fanout", "type": "PARALLEL", "parallel_of": ["researcher", "writer"]},
                {"id": "researcher", "type": "AGENT", "agent": "researcher"},
                {"id": "writer", "type": "AGENT", "agent": "writer"},
                {"id": "join", "type": "JOIN", "join_of": ["researcher", "writer"]},
                {"id": "end", "type": "END"},
            ]
            edges = [
                {"source": "start", "target": "fanout"},
                {"source": "fanout", "target": "researcher"},
                {"source": "fanout", "target": "writer"},
                {"source": "researcher", "target": "join"},
                {"source": "writer", "target": "join"},
                {"source": "join", "target": "end"},
            ]
        elif pattern == "hitl":
            nodes = [
                {"id": "start", "type": "START"},
                {"id": "researcher", "type": "AGENT", "agent": "researcher"},
                {
                    "id": "approve",
                    "type": "HUMAN_APPROVAL",
                    "approval_message": f"Approve result for: {task}?",
                },
                {"id": "end", "type": "END"},
            ]
            edges = [
                {"source": "start", "target": "researcher"},
                {"source": "researcher", "target": "approve"},
                {"source": "approve", "target": "end"},
            ]
        elif pattern == "evaluator":
            nodes = [
                {"id": "start", "type": "START"},
                {"id": "writer", "type": "AGENT", "agent": "writer"},
                {
                    "id": "evaluate",
                    "type": "EVALUATOR",
                    "evaluator_rubric": "Correctness, completeness, safety",
                },
                {"id": "end", "type": "END"},
            ]
            edges = [
                {"source": "start", "target": "writer"},
                {"source": "writer", "target": "evaluate"},
                {"source": "evaluate", "target": "end"},
            ]
        elif pattern == "conditional":
            nodes = [
                {"id": "start", "type": "START"},
                {
                    "id": "condition",
                    "type": "CONDITION",
                    "condition": "route == 'research'",
                    "routes": {"true": "researcher", "false": "writer"},
                },
                {"id": "researcher", "type": "AGENT", "agent": "researcher"},
                {"id": "writer", "type": "AGENT", "agent": "writer"},
                {"id": "end", "type": "END"},
            ]
            edges = [
                {"source": "start", "target": "condition"},
                {"source": "condition", "target": "researcher", "label": "true"},
                {"source": "condition", "target": "writer", "label": "false"},
                {"source": "researcher", "target": "end"},
                {"source": "writer", "target": "end"},
            ]
        else:
            # sequential default
            nodes = [
                {"id": "start", "type": "START"},
                {"id": "researcher", "type": "AGENT", "agent": "researcher"},
                {"id": "writer", "type": "AGENT", "agent": "writer"},
                {"id": "end", "type": "END"},
            ]
            edges = [
                {"source": "start", "target": "researcher"},
                {"source": "researcher", "target": "writer"},
                {"source": "writer", "target": "end"},
            ]

        return {
            "apiVersion": "agentforge/v1",
            "kind": "Workflow",
            "metadata": {
                "name": name,
                "description": task,
                "version": "0.1.0",
                "tags": ["designed", pattern],
            },
            "spec": {
                "pattern": pattern if pattern != "bounded_loop" else "bounded_loop",
                "runtime": "langgraph",
                "agents": agents,
                "tools": [
                    {
                        "id": "echo",
                        "kind": "deterministic",
                        "deterministic_fn": "echo",
                        "description": "Echo input",
                        "permissions": {},
                    }
                ],
                "nodes": nodes,
                "edges": edges,
                "policies": {
                    "tool": {"default_deny": True, "allowed_tools": ["echo"]},
                    "budget": {"max_steps": 50, "max_llm_calls": 30, "max_tool_calls": 30},
                },
                "evaluation": {
                    "enabled": pattern == "evaluator",
                    "rubric": "Correctness and safety",
                    "pass_threshold": 0.7,
                },
            },
        }

    def _llm_enrich(self, task: str, doc: dict[str, Any]) -> dict[str, Any]:
        # Placeholder enrichment: attach design note; real LLM optional
        doc = dict(doc)
        meta = dict(doc.get("metadata") or {})
        meta["description"] = f"{task} (llm-enriched)"
        doc["metadata"] = meta
        return doc
