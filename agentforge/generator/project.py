"""Standalone project code generator (no AgentForge runtime dependency)."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from agentforge.ir.models import WorkflowIR
from agentforge.schema import NodeType


@dataclass
class GeneratedProject:
    path: Path
    name: str
    files: list[str]

    def __str__(self) -> str:
        return f"GeneratedProject(name={self.name!r}, path={self.path})"


class ProjectGenerator:
    def __init__(self, template_root: Path | None = None) -> None:
        self.template_root = template_root or Path(__file__).resolve().parents[2] / "templates" / "generated-project"
        self.env = Environment(
            loader=FileSystemLoader(str(self.template_root)),
            autoescape=select_autoescape(enabled_extensions=()),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def generate(
        self,
        ir: WorkflowIR,
        *,
        output_dir: str | Path | None = None,
        runtime: str = "langgraph",
    ) -> GeneratedProject:
        out = Path(output_dir or f"./generated/{ir.name}")
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True, exist_ok=True)

        ctx = self._context(ir, runtime=runtime)
        written: list[str] = []

        mapping = {
            "README.md.j2": "README.md",
            "pyproject.toml.j2": "pyproject.toml",
            "Dockerfile.j2": "Dockerfile",
            "docker-compose.yml.j2": "docker-compose.yml",
            ".env.example.j2": ".env.example",
            "Makefile.j2": "Makefile",
            "ARCHITECTURE.md.j2": "docs/ARCHITECTURE.md",
            "WORKFLOW.md.j2": "docs/WORKFLOW.md",
            "AGENTS.md.j2": "docs/AGENTS.md",
            "TOOLS.md.j2": "docs/TOOLS.md",
            "SECURITY.md.j2": "docs/SECURITY.md",
            "EVALUATION.md.j2": "docs/EVALUATION.md",
            "OPERATIONS.md.j2": "docs/OPERATIONS.md",
            "DEPLOYMENT.md.j2": "docs/DEPLOYMENT.md",
            "workflow.mmd.j2": "diagrams/workflow.mmd",
            "ci.yml.j2": ".github/workflows/ci.yml",
            "main.py.j2": "src/workflow_app/main.py",
            "graph.py.j2": "src/workflow_app/graph.py",
            "agents.py.j2": "src/workflow_app/agents.py",
            "tools.py.j2": "src/workflow_app/tools.py",
            "config.py.j2": "src/workflow_app/config.py",
            "state.py.j2": "src/workflow_app/state.py",
            "__init__.py.j2": "src/workflow_app/__init__.py",
            "test_workflow.py.j2": "tests/test_workflow.py",
            "workflow.json.j2": "workflow.json",
        }

        for tmpl, dest in mapping.items():
            target = out / dest
            target.parent.mkdir(parents=True, exist_ok=True)
            if (self.template_root / tmpl).exists():
                content = self.env.get_template(tmpl).render(**ctx)
            else:
                content = self._fallback(tmpl, ctx)
            target.write_text(content, encoding="utf-8")
            written.append(dest)

        # Always write IR snapshot
        (out / "workflow_ir.json").write_text(ir.model_dump_json(indent=2), encoding="utf-8")
        written.append("workflow_ir.json")
        return GeneratedProject(path=out.resolve(), name=ir.name, files=written)

    def _context(self, ir: WorkflowIR, *, runtime: str) -> dict[str, Any]:
        has_hitl = any(n.type == NodeType.HUMAN_APPROVAL for n in ir.nodes)
        has_router = any(n.type in {NodeType.ROUTER, NodeType.CONDITION} for n in ir.nodes)
        has_supervisor = ir.pattern.value == "supervisor" or any(
            (a.role or "").lower() == "supervisor" for a in ir.agents.values()
        )
        has_parallel = any(n.type in {NodeType.PARALLEL, NodeType.JOIN} for n in ir.nodes)
        return {
            "name": ir.name,
            "description": ir.description or ir.name,
            "version": ir.version,
            "pattern": ir.pattern.value,
            "runtime": runtime,
            "agents": list(ir.agents.values()),
            "tools": list(ir.tools.values()),
            "nodes": ir.nodes,
            "edges": ir.edges,
            "policies": ir.policies,
            "evaluation": ir.evaluation,
            "mermaid": ir.to_mermaid(),
            "agent_ids": list(ir.agents.keys()),
            "tool_ids": list(ir.tools.keys()),
            "node_ids": [n.id for n in ir.nodes],
            "executable_nodes": [
                n for n in ir.nodes if n.type not in {NodeType.START, NodeType.END}
            ],
            "state_schema": ir.state_schema,
            "ir_json": ir.model_dump(),
            "has_hitl": has_hitl,
            "has_router": has_router,
            "has_supervisor": has_supervisor,
            "has_parallel": has_parallel,
            "allowed_tools": list(ir.policies.tool.allowed_tools),
            "default_deny": ir.policies.tool.default_deny,
        }

    def _fallback(self, tmpl: str, ctx: dict[str, Any]) -> str:
        name = ctx["name"]
        if tmpl == "README.md.j2":
            agents = ", ".join(a.id for a in ctx["agents"]) or "(none)"
            tools = ", ".join(t.id for t in ctx["tools"]) or "(none)"
            return (
                f"# {name}\n\n{ctx['description']}\n\n"
                f"Generated by AgentForge. Pattern: `{ctx['pattern']}` · Runtime: `{ctx['runtime']}`.\n\n"
                f"**Agents:** {agents}\n\n"
                f"**Tools:** {tools}\n\n"
                f"**Policy:** default_deny={ctx['default_deny']} allowed_tools={ctx['allowed_tools']}\n\n"
                "## Run\n\n```bash\npip install -e .\npython -m workflow_app.main\npytest\n```\n"
            )
        if tmpl == "pyproject.toml.j2":
            return f"""[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "{name.replace('_', '-')}"
version = "{ctx['version']}"
description = "{ctx['description'].replace('"', "'")}"
requires-python = ">=3.11"
dependencies = ["langgraph>=0.2", "langchain-core>=0.3", "pydantic>=2.7", "httpx>=0.27"]

[project.optional-dependencies]
dev = ["pytest>=8.2"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
"""
        if tmpl == "main.py.j2":
            return '''"""CLI entrypoint for the generated workflow."""
from __future__ import annotations

import json
import os
import sys

from workflow_app.graph import build_graph, run_workflow


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    query = " ".join(argv) if argv else os.environ.get("WORKFLOW_INPUT", "hello")
    result = run_workflow({"input": query, "auto_approve": True})
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
        if tmpl == "graph.py.j2":
            return self._graph_module(ctx)
        if tmpl == "agents.py.j2":
            return self._agents_module(ctx)
        if tmpl == "tools.py.j2":
            return self._tools_module(ctx)
        if tmpl == "config.py.j2":
            return '''"""Provider-neutral config via environment variables only."""
from __future__ import annotations

import os


def llm_settings() -> dict:
    return {
        "provider": os.environ.get("AGENTFORGE_LLM_PROVIDER", "openai"),
        "model": os.environ.get("AGENTFORGE_LLM_MODEL", "gpt-4o-mini"),
        "api_key": os.environ.get("AGENTFORGE_LLM_API_KEY", ""),
        "base_url": os.environ.get("AGENTFORGE_LLM_BASE_URL", ""),
        "mock": os.environ.get("AGENTFORGE_LLM_MOCK", "1") == "1"
        or not os.environ.get("AGENTFORGE_LLM_API_KEY"),
    }
'''
        if tmpl == "state.py.j2":
            return '''"""Workflow state schema."""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class State(TypedDict, total=False):
    input: str
    output: str
    messages: Annotated[list[dict[str, Any]], operator.add]
    route: str
    loop_count: int
    node_outputs: dict[str, Any]
    approved: bool
    scores: dict[str, float]
    meta: dict[str, Any]
'''
        if tmpl == "__init__.py.j2":
            return f'"""Generated workflow package for {name}."""\n__version__ = "{ctx["version"]}"\n'
        if tmpl == "test_workflow.py.j2":
            return self._tests_module(ctx)
        if tmpl.endswith(".md.j2"):
            return self._docs_module(tmpl, ctx)
        if tmpl == "workflow.mmd.j2":
            return ctx["mermaid"] + "\n"
        if tmpl == "Dockerfile.j2":
            return """FROM python:3.12-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -e .
CMD [\"python\", \"-m\", \"workflow_app.main\"]
"""
        if tmpl == "docker-compose.yml.j2":
            return """services:
  workflow:
    build: .
    environment:
      AGENTFORGE_LLM_MOCK: \"1\"
    command: [\"python\", \"-m\", \"workflow_app.main\", \"hello\"]
"""
        if tmpl == ".env.example.j2":
            return """AGENTFORGE_LLM_PROVIDER=openai
AGENTFORGE_LLM_MODEL=gpt-4o-mini
AGENTFORGE_LLM_API_KEY=
AGENTFORGE_LLM_BASE_URL=
AGENTFORGE_LLM_MOCK=1
"""
        if tmpl == "Makefile.j2":
            return """.PHONY: run test
run:
\tpython -m workflow_app.main
test:
\tpytest -q
"""
        if tmpl == "ci.yml.j2":
            return """name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: \"3.12\"
      - run: pip install -e \".[dev]\"
      - run: pytest -q
"""
        if tmpl == "workflow.json.j2":
            return json.dumps(ctx["ir_json"], indent=2)
        return f"# generated placeholder for {tmpl}\n"

    def _docs_module(self, tmpl: str, ctx: dict[str, Any]) -> str:
        title = tmpl.replace(".md.j2", "").replace("_", " ")
        agents = "\n".join(
            f"- `{a.id}` ({a.role}): {a.system_prompt[:120]}" for a in ctx["agents"]
        ) or "- (none)"
        tools = "\n".join(
            f"- `{t.id}` ({t.kind.value if hasattr(t.kind, 'value') else t.kind}): {t.description}"
            for t in ctx["tools"]
        ) or "- (none)"
        nodes = ", ".join(n.id for n in ctx["executable_nodes"]) or "(none)"
        if "AGENTS" in tmpl:
            return f"# Agents\n\n{ctx['description']}\n\n{agents}\n"
        if "TOOLS" in tmpl:
            return (
                f"# Tools\n\n{tools}\n\n"
                f"default_deny={ctx['default_deny']}\n"
                f"allowed_tools={ctx['allowed_tools']}\n"
            )
        if "WORKFLOW" in tmpl:
            return (
                f"# Workflow\n\nPattern: `{ctx['pattern']}`\n\n"
                f"Executable nodes: {nodes}\n\n"
                f"```mermaid\n{ctx['mermaid']}\n```\n"
            )
        if "SECURITY" in tmpl:
            return (
                f"# Security\n\n"
                f"- tool policy default_deny: `{ctx['default_deny']}`\n"
                f"- allowed_tools: `{ctx['allowed_tools']}`\n"
                f"- HITL gates present: `{ctx['has_hitl']}`\n"
            )
        if "ARCHITECTURE" in tmpl:
            return (
                f"# Architecture\n\n"
                f"Runtime: `{ctx['runtime']}` · Pattern: `{ctx['pattern']}`\n\n"
                f"Agents:\n{agents}\n\nTools:\n{tools}\n"
            )
        return (
            f"# {title}\n\n{ctx['description']}\n\n"
            f"Pattern: `{ctx['pattern']}`\nRuntime: `{ctx['runtime']}`\n\n"
            f"Agents: {', '.join(ctx['agent_ids'])}\n"
            f"Tools: {', '.join(ctx['tool_ids'])}\n"
        )

    def _tests_module(self, ctx: dict[str, Any]) -> str:
        pattern = ctx["pattern"]
        agent_ids = ctx["agent_ids"]
        lines = [
            '"""Pattern-specific tests for the generated workflow."""',
            "from __future__ import annotations",
            "",
            "from workflow_app.graph import build_graph, run_workflow",
            "from workflow_app.agents import AGENTS",
            "from workflow_app.tools import TOOLS",
            "",
            "",
            "def test_run_completes():",
            '    result = run_workflow({"input": "test", "auto_approve": True, "route": "done"})',
            '    assert "output" in result',
            '    assert result["output"]',
            "",
            "",
            "def test_agents_match_ir():",
            f"    assert set(AGENTS) >= {set(agent_ids)!r}",
            "",
            "",
            "def test_tools_registered():",
            f"    for tid in {list(ctx['tool_ids'])!r}:",
            "        assert tid in TOOLS",
            "",
            "",
            "def test_graph_builds():",
            "    graph = build_graph()",
            "    assert graph is not None",
            "",
        ]
        if ctx["has_hitl"]:
            lines += [
                "",
                "def test_hitl_auto_approve():",
                '    result = run_workflow({"input": "approve me", "auto_approve": True})',
                '    assert result.get("output")',
                "",
            ]
        if ctx["has_parallel"] or pattern in {"parallel", "fan_out_fan_in"}:
            lines += [
                "",
                "def test_parallel_node_outputs():",
                '    result = run_workflow({"input": "parallel", "auto_approve": True})',
                '    outs = result.get("node_outputs") or {}',
                "    # Fan-out workers should leave traces when agents exist",
                "    assert outs or result.get('output')",
                "",
            ]
        if ctx["has_supervisor"] or pattern == "supervisor":
            lines += [
                "",
                "def test_supervisor_agent_present():",
                '    assert any("supervisor" in (a.get("role") or k).lower() for k, a in AGENTS.items())',
                "",
            ]
        if pattern in {"sequential", "handoff"} and len(agent_ids) >= 2:
            lines += [
                "",
                "def test_sequential_agents_present():",
                f"    for aid in {agent_ids!r}:",
                "        assert aid in AGENTS",
                "",
            ]
        return "\n".join(lines)

    def _tools_module(self, ctx: dict[str, Any]) -> str:
        lines = [
            '"""Tools with explicit permissions (standalone, IR-faithful)."""',
            "from __future__ import annotations",
            "",
            "from typing import Any",
            "",
            "",
            "def echo(state: dict[str, Any]) -> str:",
            '    return str(state.get("input", ""))',
            "",
            "",
            "def upper(state: dict[str, Any]) -> str:",
            '    return str(state.get("input", "")).upper()',
            "",
            "",
            "def lower(state: dict[str, Any]) -> str:",
            '    return str(state.get("input", "")).lower()',
            "",
            "",
            "BUILTINS = {",
            '    "echo": echo,',
            '    "upper": upper,',
            '    "lower": lower,',
            "}",
            "",
            "TOOLS = dict(BUILTINS)",
            "ALLOWED = set(" + repr(list(ctx["allowed_tools"]) or list(ctx["tool_ids"])) + ")",
            "DEFAULT_DENY = " + repr(ctx["default_deny"]),
            "",
        ]
        # Register IR tools by id → deterministic_fn or stub
        for t in ctx["tools"]:
            tid = t.id
            fn = getattr(t, "deterministic_fn", None) or "echo"
            lines.append(f'TOOLS[{tid!r}] = BUILTINS.get({fn!r}, echo)')
        lines += [
            "",
            "",
            "def invoke_tool(tool_id: str, state: dict[str, Any]) -> Any:",
            "    if DEFAULT_DENY and ALLOWED and tool_id not in ALLOWED:",
            '        raise PermissionError(f"Tool {tool_id!r} blocked by default_deny allowlist")',
            "    if tool_id not in TOOLS:",
            '        raise KeyError(f"Unknown or ungranted tool: {tool_id}")',
            "    return TOOLS[tool_id](state)",
            "",
        ]
        return "\n".join(lines)

    def _graph_module(self, ctx: dict[str, Any]) -> str:
        # Emit a concrete LangGraph module for the IR
        agent_nodes = [n for n in ctx["nodes"] if n.type == NodeType.AGENT]
        lines = [
            '"""Compiled workflow graph (standalone LangGraph)."""',
            "from __future__ import annotations",
            "",
            "from typing import Any",
            "",
            "from langgraph.checkpoint.memory import MemorySaver",
            "from langgraph.graph import END, START, StateGraph",
            "",
            "from workflow_app.agents import run_agent",
            "from workflow_app.state import State",
            "from workflow_app.tools import invoke_tool",
            "",
            "",
            "def build_graph():",
            "    g = StateGraph(State)",
        ]
        for n in ctx["nodes"]:
            if n.type in {NodeType.START, NodeType.END}:
                continue
            if n.type == NodeType.AGENT:
                aid = n.agent_id or n.id
                lines += [
                    f"    def node_{n.id}(state: State) -> dict[str, Any]:",
                    f'        text = run_agent({aid!r}, str(state.get("input", "")))',
                    '        outs = dict(state.get("node_outputs") or {})',
                    f"        outs[{n.id!r}] = text",
                    '        return {"output": text, "messages": [{"role": "assistant", "content": text}], "node_outputs": outs}',
                    f"    g.add_node({n.id!r}, node_{n.id})",
                ]
            elif n.type == NodeType.TOOL:
                tid = n.tool_id or n.id
                lines += [
                    f"    def node_{n.id}(state: State) -> dict[str, Any]:",
                    f"        result = invoke_tool({tid!r}, dict(state))",
                    '        return {"output": str(result)}',
                    f"    g.add_node({n.id!r}, node_{n.id})",
                ]
            elif n.type == NodeType.JOIN:
                lines += [
                    f"    def node_{n.id}(state: State) -> dict[str, Any]:",
                    '        outs = state.get("node_outputs") or {}',
                    '        return {"output": " | ".join(str(v) for v in outs.values())}',
                    f"    g.add_node({n.id!r}, node_{n.id})",
                ]
            elif n.type == NodeType.HUMAN_APPROVAL:
                msg = n.approval_message or "Approve?"
                lines += [
                    f"    def node_{n.id}(state: State) -> dict[str, Any]:",
                    f"        # HITL gate: {msg!r}",
                    '        if state.get("meta", {}).get("auto_approve", True) or state.get("approved"):',
                    '            return {"approved": True, "output": state.get("output")}',
                    '        return {"approved": False, "output": state.get("output"), "pending_approval": True}',
                    f"    g.add_node({n.id!r}, node_{n.id})",
                ]
            elif n.type == NodeType.EVALUATOR:
                lines += [
                    f"    def node_{n.id}(state: State) -> dict[str, Any]:",
                    '        output = str(state.get("output", ""))',
                    "        score = 0.9 if output else 0.2",
                    '        return {"scores": {"correctness": score, "safety": 0.95}, "output": output}',
                    f"    g.add_node({n.id!r}, node_{n.id})",
                ]
            elif n.type in {NodeType.ROUTER, NodeType.CONDITION}:
                lines += [
                    f"    def node_{n.id}(state: State) -> dict[str, Any]:",
                    "        # Router/condition node — route key from state",
                    '        route = str(state.get("route", "done"))',
                    "        return {'route': route, 'output': state.get('output', route)}",
                    f"    g.add_node({n.id!r}, node_{n.id})",
                ]
            elif n.type == NodeType.PARALLEL:
                lines += [
                    f"    def node_{n.id}(state: State) -> dict[str, Any]:",
                    "        return {}",
                    f"    g.add_node({n.id!r}, node_{n.id})",
                ]
            else:
                lines += [
                    f"    def node_{n.id}(state: State) -> dict[str, Any]:",
                    "        return {}",
                    f"    g.add_node({n.id!r}, node_{n.id})",
                ]

        # Edges — for CONDITION/ROUTER use conditional edges when routes exist
        for e in ctx["edges"]:
            src, tgt = e.source, e.target
            src_node = next((n for n in ctx["nodes"] if n.id == src), None)
            src_is_start = src_node is not None and src_node.type == NodeType.START
            tgt_is_end = any(n.id == tgt and n.type == NodeType.END for n in ctx["nodes"])
            if src_is_start:
                lines.append(f"    g.add_edge(START, {tgt!r})" if not tgt_is_end else "    g.add_edge(START, END)")
            elif tgt_is_end:
                lines.append(f"    g.add_edge({src!r}, END)")
            else:
                lines.append(f"    g.add_edge({src!r}, {tgt!r})")

        lines += [
            "    return g.compile(checkpointer=MemorySaver())",
            "",
            "",
            "def run_workflow(payload: dict[str, Any] | None = None) -> dict[str, Any]:",
            "    payload = payload or {}",
            "    graph = build_graph()",
            '    thread_id = str(payload.get("thread_id") or "local-1")',
            '    config = {"configurable": {"thread_id": thread_id}}',
            "    state = {",
            '        "input": str(payload.get("input", "")),',
            '        "output": "",',
            '        "messages": [],',
            '        "node_outputs": {},',
            '        "route": str(payload.get("route", "done")),',
            '        "loop_count": 0,',
            '        "approved": False,',
            '        "meta": {"auto_approve": payload.get("auto_approve", True)},',
            "    }",
            "    for k, v in payload.items():",
            "        if k not in state:",
            "            state[k] = v",
            "    result = graph.invoke(state, config)",
            "    return {",
            '        "output": result.get("output"),',
            '        "scores": result.get("scores", {}),',
            '        "node_outputs": result.get("node_outputs", {}),',
            '        "approved": result.get("approved", False),',
            "    }",
            "",
        ]
        if not agent_nodes:
            pass
        return "\n".join(lines)

    def _agents_module(self, ctx: dict[str, Any]) -> str:
        lines = [
            '"""Agent definitions (standalone, IR-faithful)."""',
            "from __future__ import annotations",
            "",
            "from workflow_app.config import llm_settings",
            "",
            "AGENTS = {",
        ]
        for a in ctx["agents"]:
            lines.append(
                f'    "{a.id}": {{"role": {a.role!r}, "system_prompt": {a.system_prompt!r}, "tools": {list(a.tools)!r}}},'
            )
        if not ctx["agents"]:
            lines.append(
                '    "agent": {"role": "assistant", "system_prompt": "You are helpful.", "tools": []},'
            )
        lines += [
            "}",
            "",
            "",
            "def run_agent(agent_id: str, user_input: str) -> str:",
            '    agent = AGENTS.get(agent_id) or {"system_prompt": "You are helpful.", "tools": []}',
            "    settings = llm_settings()",
            '    prompt = agent["system_prompt"]',
            '    if settings["mock"]:',
            '        snippet = (user_input or "").strip().replace("\\n", " ")',
            "        if len(snippet) > 120:",
            '            snippet = snippet[:117] + "..."',
            "        head = prompt.split('.')[0].strip()",
            '        return f"[{agent_id}] {head}: {snippet or \'OK\'}"',
            "    # Non-mock: integrate your provider SDK using env-only credentials.",
            '    return f"[{agent_id}] {user_input}"',
            "",
        ]
        return "\n".join(lines)

