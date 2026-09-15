"""YAML/JSON workflow spec loader → WorkflowIR."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from agentforge.ir.models import IREdge, IRNode, WorkflowIR
from agentforge.schema import NodeType, WorkflowDocument, WorkflowPattern


class SpecLoader:
    """Parse YAML/JSON/dict documents into canonical WorkflowIR."""

    def load(self, source: str | Path | dict[str, Any]) -> WorkflowIR:
        if isinstance(source, dict):
            data = source
            source_path = None
        else:
            path = Path(source)
            text = path.read_text(encoding="utf-8")
            if path.suffix.lower() in {".yaml", ".yml"}:
                data = yaml.safe_load(text)
            elif path.suffix.lower() == ".json":
                data = json.loads(text)
            else:
                # Try YAML first, then JSON
                try:
                    data = yaml.safe_load(text)
                except yaml.YAMLError:
                    data = json.loads(text)
            source_path = str(path.resolve())

        if not isinstance(data, dict):
            raise ValueError("Workflow document must be a mapping/object")

        try:
            doc = WorkflowDocument.model_validate(data)
        except ValidationError as exc:
            raise ValueError(f"Invalid workflow document: {exc}") from exc

        return self._to_ir(doc, source_path=source_path)

    def _to_ir(self, doc: WorkflowDocument, *, source_path: str | None) -> WorkflowIR:
        spec = doc.spec
        nodes = [
            IRNode(
                id=n.id,
                type=n.type,
                agent_id=n.agent,
                tool_id=n.tool,
                subworkflow_id=n.subworkflow,
                condition_expr=n.condition,
                routes=dict(n.routes),
                join_of=list(n.join_of),
                parallel_of=list(n.parallel_of),
                loop_body=n.loop_body,
                loop_condition=n.loop_condition,
                max_iterations=n.max_iterations,
                transform_expr=n.transform,
                prompt=n.prompt,
                approval_message=n.approval_message,
                guardrail_action=n.guardrail_action.value if n.guardrail_action else None,
                guardrail_rules=list(n.guardrail_rules),
                evaluator_rubric=n.evaluator_rubric,
                metadata=dict(n.config),
            )
            for n in spec.nodes
        ]
        edges = [
            IREdge(
                source=e.source,
                target=e.target,
                condition_expr=e.condition,
                label=e.label,
            )
            for e in spec.edges
        ]

        # Auto-expand minimal pattern graphs when nodes are empty
        if not nodes:
            nodes, edges = self._synthesize_from_pattern(spec.pattern, list(spec.agents), list(spec.tools))

        # Ensure START/END exist
        ids = {n.id for n in nodes}
        if not any(n.type == NodeType.START for n in nodes):
            start_id = "start"
            nodes.insert(0, IRNode(id=start_id, type=NodeType.START))
            if edges:
                # connect start to entry or first non-end node
                entry = spec.entry or next(
                    (n.id for n in nodes if n.type not in {NodeType.START, NodeType.END}),
                    None,
                )
                if entry and entry in ids | {start_id}:
                    edges.insert(0, IREdge(source=start_id, target=entry))
            ids.add(start_id)
        if not any(n.type == NodeType.END for n in nodes):
            end_id = "end"
            nodes.append(IRNode(id=end_id, type=NodeType.END))
            # connect dangling nodes to end
            sources = {e.source for e in edges}
            targets = {e.target for e in edges}
            dangling = [n.id for n in nodes if n.id not in sources and n.type != NodeType.END]
            for did in dangling:
                if did != end_id:
                    edges.append(IREdge(source=did, target=end_id))
            # Also connect nodes that are never targets except start
            for n in nodes:
                if n.type not in {NodeType.START, NodeType.END} and n.id not in targets:
                    # leave as is — validator will catch if truly disconnected
                    pass

        entry = spec.entry or next(n.id for n in nodes if n.type == NodeType.START)

        return WorkflowIR(
            name=doc.metadata.name,
            description=doc.metadata.description,
            version=doc.metadata.version,
            pattern=spec.pattern,
            runtime=spec.runtime,
            entry=entry,
            nodes=nodes,
            edges=edges,
            agents={a.id: a for a in spec.agents},
            tools={t.id: t for t in spec.tools},
            mcp_servers={m.id: m for m in spec.mcp_servers},
            policies=spec.policies,
            guardrails=list(spec.guardrails),
            evaluation=spec.evaluation,
            memory=spec.memory,
            observability=spec.observability,
            state_schema=dict(spec.state_schema) or {"input": "str", "output": "str"},
            subworkflows=dict(spec.subworkflows),
            tags=list(doc.metadata.tags),
            source_path=source_path,
        )

    def _synthesize_from_pattern(
        self,
        pattern: WorkflowPattern,
        agents: list,
        tools: list,
    ) -> tuple[list[IRNode], list[IREdge]]:
        """Build a minimal node/edge graph from pattern + agent list."""
        nodes: list[IRNode] = [IRNode(id="start", type=NodeType.START)]
        edges: list[IREdge] = []
        agent_ids = [a.id for a in agents] or ["agent"]

        if pattern == WorkflowPattern.SINGLE:
            aid = agent_ids[0]
            nodes.append(IRNode(id=aid, type=NodeType.AGENT, agent_id=aid))
            edges += [IREdge(source="start", target=aid), IREdge(source=aid, target="end")]
        elif pattern in {WorkflowPattern.SEQUENTIAL, WorkflowPattern.HANDOFF}:
            prev = "start"
            for aid in agent_ids:
                nodes.append(IRNode(id=aid, type=NodeType.AGENT, agent_id=aid))
                edges.append(IREdge(source=prev, target=aid))
                prev = aid
            edges.append(IREdge(source=prev, target="end"))
        elif pattern in {WorkflowPattern.PARALLEL, WorkflowPattern.FAN_OUT_FAN_IN}:
            nodes.append(IRNode(id="fanout", type=NodeType.PARALLEL, parallel_of=agent_ids))
            edges.append(IREdge(source="start", target="fanout"))
            for aid in agent_ids:
                nodes.append(IRNode(id=aid, type=NodeType.AGENT, agent_id=aid))
                edges.append(IREdge(source="fanout", target=aid))
            nodes.append(IRNode(id="join", type=NodeType.JOIN, join_of=agent_ids))
            for aid in agent_ids:
                edges.append(IREdge(source=aid, target="join"))
            edges.append(IREdge(source="join", target="end"))
        elif pattern == WorkflowPattern.SUPERVISOR:
            supervisor = agent_ids[0]
            workers = agent_ids[1:] or agent_ids
            nodes.append(IRNode(id=supervisor, type=NodeType.AGENT, agent_id=supervisor))
            nodes.append(
                IRNode(
                    id="router",
                    type=NodeType.ROUTER,
                    routes={w: w for w in workers} | {"done": "end"},
                )
            )
            edges += [
                IREdge(source="start", target=supervisor),
                IREdge(source=supervisor, target="router"),
            ]
            for w in workers:
                if w != supervisor:
                    nodes.append(IRNode(id=w, type=NodeType.AGENT, agent_id=w))
                edges.append(IREdge(source="router", target=w, label=w))
                edges.append(IREdge(source=w, target=supervisor))
            edges.append(IREdge(source="router", target="end", label="done"))
        elif pattern == WorkflowPattern.REFLECTION:
            actor = agent_ids[0]
            critic = agent_ids[1] if len(agent_ids) > 1 else f"{actor}_critic"
            nodes += [
                IRNode(id=actor, type=NodeType.AGENT, agent_id=actor),
                IRNode(id=critic, type=NodeType.AGENT, agent_id=critic if critic in agent_ids else actor),
                IRNode(
                    id="loop",
                    type=NodeType.LOOP,
                    loop_body=actor,
                    loop_condition="needs_revision",
                    max_iterations=3,
                ),
            ]
            edges += [
                IREdge(source="start", target=actor),
                IREdge(source=actor, target=critic),
                IREdge(source=critic, target="loop"),
                IREdge(source="loop", target=actor, label="revise"),
                IREdge(source="loop", target="end", label="done"),
            ]
        elif pattern == WorkflowPattern.CONDITIONAL:
            aid = agent_ids[0]
            nodes += [
                IRNode(
                    id="condition",
                    type=NodeType.CONDITION,
                    condition_expr="route == 'a'",
                    routes={"true": aid, "false": "end"},
                ),
                IRNode(id=aid, type=NodeType.AGENT, agent_id=aid),
            ]
            edges += [
                IREdge(source="start", target="condition"),
                IREdge(source="condition", target=aid, label="true"),
                IREdge(source="condition", target="end", label="false"),
                IREdge(source=aid, target="end"),
            ]
        elif pattern == WorkflowPattern.BOUNDED_LOOP:
            aid = agent_ids[0]
            nodes += [
                IRNode(id=aid, type=NodeType.AGENT, agent_id=aid),
                IRNode(
                    id="loop",
                    type=NodeType.LOOP,
                    loop_body=aid,
                    loop_condition="continue",
                    max_iterations=5,
                ),
            ]
            edges += [
                IREdge(source="start", target=aid),
                IREdge(source=aid, target="loop"),
                IREdge(source="loop", target=aid, label="continue"),
                IREdge(source="loop", target="end", label="done"),
            ]
        elif pattern == WorkflowPattern.HITL:
            aid = agent_ids[0]
            nodes += [
                IRNode(id=aid, type=NodeType.AGENT, agent_id=aid),
                IRNode(
                    id="approve",
                    type=NodeType.HUMAN_APPROVAL,
                    approval_message="Approve agent output?",
                ),
            ]
            edges += [
                IREdge(source="start", target=aid),
                IREdge(source=aid, target="approve"),
                IREdge(source="approve", target="end"),
            ]
        elif pattern == WorkflowPattern.EVALUATOR:
            aid = agent_ids[0]
            nodes += [
                IRNode(id=aid, type=NodeType.AGENT, agent_id=aid),
                IRNode(
                    id="evaluate",
                    type=NodeType.EVALUATOR,
                    evaluator_rubric="Correctness and safety",
                ),
            ]
            edges += [
                IREdge(source="start", target=aid),
                IREdge(source=aid, target="evaluate"),
                IREdge(source="evaluate", target="end"),
            ]
        elif pattern == WorkflowPattern.HIERARCHICAL:
            root = agent_ids[0]
            children = agent_ids[1:] or agent_ids
            nodes.append(IRNode(id=root, type=NodeType.AGENT, agent_id=root))
            edges.append(IREdge(source="start", target=root))
            for c in children:
                if c != root:
                    nodes.append(IRNode(id=c, type=NodeType.AGENT, agent_id=c))
                    edges.append(IREdge(source=root, target=c))
                    edges.append(IREdge(source=c, target="end"))
            if not children or children == [root]:
                edges.append(IREdge(source=root, target="end"))
        elif pattern == WorkflowPattern.SUBWORKFLOW:
            nodes.append(
                IRNode(id="sub", type=NodeType.SUBWORKFLOW, subworkflow_id="child")
            )
            edges += [IREdge(source="start", target="sub"), IREdge(source="sub", target="end")]
        elif pattern == WorkflowPattern.AGENT_AS_TOOL:
            aid = agent_ids[0]
            tool_agent = agent_ids[1] if len(agent_ids) > 1 else aid
            nodes += [
                IRNode(id=aid, type=NodeType.AGENT, agent_id=aid),
                IRNode(id=f"tool_{tool_agent}", type=NodeType.TOOL, tool_id=tool_agent),
            ]
            edges += [
                IREdge(source="start", target=aid),
                IREdge(source=aid, target=f"tool_{tool_agent}"),
                IREdge(source=f"tool_{tool_agent}", target="end"),
            ]
        else:
            aid = agent_ids[0]
            nodes.append(IRNode(id=aid, type=NodeType.AGENT, agent_id=aid))
            edges += [IREdge(source="start", target=aid), IREdge(source=aid, target="end")]

        nodes.append(IRNode(id="end", type=NodeType.END))
        # Ensure agent stubs exist for synthesized graphs
        return nodes, edges
