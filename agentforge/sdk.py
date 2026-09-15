"""Public SDK surface for AgentForge."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentforge.compiler.engine import CompilerEngine
from agentforge.generator.project import GeneratedProject, ProjectGenerator
from agentforge.ir.models import WorkflowIR
from agentforge.parser.loader import SpecLoader
from agentforge.validator.engine import ValidationEngine


class WorkflowCompiler:
    """High-level compile / generate API.

    Example::

        from agentforge import WorkflowCompiler

        compiler = WorkflowCompiler()
        project = compiler.generate("workflow.yaml")
    """

    def __init__(self, runtime: str = "langgraph") -> None:
        self.runtime = runtime
        self._loader = SpecLoader()
        self._validator = ValidationEngine()
        self._engine = CompilerEngine()
        self._generator = ProjectGenerator()

    def parse(self, source: str | Path | dict[str, Any]) -> WorkflowIR:
        return self._loader.load(source)

    def validate(self, source: str | Path | dict[str, Any] | WorkflowIR):
        ir = source if isinstance(source, WorkflowIR) else self.parse(source)
        return self._validator.validate(ir)

    def compile(self, source: str | Path | dict[str, Any] | WorkflowIR) -> WorkflowIR:
        ir = source if isinstance(source, WorkflowIR) else self.parse(source)
        report = self._validator.validate(ir)
        if report.has_errors:
            raise ValueError(report.format())
        return self._engine.compile(ir, runtime=self.runtime)

    def generate(
        self,
        source: str | Path | dict[str, Any] | WorkflowIR,
        *,
        output_dir: str | Path | None = None,
        runtime: str | None = None,
    ) -> GeneratedProject:
        ir = self.compile(source)
        return self._generator.generate(
            ir,
            output_dir=output_dir,
            runtime=runtime or self.runtime,
        )
