"""Workflow IR validation with structured diagnostics."""

from __future__ import annotations

from agentforge.ir.models import WorkflowIR
from agentforge.schema import NodeType, ToolKind
from agentforge.validator.diagnostics import Diagnostic, DiagnosticReport, Severity


class ValidationEngine:
    def validate(self, ir: WorkflowIR) -> DiagnosticReport:
        report = DiagnosticReport()
        node_ids = {n.id for n in ir.nodes}

        if not ir.name:
            report.add(
                Diagnostic(
                    code="WF001",
                    severity=Severity.ERROR,
                    path="metadata.name",
                    message="Workflow name is required",
                    suggestion="Set metadata.name to a non-empty string",
                )
            )

        starts = [n for n in ir.nodes if n.type == NodeType.START]
        ends = [n for n in ir.nodes if n.type == NodeType.END]
        if len(starts) != 1:
            report.add(
                Diagnostic(
                    code="WF002",
                    severity=Severity.ERROR,
                    path="spec.nodes",
                    message=f"Expected exactly one START node, found {len(starts)}",
                    suggestion="Add a single node with type: START",
                )
            )
        if len(ends) < 1:
            report.add(
                Diagnostic(
                    code="WF003",
                    severity=Severity.ERROR,
                    path="spec.nodes",
                    message="At least one END node is required",
                    suggestion="Add a node with type: END",
                )
            )

        # Duplicate IDs
        seen: set[str] = set()
        for n in ir.nodes:
            if n.id in seen:
                report.add(
                    Diagnostic(
                        code="WF004",
                        severity=Severity.ERROR,
                        path=f"spec.nodes[{n.id}]",
                        message=f"Duplicate node id '{n.id}'",
                        suggestion="Make node ids unique",
                    )
                )
            seen.add(n.id)

        for e in ir.edges:
            if e.source not in node_ids:
                report.add(
                    Diagnostic(
                        code="WF005",
                        severity=Severity.ERROR,
                        path="spec.edges",
                        message=f"Edge source '{e.source}' does not exist",
                        suggestion="Reference an existing node id",
                    )
                )
            if e.target not in node_ids:
                report.add(
                    Diagnostic(
                        code="WF006",
                        severity=Severity.ERROR,
                        path="spec.edges",
                        message=f"Edge target '{e.target}' does not exist",
                        suggestion="Reference an existing node id",
                    )
                )

        # Reachability from start
        if starts:
            reachable = self._reachable(starts[0].id, ir)
            for n in ir.nodes:
                if n.id not in reachable and n.type != NodeType.END:
                    report.add(
                        Diagnostic(
                            code="WF007",
                            severity=Severity.WARNING,
                            path=f"spec.nodes[{n.id}]",
                            message=f"Node '{n.id}' is unreachable from START",
                            suggestion="Add edges from the main path or remove the node",
                        )
                    )

        # Agent/tool refs
        for n in ir.nodes:
            if n.type == NodeType.AGENT:
                if not n.agent_id:
                    report.add(
                        Diagnostic(
                            code="WF010",
                            severity=Severity.ERROR,
                            path=f"spec.nodes[{n.id}].agent",
                            message="AGENT nodes require an agent reference",
                            suggestion="Set agent: <agent_id>",
                        )
                    )
                elif n.agent_id not in ir.agents:
                    # Allow synthetic agent ids from pattern expansion
                    report.add(
                        Diagnostic(
                            code="WF011",
                            severity=Severity.WARNING,
                            path=f"spec.nodes[{n.id}].agent",
                            message=f"Agent '{n.agent_id}' not declared in spec.agents",
                            suggestion="Declare the agent or rely on generator defaults",
                        )
                    )
            if n.type == NodeType.TOOL and n.tool_id and n.tool_id not in ir.tools:
                # tool_id may be agent-as-tool
                if n.tool_id not in ir.agents:
                    report.add(
                        Diagnostic(
                            code="WF012",
                            severity=Severity.ERROR,
                            path=f"spec.nodes[{n.id}].tool",
                            message=f"Tool '{n.tool_id}' not declared",
                            suggestion="Add the tool under spec.tools or grant via MCP",
                        )
                    )
            if n.type == NodeType.CONDITION and not n.condition_expr and not n.routes:
                report.add(
                    Diagnostic(
                        code="WF013",
                        severity=Severity.ERROR,
                        path=f"spec.nodes[{n.id}]",
                        message="CONDITION nodes require condition or routes",
                        suggestion="Set condition and/or routes",
                    )
                )
            if n.type == NodeType.LOOP and n.max_iterations < 1:
                report.add(
                    Diagnostic(
                        code="WF014",
                        severity=Severity.ERROR,
                        path=f"spec.nodes[{n.id}].max_iterations",
                        message="LOOP max_iterations must be >= 1",
                        suggestion="Set a positive bound",
                    )
                )
            if n.type == NodeType.SUBWORKFLOW and not n.subworkflow_id:
                report.add(
                    Diagnostic(
                        code="WF015",
                        severity=Severity.ERROR,
                        path=f"spec.nodes[{n.id}].subworkflow",
                        message="SUBWORKFLOW nodes require subworkflow id",
                        suggestion="Set subworkflow: <id>",
                    )
                )

        # Tool permissions / shell policy
        for tid, tool in ir.tools.items():
            if tool.kind == ToolKind.CLI and tool.permissions.allow_shell:
                if ir.policies.security.allow_unrestricted_shell:
                    report.add(
                        Diagnostic(
                            code="SEC001",
                            severity=Severity.WARNING,
                            path=f"spec.tools[{tid}].permissions",
                            message="Unrestricted shell is enabled for a CLI tool",
                            suggestion="Prefer allow_shell=false with allowed_commands allowlist",
                        )
                    )
            if tool.kind == ToolKind.MCP:
                server = ir.mcp_servers.get(tool.mcp_server or "")
                if not server:
                    report.add(
                        Diagnostic(
                            code="MCP001",
                            severity=Severity.ERROR,
                            path=f"spec.tools[{tid}].mcp_server",
                            message=f"MCP server '{tool.mcp_server}' not declared",
                            suggestion="Add the server under spec.mcp_servers",
                        )
                    )
                elif tool.mcp_tool and tool.mcp_tool not in server.granted_tools:
                    report.add(
                        Diagnostic(
                            code="MCP002",
                            severity=Severity.ERROR,
                            path=f"spec.tools[{tid}].mcp_tool",
                            message=f"MCP tool '{tool.mcp_tool}' is not in granted_tools",
                            suggestion="Add an explicit grant on the MCP server",
                        )
                    )

        # Default-deny tools policy
        if ir.policies.tool.default_deny and ir.policies.tool.allowed_tools:
            for tid in ir.tools:
                if tid not in ir.policies.tool.allowed_tools:
                    report.add(
                        Diagnostic(
                            code="POL001",
                            severity=Severity.WARNING,
                            path="spec.policies.tool.allowed_tools",
                            message=f"Tool '{tid}' not in allowed_tools allowlist",
                            suggestion="Add the tool id to policies.tool.allowed_tools",
                        )
                    )

        if ir.runtime not in {"langgraph", "microsoft", "mock"}:
            report.add(
                Diagnostic(
                    code="RT001",
                    severity=Severity.ERROR,
                    path="spec.runtime",
                    message=f"Unknown runtime '{ir.runtime}'",
                    suggestion="Use langgraph, microsoft, or mock",
                )
            )

        return report

    def _reachable(self, start: str, ir: WorkflowIR) -> set[str]:
        adj: dict[str, list[str]] = {n.id: [] for n in ir.nodes}
        for e in ir.edges:
            adj.setdefault(e.source, []).append(e.target)
        seen: set[str] = set()
        stack = [start]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(adj.get(cur, []))
        return seen
