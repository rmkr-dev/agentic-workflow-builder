"""Evaluation system for workflow outputs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agentforge.ir.models import WorkflowIR


class EvalScore(BaseModel):
    metric: str
    score: float
    notes: str = ""


class EvalReport(BaseModel):
    passed: bool
    threshold: float
    scores: list[EvalScore] = Field(default_factory=list)
    overall: float = 0.0
    rubric: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


class EvaluationEngine:
    def evaluate(self, ir: WorkflowIR, output: dict[str, Any]) -> EvalReport:
        text = str(output.get("output", ""))
        rubric = ir.evaluation.rubric
        metrics = ir.evaluation.metrics or ["correctness", "safety"]
        scores: list[EvalScore] = []

        for metric in metrics:
            if metric == "correctness":
                score = 0.9 if text and "blocked" not in text.lower() else 0.3
                scores.append(EvalScore(metric=metric, score=score, notes="heuristic length/safety"))
            elif metric == "safety":
                score = 0.2 if any(x in text.lower() for x in ("password", "api_key", "sk-")) else 0.95
                scores.append(EvalScore(metric=metric, score=score, notes="secret leak heuristic"))
            else:
                scores.append(EvalScore(metric=metric, score=0.8, notes="default"))

        # Prefer runtime scores if present
        runtime_scores = output.get("scores") or {}
        for k, v in runtime_scores.items():
            if isinstance(v, (int, float)):
                scores.append(EvalScore(metric=str(k), score=float(v), notes="runtime"))

        overall = sum(s.score for s in scores) / max(len(scores), 1)
        return EvalReport(
            passed=overall >= ir.evaluation.pass_threshold,
            threshold=ir.evaluation.pass_threshold,
            scores=scores,
            overall=overall,
            rubric=rubric,
        )
