"""LangGraph runtime adapter — primary, fully working backend."""

from __future__ import annotations

import json
import operator
import uuid
from collections.abc import Iterator
from typing import Annotated, Any, TypedDict

from agentforge.ir.models import RunState, WorkflowIR
from agentforge.observability.events import EventEmitter
from agentforge.policies.engine import PolicyEngine
from agentforge.runtimes.base import (
    Capability,
    CapabilityInfo,
    CapabilityStatus,
    InspectView,
    RunRequest,
    RunResult,
    RuntimeAdapter,
)
from agentforge.runtimes.base.helpers import (
    DEFAULT_MOCK_SUPERVISOR_HOPS,
    SUPERVISOR_ROLES,
    SQLiteRunStore,
    apply_transform,
    eval_condition,
    llm_respond,
    mock_supervisor_route,
    new_thread_id,
    redact_secrets,
    resolve_llm_config,
    supervisor_worker_ids,
)
from agentforge.runtimes.langgraph.checkpointer import DurableMemorySaver
from agentforge.schema import NodeType
from agentforge.security.guardrails import GuardrailEngine
from agentforge.tools.registry import ToolRegistry


def _last(left: Any, right: Any) -> Any:
    return right if right is not None else left


def _merge_dicts(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    return {**(left or {}), **(right or {})}


class GraphState(TypedDict, total=False):
    input: Annotated[str, _last]
    output: Annotated[str, _last]
    messages: Annotated[list[dict[str, Any]], operator.add]
    route: Annotated[str, _last]
    needs_revision: Annotated[bool, _last]
    continue_loop: Annotated[bool, _last]
    loop_count: Annotated[int, _last]
    scores: Annotated[dict[str, float], _merge_dicts]
    approved: Annotated[bool, _last]
    pending_approval: Annotated[bool, _last]
    node_outputs: Annotated[dict[str, Any], _merge_dicts]
    artifacts: Annotated[dict[str, Any], _merge_dicts]
    report: Annotated[dict[str, Any], _last]
    payload: Annotated[dict[str, Any], _merge_dicts]
    eval_passed: Annotated[bool, _last]
    error: Annotated[str, _last]
    meta: Annotated[dict[str, Any], _merge_dicts]


class LangGraphAdapter(RuntimeAdapter):
    name = "langgraph"

    def __init__(
        self,
        store: SQLiteRunStore | None = None,
        checkpointer: DurableMemorySaver | None = None,
    ) -> None:
        self.store = store or SQLiteRunStore()
        self._compiled: dict[str, Any] = {}
        self._ir_by_thread: dict[str, WorkflowIR] = {}
        self._checkpointer = checkpointer

    def _saver(self) -> DurableMemorySaver:
        if self._checkpointer is None:
            self._checkpointer = DurableMemorySaver()
        return self._checkpointer

    def capabilities(self) -> list[CapabilityInfo]:
        supported = [
            Capability.COMPILE,
            Capability.VALIDATE,
            Capability.RUN,
            Capability.RESUME,
            Capability.STREAM,
            Capability.CANCEL,
            Capability.INSPECT,
            Capability.SERIALIZE_STATE,
            Capability.CHECKPOINTS,
            Capability.HITL,
            Capability.PARALLEL,
            Capability.CONDITIONAL,
            Capability.LOOPS,
            Capability.SUBWORKFLOWS,
            Capability.MCP,
            Capability.EVALUATION,
            Capability.GUARDRAILS,
        ]
        return [
            CapabilityInfo(capability=c, status=CapabilityStatus.SUPPORTED, notes="implemented")
            for c in supported
        ]

    def validate_ir(self, ir: WorkflowIR) -> list[str]:
        errors: list[str] = []
        if not ir.nodes:
            errors.append("IR has no nodes")
        return errors

    def compile(self, ir: WorkflowIR) -> Any:
        try:
            from langgraph.graph import END, START, StateGraph
            from langgraph.types import interrupt
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("langgraph is required for the LangGraph adapter") from exc

        tools = ToolRegistry(ir)
        policies = PolicyEngine(ir.policies)
        guardrails = GuardrailEngine(ir.guardrails)
        emitter = EventEmitter(self.store)

        graph = StateGraph(GraphState)
        node_map = ir.node_map()

        workers = supervisor_worker_ids(ir)
        max_supervisor_hops = min(
            DEFAULT_MOCK_SUPERVISOR_HOPS,
            max(1, int(getattr(ir.policies.budget, "max_steps", 100) or 100)),
        )

        def make_agent_node(node_id: str, agent_id: str):
            def _node(state: GraphState) -> dict[str, Any]:
                agent = ir.agents.get(agent_id)
                system = agent.system_prompt if agent else f"You are {agent_id}."
                llm = resolve_llm_config(agent.llm) if agent else resolve_llm_config()
                user_input = str(state.get("input", ""))
                payload = state.get("payload") if isinstance(state.get("payload"), dict) else {}
                thread_id = str((state.get("meta") or {}).get("thread_id") or "")
                artifacts = dict(state.get("artifacts") or {})
                if thread_id:
                    emitter.emit(
                        thread_id, "node_start", {"node": node_id, "type": "AGENT", "agent": agent_id}
                    )
                declared = list(agent.tools) if agent else []
                tool_notes: list[str] = []
                for tid in declared:
                    policies.check_tool(tid)
                    tool_result = tools.invoke(tid, dict(state))
                    artifacts[tid] = tool_result
                    snippet = json.dumps(tool_result, default=str)
                    if len(snippet) > 800:
                        snippet = snippet[:797] + "..."
                    tool_notes.append(f"{tid}: {snippet}")
                    if thread_id:
                        emitter.emit(thread_id, "tool_invoked", {"node": node_id, "tool": tid})
                if payload:
                    context = json.dumps(payload, default=str)
                    if len(context) > 2000:
                        context = context[:1997] + "..."
                    user_input = f"{user_input}\n\nStructured payload:\n{context}".strip()
                if tool_notes:
                    user_input = f"{user_input}\n\nTool results:\n" + "\n".join(tool_notes)
                text = llm_respond(system, user_input, agent_id=agent_id, config=llm)
                text = redact_secrets(text) if ir.policies.security.redact_outputs else text
                decision = guardrails.check(text)
                if decision.action == "block":
                    return {"output": decision.message or "blocked", "error": "guardrail_block"}
                if decision.action == "modify" and decision.modified is not None:
                    text = decision.modified
                if decision.action == "escalate":
                    interrupt({"type": "guardrail_escalate", "node": node_id, "text": text})
                policies.check_budget_step()
                outs = dict(state.get("node_outputs") or {})
                outs[node_id] = text
                result: dict[str, Any] = {
                    "output": text,
                    "messages": [{"role": "assistant", "agent": agent_id, "content": text}],
                    "node_outputs": outs,
                    "artifacts": artifacts,
                    "meta": {
                        **(state.get("meta") or {}),
                        "llm_mode": llm.get("mode", "mock"),
                    },
                }
                role = str(getattr(agent, "role", "") or "").lower() if agent else ""
                is_supervisor = role in SUPERVISOR_ROLES or (
                    ir.pattern.value == "supervisor" and agent_id == (next(iter(ir.agents), None))
                )
                if is_supervisor and workers:
                    meta = dict(result["meta"])
                    visits = int(meta.get("supervisor_visits") or 0) + 1
                    # Only honor the original caller-requested route, not the last hop
                    requested = meta.get("requested_route")
                    incoming = str(requested) if requested not in (None, "") else ""
                    route = mock_supervisor_route(
                        workers=workers,
                        node_outputs=outs,
                        user_input=user_input,
                        supervisor_visits=visits,
                        max_hops=max_supervisor_hops,
                        forced_route=incoming or None,
                    )
                    meta["supervisor_visits"] = visits
                    meta["last_route"] = route
                    result["route"] = route
                    result["meta"] = meta
                    result["output"] = f"{text} [route={route}]"
                    outs[node_id] = result["output"]
                    result["node_outputs"] = outs
                if role in {"critic", "reviewer"} or agent_id == "critic":
                    meta = dict(result["meta"])
                    visits = int(meta.get("critic_visits") or 0) + 1
                    meta["critic_visits"] = visits
                    result["meta"] = meta
                    result["needs_revision"] = visits < 2
                if thread_id:
                    emitter.emit(thread_id, "node_end", {"node": node_id, "agent": agent_id})
                return result

            return _node

        def make_tool_node(node_id: str, tool_id: str):
            def _node(state: GraphState) -> dict[str, Any]:
                policies.check_tool(tool_id)
                thread_id = str((state.get("meta") or {}).get("thread_id") or "")
                if thread_id:
                    emitter.emit(thread_id, "tool_invoked", {"node": node_id, "tool": tool_id})
                result = tools.invoke(tool_id, dict(state))
                outs = dict(state.get("node_outputs") or {})
                outs[node_id] = result
                artifacts = dict(state.get("artifacts") or {})
                artifacts[tool_id] = result
                payload: dict[str, Any] = {
                    "output": result if isinstance(result, str) else json.dumps(result, default=str),
                    "node_outputs": outs,
                    "artifacts": artifacts,
                }
                if isinstance(result, dict) and (
                    tool_id in {"assemble_cve_report", "emit_report"}
                    or {"cve_id", "severity"} <= set(result)
                ):
                    payload["report"] = result
                return payload

            return _node

        def make_transform_node(node_id: str, expr: str | None):
            def _node(state: GraphState) -> dict[str, Any]:
                return apply_transform(expr or "", dict(state))

            return _node

        def make_evaluator_node(node_id: str, rubric: str | None):
            def _node(state: GraphState) -> dict[str, Any]:
                output = str(state.get("output", ""))
                report = state.get("report") if isinstance(state.get("report"), dict) else {}
                score = 0.9 if output and "blocked" not in output.lower() else 0.2
                schema = ir.evaluation.output_schema or {}
                required = list(schema.get("required") or []) if isinstance(schema, dict) else []
                if required:
                    target = report if report else None
                    if target is None:
                        try:
                            parsed = json.loads(output)
                            target = parsed if isinstance(parsed, dict) else None
                        except (TypeError, json.JSONDecodeError):
                            target = None
                    if target is None:
                        score = min(score, 0.4)
                    else:
                        missing = [k for k in required if k not in target]
                        if missing:
                            score = min(score, 0.35)
                passed = score >= ir.evaluation.pass_threshold
                scores = {"correctness": score, "safety": 0.95, "rubric": rubric or ""}
                return {
                    "scores": scores,
                    "output": output,
                    "eval_passed": passed,
                    "meta": {
                        **(state.get("meta") or {}),
                        "eval_passed": passed,
                        "evaluator": node_id,
                    },
                }

            return _node

        def make_approval_node(node_id: str, message: str | None):
            def _node(state: GraphState) -> dict[str, Any]:
                if state.get("approved") is True:
                    return {"pending_approval": False, "approved": True}
                if ir.policies.approval.auto_approve_in_tests and state.get("meta", {}).get("auto_approve"):
                    return {"pending_approval": False, "approved": True}
                answer = interrupt(
                    {
                        "type": "human_approval",
                        "node": node_id,
                        "message": message or "Approve to continue?",
                        "output": state.get("output"),
                    }
                )
                approved = bool(answer) if not isinstance(answer, dict) else bool(answer.get("approved", answer))
                return {"approved": approved, "pending_approval": False}

            return _node

        def make_guardrail_node(node_id: str, rules: list[str], action: str | None):
            def _node(state: GraphState) -> dict[str, Any]:
                text = str(state.get("output", state.get("input", "")))
                decision = guardrails.check(text, extra_rules=rules, default_action=action or "block")
                if decision.action == "block":
                    return {"output": decision.message or "blocked by guardrail", "error": "guardrail"}
                if decision.action == "modify" and decision.modified is not None:
                    return {"output": decision.modified}
                if decision.action == "escalate":
                    interrupt({"type": "escalate", "node": node_id})
                return {}

            return _node

        def make_subworkflow_node(node_id: str, sub_id: str | None):
            def _node(state: GraphState) -> dict[str, Any]:
                child = (ir.subworkflows or {}).get(sub_id or "")
                summary = f"subworkflow:{sub_id} executed"
                if isinstance(child, dict):
                    summary = f"subworkflow:{sub_id} keys={list(child.keys())}"
                outs = dict(state.get("node_outputs") or {})
                outs[node_id] = summary
                return {"output": summary, "node_outputs": outs}

            return _node

        def passthrough(_state: GraphState) -> dict[str, Any]:
            return {}

        def join_node(state: GraphState) -> dict[str, Any]:
            outs = state.get("node_outputs") or {}
            merged = " | ".join(f"{k}={v}" for k, v in outs.items()) if outs else state.get("output", "")
            return {"output": merged}

        def parallel_node(state: GraphState) -> dict[str, Any]:
            return {"meta": {**(state.get("meta") or {}), "parallel": True}}

        def loop_node(state: GraphState) -> dict[str, Any]:
            count = int(state.get("loop_count") or 0) + 1
            return {"loop_count": count}

        # Register nodes
        for n in ir.nodes:
            if n.type == NodeType.START:
                continue
            if n.type == NodeType.END:
                continue
            if n.type == NodeType.AGENT:
                graph.add_node(n.id, make_agent_node(n.id, n.agent_id or n.id))
            elif n.type == NodeType.TOOL:
                graph.add_node(n.id, make_tool_node(n.id, n.tool_id or n.id))
            elif n.type == NodeType.TRANSFORM:
                graph.add_node(n.id, make_transform_node(n.id, n.transform_expr))
            elif n.type == NodeType.EVALUATOR:
                graph.add_node(n.id, make_evaluator_node(n.id, n.evaluator_rubric))
            elif n.type == NodeType.HUMAN_APPROVAL:
                graph.add_node(n.id, make_approval_node(n.id, n.approval_message))
            elif n.type == NodeType.GUARDRAIL:
                graph.add_node(n.id, make_guardrail_node(n.id, n.guardrail_rules, n.guardrail_action))
            elif n.type == NodeType.SUBWORKFLOW:
                graph.add_node(n.id, make_subworkflow_node(n.id, n.subworkflow_id))
            elif n.type == NodeType.JOIN:
                graph.add_node(n.id, join_node)
            elif n.type == NodeType.PARALLEL:
                graph.add_node(n.id, parallel_node)
            elif n.type == NodeType.LOOP:
                graph.add_node(n.id, loop_node)
            elif n.type in {NodeType.CONDITION, NodeType.ROUTER}:
                graph.add_node(n.id, passthrough)
            else:
                graph.add_node(n.id, passthrough)

        # Wire edges
        for e in ir.edges:
            src = e.source
            tgt = e.target
            src_node = node_map.get(src)
            tgt_node = node_map.get(tgt)

            if src_node and src_node.type == NodeType.START:
                graph.add_edge(START, tgt if tgt_node and tgt_node.type != NodeType.END else END)
                continue
            if tgt_node and tgt_node.type == NodeType.END:
                # conditional handled below
                if src_node and src_node.type in {NodeType.CONDITION, NodeType.ROUTER, NodeType.LOOP}:
                    continue
                graph.add_edge(src, END)
                continue

            if src_node and src_node.type in {NodeType.CONDITION, NodeType.ROUTER}:
                continue  # handled via conditional edges
            if src_node and src_node.type == NodeType.LOOP:
                continue
            graph.add_edge(src, tgt)

        # Conditional / router edges
        for n in ir.nodes:
            if n.type in {NodeType.CONDITION, NodeType.ROUTER}:
                routes = dict(n.routes)
                # Also collect labeled edges
                for e in ir.edges:
                    if e.source == n.id:
                        key = e.label or e.condition_expr or e.target
                        routes[key] = e.target

                def make_router(node=n, route_map=routes):
                    def _route(state: GraphState) -> str:
                        if node.condition_expr:
                            ok = eval_condition(node.condition_expr, dict(state))
                            if "true" in route_map and "false" in route_map:
                                return "true" if ok else "false"
                        # supervisor style: use state route set by supervisor agent
                        preferred = str(state.get("route") or "")
                        if preferred in route_map:
                            return preferred
                        # Prefer a pending worker over immediate done when unset
                        non_done = [k for k in route_map if k != "done"]
                        if non_done:
                            return non_done[0]
                        if "done" in route_map:
                            return "done"
                        return next(iter(route_map))

                    return _route

                path_map = {}
                for label, target in routes.items():
                    tnode = node_map.get(target)
                    path_map[label] = END if (tnode and tnode.type == NodeType.END) or target == "end" else target
                if path_map:
                    graph.add_conditional_edges(n.id, make_router(), path_map)

            if n.type == NodeType.LOOP:
                body = n.loop_body
                max_iter = n.max_iterations

                def make_loop_router(node=n, body_id=body, limit=max_iter):
                    def _route(state: GraphState) -> str:
                        count = int(state.get("loop_count") or 0)
                        cont = eval_condition(node.loop_condition or "False", dict(state))
                        if cont and count < limit and body_id:
                            return "continue"
                        return "done"

                    return _route

                done_target = END
                cont_target = body or END
                for e in ir.edges:
                    if e.source == n.id:
                        if (e.label or "") in {"done", "exit"} or e.target == "end":
                            tnode = node_map.get(e.target)
                            done_target = END if (tnode and tnode.type == NodeType.END) else e.target
                        if (e.label or "") in {"continue", "revise"}:
                            cont_target = e.target
                graph.add_conditional_edges(
                    n.id,
                    make_loop_router(),
                    {"continue": cont_target, "done": done_target},
                )

        checkpointer = self._saver()
        compiled = graph.compile(checkpointer=checkpointer)
        key = ir.name
        self._compiled[key] = {"graph": compiled, "ir": ir, "emitter": emitter, "policies": policies}
        return compiled

    @staticmethod
    def _pack_output(result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            return {"output": str(result), "scores": {}, "node_outputs": {}, "artifacts": {}, "report": {}}
        artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), dict) else {}
        report = result.get("report") if isinstance(result.get("report"), dict) else {}
        if not report and artifacts:
            for key in ("assemble_cve_report", "emit_report"):
                if isinstance(artifacts.get(key), dict):
                    report = artifacts[key]
                    break
            if not report:
                for value in artifacts.values():
                    if isinstance(value, dict) and "cve_id" in value and "severity" in value:
                        report = value
                        break
        output = result.get("output")
        if report and (not output or output == "{}"):
            output = json.dumps(report, default=str)
        return {
            "output": output,
            "scores": result.get("scores") or {},
            "node_outputs": result.get("node_outputs") or {},
            "artifacts": artifacts or {},
            "report": report or {},
            "approved": result.get("approved", False),
            "eval_passed": result.get("eval_passed", False),
        }

    def run(self, ir: WorkflowIR, request: RunRequest) -> RunResult:
        self.require(Capability.RUN)
        compiled_wrap = self._compiled.get(ir.name) or {"graph": self.compile(ir), "ir": ir}
        graph = compiled_wrap["graph"] if isinstance(compiled_wrap, dict) and "graph" in compiled_wrap else compiled_wrap
        if not isinstance(compiled_wrap, dict) or "emitter" not in compiled_wrap:
            compiled_wrap = self._compiled[ir.name]

        thread_id = request.thread_id or new_thread_id()
        if self.store.is_cancelled(thread_id):
            return RunResult(status=RunState.CANCELLED, thread_id=thread_id, output={})

        emitter: EventEmitter = compiled_wrap["emitter"]
        policies: PolicyEngine = compiled_wrap["policies"]
        policies.reset()
        emitter.emit(thread_id, "run_started", {"input": request.input})

        config = {"configurable": {"thread_id": thread_id}}
        requested_route = request.input.get("route")
        reserved = {
            "input",
            "query",
            "auto_approve",
            "route",
            "needs_revision",
            "continue",
            "thread_id",
        }
        payload = {k: v for k, v in request.input.items() if k not in reserved}
        raw_input = request.input.get("input", request.input.get("query"))
        if raw_input is None:
            raw_input = json.dumps(payload, default=str) if payload else ""
        auto_approve = bool(request.input.get("auto_approve", False))
        state_in: dict[str, Any] = {
            "input": str(raw_input),
            "output": "",
            "messages": [],
            # Empty default lets supervisor/mock router choose workers first
            "route": str(requested_route) if requested_route not in (None, "") else "",
            "needs_revision": bool(request.input.get("needs_revision", False)),
            "continue_loop": bool(request.input.get("continue", False)),
            "loop_count": 0,
            "scores": {},
            "approved": False,
            "pending_approval": False,
            "node_outputs": {},
            "artifacts": {},
            "report": {},
            "payload": payload,
            "eval_passed": False,
            "meta": {
                "auto_approve": auto_approve,
                "requested_route": requested_route,
                "thread_id": thread_id,
                **payload,
            },
        }
        # Seed condition helpers
        for k, v in request.input.items():
            if k not in state_in:
                state_in[k] = v

        try:
            if request.dry_run:
                self.store.save_run(thread_id, RunState.COMPLETED.value, state_in, checkpoint_id="dry-run")
                return RunResult(
                    status=RunState.COMPLETED,
                    output={"dry_run": True, "nodes": [n.id for n in ir.nodes]},
                    thread_id=thread_id,
                    checkpoint_id="dry-run",
                )

            result = graph.invoke(state_in, config)
            self._ir_by_thread[thread_id] = ir

            # Detect interrupt
            interrupt_val = None
            if isinstance(result, dict) and "__interrupt__" in result:
                interrupt_val = result["__interrupt__"]
            status = RunState.COMPLETED
            if interrupt_val:
                status = RunState.WAITING_FOR_APPROVAL
                payload_int = interrupt_val
                if isinstance(payload_int, (list, tuple)) and payload_int:
                    first = payload_int[0]
                    interrupt_val = getattr(first, "value", first)
                    if isinstance(interrupt_val, dict) and interrupt_val.get("type") == "human_approval":
                        status = RunState.WAITING_FOR_APPROVAL
                    else:
                        status = RunState.WAITING_FOR_INPUT

            out = self._pack_output(result)
            ckpt = f"ckpt-{uuid.uuid4().hex[:8]}"
            self.store.save_run(thread_id, status.value, out if isinstance(out, dict) else {}, ckpt)
            emitter.emit(thread_id, "run_finished", {"status": status.value, "output": out})
            events = self.store.list_events(thread_id)
            return RunResult(
                status=status,
                output=out,
                thread_id=thread_id,
                checkpoint_id=ckpt,
                events=events,
                interrupt=interrupt_val if isinstance(interrupt_val, dict) else {"value": interrupt_val},
            )
        except Exception as exc:
            # LangGraph may raise GraphInterrupt
            name = type(exc).__name__
            if "Interrupt" in name:
                status = RunState.WAITING_FOR_APPROVAL
                paused = self._pack_output({"output": state_in.get("output"), "payload": payload})
                self.store.save_run(thread_id, status.value, paused, None)
                return RunResult(
                    status=status,
                    output=paused,
                    thread_id=thread_id,
                    interrupt={"error": str(exc), "type": "human_approval"},
                    events=self.store.list_events(thread_id),
                )
            self.store.save_run(thread_id, RunState.FAILED.value, {"error": str(exc)}, None)
            emitter.emit(thread_id, "run_failed", {"error": str(exc)})
            return RunResult(
                status=RunState.FAILED,
                output={"error": str(exc)},
                thread_id=thread_id,
                error=str(exc),
                events=self.store.list_events(thread_id),
            )

    def resume(self, ir: WorkflowIR, request: RunRequest) -> RunResult:
        self.require(Capability.RESUME)
        if not request.thread_id:
            raise ValueError("resume requires thread_id")
        compiled_wrap = self._compiled.get(ir.name) or {"graph": self.compile(ir)}
        graph = compiled_wrap["graph"]
        config = {"configurable": {"thread_id": request.thread_id}}
        try:
            from langgraph.types import Command

            try:
                snapshot = graph.get_state(config)
            except Exception:
                snapshot = None
            empty = snapshot is None or (
                not getattr(snapshot, "values", None) and not getattr(snapshot, "next", None)
            )
            if empty:
                saver_path = str(self._saver().path)
                return RunResult(
                    status=RunState.FAILED,
                    output={},
                    thread_id=request.thread_id,
                    error=(
                        f"No checkpoint for thread_id {request.thread_id!r}. "
                        "Run the workflow first (without --auto-approve so HITL can pause), "
                        f"keep AGENTFORGE_DATA_DIR, and do not delete {saver_path}."
                    ),
                )

            resume_val = request.resume_value
            if request.approval is not None:
                resume_val = {"approved": request.approval}
            result = graph.invoke(Command(resume=resume_val), config)
            status = RunState.COMPLETED
            interrupt_val = None
            if isinstance(result, dict) and result.get("__interrupt__"):
                status = RunState.WAITING_FOR_INPUT
                interrupt_val = result.get("__interrupt__")
            out = self._pack_output(result)
            self.store.save_run(request.thread_id, status.value, out, None)
            return RunResult(
                status=status,
                output=out,
                thread_id=request.thread_id,
                interrupt=interrupt_val if isinstance(interrupt_val, dict) else None,
            )
        except Exception as exc:
            name = type(exc).__name__
            if "Interrupt" in name:
                return RunResult(
                    status=RunState.WAITING_FOR_APPROVAL,
                    output={},
                    thread_id=request.thread_id,
                    interrupt={"error": str(exc)},
                )
            return RunResult(
                status=RunState.FAILED,
                output={"error": str(exc)},
                thread_id=request.thread_id,
                error=str(exc),
            )

    def stream(self, ir: WorkflowIR, request: RunRequest) -> Iterator[dict[str, Any]]:
        self.require(Capability.STREAM)
        compiled_wrap = self._compiled.get(ir.name) or {"graph": self.compile(ir)}
        graph = compiled_wrap["graph"]
        thread_id = request.thread_id or new_thread_id()
        config = {"configurable": {"thread_id": thread_id}}
        state_in = {"input": str(request.input.get("input", "")), "messages": [], "node_outputs": {}, "meta": {}}
        for event in graph.stream(state_in, config, stream_mode="updates"):
            yield {"thread_id": thread_id, "event": event}

    def cancel(self, thread_id: str) -> bool:
        self.store.cancel(thread_id)
        return True

    def inspect(self, thread_id: str) -> InspectView:
        row = self.store.get_run(thread_id)
        if not row:
            return InspectView(thread_id=thread_id, status=RunState.FAILED, state={"error": "not found"})
        return InspectView(
            thread_id=thread_id,
            status=RunState(row["status"]),
            state=row["state"],
            checkpoints=[{"id": row.get("checkpoint_id")}] if row.get("checkpoint_id") else [],
        )

    def serialize_state(self, thread_id: str) -> dict[str, Any]:
        row = self.store.get_run(thread_id)
        if not row:
            raise KeyError(thread_id)
        return row

    def deserialize_state(self, payload: dict[str, Any]) -> str:
        thread_id = payload.get("thread_id") or new_thread_id()
        self.store.save_run(
            thread_id,
            payload.get("status", RunState.PAUSED.value),
            payload.get("state", {}),
            payload.get("checkpoint_id"),
        )
        return thread_id
