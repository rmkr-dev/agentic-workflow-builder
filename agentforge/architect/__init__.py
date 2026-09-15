"""NL → workflow spec architect with multi-intent composition."""

from __future__ import annotations

import os
import re
from typing import Any

import yaml

from agentforge.parser.loader import SpecLoader
from agentforge.validator.engine import ValidationEngine

# Ordered by specificity for *primary* pattern tagging; composition uses all matches.
INTENT_KEYWORDS: list[tuple[str, list[str]]] = [
    ("hitl", ["approve", "human", "hitl", "review gate", "approval"]),
    ("evaluator", ["evaluat", "rubric", "score", "qa check", "quality check"]),
    ("reflection", ["reflect", "critique", "revise", "critic"]),
    ("supervisor", ["supervisor", "orchestrat", "delegate"]),
    ("parallel", ["parallel", "fan-out", "fan out", "concurrent"]),
    ("conditional", ["if ", "condition", "route", "branch"]),
    ("bounded_loop", ["loop", "retry", "until", "iterate"]),
    ("handoff", ["handoff", "hand off", "pass to"]),
    ("hierarchical", ["hierarch", "manager", "team"]),
    ("sequential", ["then", "pipeline", "sequential", "steps", "research", "write"]),
    ("single", ["single", "one agent", "simple"]),
]

# Intent signals that imply agent roles (independent of pattern keyword winner).
ROLE_SIGNALS: list[tuple[str, list[str]]] = [
    ("researcher", ["research", "investigate", "gather", "search", "analyze"]),
    ("writer", ["write", "draft", "summar", "compose", "author"]),
    ("critic", ["critique", "reflect", "revise", "critic"]),
    ("supervisor", ["supervisor", "orchestrat", "delegate"]),
]


class Architect:
    """Design a validated workflow YAML from a natural-language task.

    Multi-intent tasks (e.g. research + write + approval) compose patterns so
    implied agents are not dropped when HITL/evaluator keywords win first.
    """

    def __init__(self) -> None:
        self.loader = SpecLoader()
        self.validator = ValidationEngine()

    def design(self, task: str, *, pattern: str | None = None, name: str | None = None) -> dict[str, Any]:
        intents = self._infer_intents(task)
        chosen = pattern or self._primary_pattern(intents, task)
        wf_name = name or self._slug(task)
        doc = self._compose_spec(task, chosen, intents, wf_name)

        if os.environ.get("AGENTFORGE_LLM_API_KEY") and os.environ.get("AGENTFORGE_LLM_MOCK", "1") != "1":
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
            raise ValueError(report.format())
        return doc

    def design_yaml(self, task: str, **kwargs: Any) -> str:
        return yaml.safe_dump(self.design(task, **kwargs), sort_keys=False)

    def _infer_intents(self, task: str) -> list[str]:
        lower = task.lower()
        found: list[str] = []
        for pattern, keys in INTENT_KEYWORDS:
            if any(k in lower for k in keys):
                found.append(pattern)
        if not found:
            found = ["sequential"]
        # Deduplicate while preserving order
        seen: set[str] = set()
        ordered: list[str] = []
        for p in found:
            if p not in seen:
                seen.add(p)
                ordered.append(p)
        return ordered

    def _primary_pattern(self, intents: list[str], task: str) -> str:
        # Prefer structural patterns that wrap pipelines when composed.
        priority = [
            "supervisor",
            "hierarchical",
            "parallel",
            "reflection",
            "hitl",
            "evaluator",
            "conditional",
            "bounded_loop",
            "handoff",
            "sequential",
            "single",
        ]
        for p in priority:
            if p in intents:
                # hitl/evaluator alone without research/write → keep; with pipeline → sequential base
                if p in {"hitl", "evaluator"} and any(
                    x in intents for x in ("sequential", "parallel", "supervisor", "reflection")
                ):
                    continue
                return p
        return intents[0] if intents else "sequential"

    def _infer_roles(self, task: str, intents: list[str]) -> list[str]:
        lower = task.lower()
        roles: list[str] = []
        for role, keys in ROLE_SIGNALS:
            if any(k in lower for k in keys):
                roles.append(role)
        if "supervisor" in intents and "supervisor" not in roles:
            roles.insert(0, "supervisor")
        if "reflection" in intents and "critic" not in roles:
            roles.append("critic")
        if not roles:
            roles = ["researcher"]
        # Always keep writer when research+write style sequential pipeline is implied
        if "researcher" in roles and "writer" not in roles:
            if any(k in lower for k in ("write", "draft", "summar", "then", "pipeline")):
                roles.append("writer")
        # Multi-step without explicit single → ensure writer for composition with HITL
        if "hitl" in intents or "evaluator" in intents:
            if "researcher" not in roles and "writer" not in roles:
                roles = ["researcher", "writer"]
            elif "writer" not in roles and "researcher" in roles:
                roles.append("writer")
        # Deduplicate
        seen: set[str] = set()
        out: list[str] = []
        for r in roles:
            if r not in seen:
                seen.add(r)
                out.append(r)
        return out

    def _slug(self, task: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", task.lower()).strip("-")
        return (slug[:40] or "workflow").strip("-")

    def _agent_defs(self, task: str, roles: list[str]) -> list[dict[str, Any]]:
        prompts = {
            "researcher": f"Research and analyze: {task}",
            "writer": "Write a concise answer from research notes.",
            "critic": "Critique the draft and set needs_revision when improvements are needed.",
            "supervisor": "Delegate work to workers, then finish.",
        }
        agents: list[dict[str, Any]] = []
        for role in roles:
            tools = ["echo"] if role == "researcher" else []
            agents.append(
                {
                    "id": role,
                    "role": role,
                    "system_prompt": prompts.get(role, f"Assist with: {task}"),
                    "tools": tools,
                }
            )
        return agents

    def _compose_spec(
        self,
        task: str,
        pattern: str,
        intents: list[str],
        name: str,
    ) -> dict[str, Any]:
        roles = self._infer_roles(task, intents)
        # Pattern overrides for dedicated structures
        if pattern == "single":
            roles = roles[:1] or ["researcher"]
        if pattern == "supervisor" and "supervisor" not in roles:
            roles = ["supervisor", *[r for r in roles if r != "supervisor"]]
        if pattern == "reflection" and "critic" not in roles:
            roles = [r for r in roles if r != "critic"] + ["critic"]

        agents = self._agent_defs(task, roles)
        pipeline = [r for r in roles if r not in {"supervisor"}]
        if not pipeline:
            pipeline = ["researcher"]

        want_hitl = "hitl" in intents
        want_eval = "evaluator" in intents
        want_parallel = pattern == "parallel" or (
            "parallel" in intents and pattern not in {"supervisor", "hierarchical"}
        )

        nodes: list[dict[str, Any]] = [{"id": "start", "type": "START"}]
        edges: list[dict[str, Any]] = []

        if pattern == "single":
            aid = pipeline[0]
            nodes.append({"id": aid, "type": "AGENT", "agent": aid})
            edges.append({"source": "start", "target": aid})
            last = aid
        elif want_parallel and len(pipeline) >= 2:
            fan_ids = pipeline[:2]
            nodes.append({"id": "fanout", "type": "PARALLEL", "parallel_of": fan_ids})
            for aid in fan_ids:
                nodes.append({"id": aid, "type": "AGENT", "agent": aid})
            nodes.append({"id": "join", "type": "JOIN", "join_of": fan_ids})
            edges.append({"source": "start", "target": "fanout"})
            for aid in fan_ids:
                edges.append({"source": "fanout", "target": aid})
                edges.append({"source": aid, "target": "join"})
            last = "join"
        elif pattern == "conditional":
            nodes.append(
                {
                    "id": "condition",
                    "type": "CONDITION",
                    "condition": "route == 'research'",
                    "routes": {
                        "true": pipeline[0],
                        "false": pipeline[1] if len(pipeline) > 1 else pipeline[0],
                    },
                }
            )
            for aid in pipeline[:2]:
                if not any(n["id"] == aid for n in nodes):
                    nodes.append({"id": aid, "type": "AGENT", "agent": aid})
            edges.append({"source": "start", "target": "condition"})
            edges.append({"source": "condition", "target": pipeline[0], "label": "true"})
            alt = pipeline[1] if len(pipeline) > 1 else pipeline[0]
            edges.append({"source": "condition", "target": alt, "label": "false"})
            # Both branches continue to shared tail
            last_candidates = list(dict.fromkeys([pipeline[0], alt]))
            last = last_candidates[0]
            # Wire branches into HITL/eval/end via a join-like writer if two distinct
            if len(last_candidates) == 2 and not want_hitl and not want_eval:
                for aid in last_candidates:
                    edges.append({"source": aid, "target": "end"})
                nodes.append({"id": "end", "type": "END"})
                return self._finalize_doc(task, pattern, intents, name, agents, nodes, edges)
            # Merge into sequential tail starting after both
            merge = "writer" if "writer" in pipeline else pipeline[-1]
            if merge not in last_candidates:
                nodes.append({"id": merge, "type": "AGENT", "agent": merge})
                for aid in last_candidates:
                    edges.append({"source": aid, "target": merge})
                last = merge
            else:
                # Use second agent as merge target from first if needed
                last = last_candidates[-1]
                if last_candidates[0] != last:
                    edges.append({"source": last_candidates[0], "target": last})
        elif pattern == "supervisor":
            nodes.append({"id": "supervisor", "type": "AGENT", "agent": "supervisor"})
            edges.append({"source": "start", "target": "supervisor"})
            workers = [r for r in pipeline if r != "supervisor"]
            for wid in workers:
                if not any(n["id"] == wid for n in nodes):
                    nodes.append({"id": wid, "type": "AGENT", "agent": wid})
                edges.append({"source": "supervisor", "target": wid})
                edges.append({"source": wid, "target": "supervisor"})
            last = "supervisor"
        else:
            # Sequential (default composition spine)
            prev = "start"
            for aid in pipeline:
                if not any(n["id"] == aid for n in nodes):
                    nodes.append({"id": aid, "type": "AGENT", "agent": aid})
                edges.append({"source": prev, "target": aid})
                prev = aid
            last = prev

        # Compose HITL / evaluator after the pipeline (never drop writer when HITL wins)
        if want_eval:
            nodes.append(
                {
                    "id": "evaluate",
                    "type": "EVALUATOR",
                    "evaluator_rubric": "Correctness, completeness, safety",
                }
            )
            edges.append({"source": last, "target": "evaluate"})
            last = "evaluate"

        if want_hitl:
            nodes.append(
                {
                    "id": "approve",
                    "type": "HUMAN_APPROVAL",
                    "approval_message": f"Approve result for: {task}?",
                }
            )
            edges.append({"source": last, "target": "approve"})
            last = "approve"

        nodes.append({"id": "end", "type": "END"})
        edges.append({"source": last, "target": "end"})

        # Effective pattern tag: prefer composed label
        effective = pattern
        if want_hitl and pattern not in {"hitl"}:
            effective = "hitl" if pattern == "sequential" and want_hitl else pattern
        if want_hitl and "sequential" in intents:
            effective = "hitl"
        tags = ["designed", effective, *intents]

        return self._finalize_doc(task, effective, intents, name, agents, nodes, edges, tags)

    def _finalize_doc(
        self,
        task: str,
        pattern: str,
        intents: list[str],
        name: str,
        agents: list[dict[str, Any]],
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        # Normalize pattern to a schema-known value
        known = {
            "single",
            "sequential",
            "parallel",
            "fan_out_fan_in",
            "supervisor",
            "hierarchical",
            "handoff",
            "reflection",
            "conditional",
            "bounded_loop",
            "subworkflow",
            "agent_as_tool",
            "hitl",
            "evaluator",
        }
        if pattern not in known:
            pattern = "sequential"
        tag_list = tags or ["designed", pattern, *intents]
        # Dedupe tags
        seen: set[str] = set()
        uniq_tags: list[str] = []
        for t in tag_list:
            if t not in seen:
                seen.add(t)
                uniq_tags.append(t)

        return {
            "apiVersion": "agentforge/v1",
            "kind": "Workflow",
            "metadata": {
                "name": name,
                "description": task,
                "version": "0.1.0",
                "tags": uniq_tags,
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
                    "enabled": "evaluator" in intents or pattern == "evaluator",
                    "rubric": "Correctness and safety",
                    "pass_threshold": 0.7,
                },
            },
        }

    def _llm_enrich(self, task: str, doc: dict[str, Any]) -> dict[str, Any]:
        doc = dict(doc)
        meta = dict(doc.get("metadata") or {})
        meta["description"] = f"{task} (llm-enriched)"
        doc["metadata"] = meta
        return doc
