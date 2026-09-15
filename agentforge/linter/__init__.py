"""Best-practice linter for workflow specs."""

from __future__ import annotations

from agentforge.ir.models import WorkflowIR
from agentforge.schema import NodeType
from agentforge.validator.diagnostics import Diagnostic, DiagnosticReport, Severity


class Linter:
    def lint(self, ir: WorkflowIR) -> DiagnosticReport:
        report = DiagnosticReport()

        if not ir.description:
            report.add(
                Diagnostic(
                    code="LINT001",
                    severity=Severity.INFO,
                    path="metadata.description",
                    message="Workflow has no description",
                    suggestion="Add a short description for generated docs",
                )
            )

        agent_nodes = [n for n in ir.nodes if n.type == NodeType.AGENT]
        if len(agent_nodes) > 8:
            report.add(
                Diagnostic(
                    code="LINT002",
                    severity=Severity.WARNING,
                    path="spec.nodes",
                    message=f"Large agent count ({len(agent_nodes)}); consider subworkflows",
                    suggestion="Extract nested flows into SUBWORKFLOW nodes",
                )
            )

        for n in ir.nodes:
            if n.type == NodeType.LOOP and n.max_iterations > 20:
                report.add(
                    Diagnostic(
                        code="LINT003",
                        severity=Severity.WARNING,
                        path=f"spec.nodes[{n.id}].max_iterations",
                        message="High loop bound may cause runaway cost",
                        suggestion="Keep max_iterations modest and rely on policies.budget",
                    )
                )
            if n.type == NodeType.HUMAN_APPROVAL and not n.approval_message:
                report.add(
                    Diagnostic(
                        code="LINT004",
                        severity=Severity.INFO,
                        path=f"spec.nodes[{n.id}].approval_message",
                        message="HITL node missing approval_message",
                        suggestion="Provide a clear human-facing prompt",
                    )
                )

        if ir.evaluation.enabled and not ir.evaluation.rubric:
            report.add(
                Diagnostic(
                    code="LINT005",
                    severity=Severity.WARNING,
                    path="spec.evaluation.rubric",
                    message="Evaluation enabled without rubric",
                    suggestion="Define evaluation criteria",
                )
            )

        if not ir.policies.tool.default_deny:
            report.add(
                Diagnostic(
                    code="LINT006",
                    severity=Severity.WARNING,
                    path="spec.policies.tool.default_deny",
                    message="default_deny is false — tools are open by default",
                    suggestion="Prefer default_deny: true with explicit allowlists",
                )
            )

        # Fan-out without join
        parallels = [n for n in ir.nodes if n.type == NodeType.PARALLEL]
        joins = [n for n in ir.nodes if n.type == NodeType.JOIN]
        if parallels and not joins:
            report.add(
                Diagnostic(
                    code="LINT007",
                    severity=Severity.WARNING,
                    path="spec.nodes",
                    message="PARALLEL node present without JOIN",
                    suggestion="Add a JOIN node for fan-in synchronization",
                )
            )

        return report
