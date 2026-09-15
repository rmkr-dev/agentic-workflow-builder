"""Structured diagnostic errors for validator/linter."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Diagnostic(BaseModel):
    code: str
    severity: Severity
    path: str
    message: str
    suggestion: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    def format_line(self) -> str:
        sug = f" Suggestion: {self.suggestion}" if self.suggestion else ""
        return f"[{self.severity.value.upper()}] {self.code} at {self.path}: {self.message}.{sug}"


class DiagnosticReport(BaseModel):
    diagnostics: list[Diagnostic] = Field(default_factory=list)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == Severity.WARNING]

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    def add(self, diagnostic: Diagnostic) -> None:
        self.diagnostics.append(diagnostic)

    def extend(self, items: list[Diagnostic]) -> None:
        self.diagnostics.extend(items)

    def format(self) -> str:
        if not self.diagnostics:
            return "OK - no diagnostics"
        return "\n".join(d.format_line() for d in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": not self.has_errors,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "diagnostics": [d.model_dump() for d in self.diagnostics],
        }
