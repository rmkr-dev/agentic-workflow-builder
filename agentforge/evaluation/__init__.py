"""Evaluation system: heuristics, golden files, schema checks, optional LLM judge."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
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
    mode: str = "heuristic"
    details: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


class EvaluationEngine:
    """Evaluate workflow outputs.

    Modes (combined when configured):
    - heuristic (default): lightweight correctness/safety signals
    - golden: compare against expected output / regex / JSON fields
    - schema: require output keys/types
    - llm_judge: optional, behind AGENTFORGE_EVAL_LLM_JUDGE=1 (mock-safe default)
    """

    def evaluate(
        self,
        ir: WorkflowIR,
        output: dict[str, Any],
        *,
        golden: dict[str, Any] | Path | str | None = None,
        use_llm_judge: bool | None = None,
    ) -> EvalReport:
        text = str(output.get("output", ""))
        rubric = ir.evaluation.rubric
        metrics = list(ir.evaluation.metrics or ["correctness", "safety"])
        scores: list[EvalScore] = []
        details: dict[str, Any] = {}
        modes: list[str] = ["heuristic"]

        # --- heuristics ---
        for metric in metrics:
            if metric == "correctness":
                score = 0.9 if text and "blocked" not in text.lower() else 0.3
                scores.append(EvalScore(metric=metric, score=score, notes="heuristic length/safety"))
            elif metric == "safety":
                score = 0.2 if any(x in text.lower() for x in ("password", "api_key", "sk-")) else 0.95
                scores.append(EvalScore(metric=metric, score=score, notes="secret leak heuristic"))
            else:
                scores.append(EvalScore(metric=metric, score=0.8, notes="default"))

        runtime_scores = output.get("scores") or {}
        for k, v in runtime_scores.items():
            if isinstance(v, (int, float)):
                scores.append(EvalScore(metric=str(k), score=float(v), notes="runtime"))

        # --- golden file / dict ---
        golden_payload = self._load_golden(golden, ir)
        if golden_payload:
            modes.append("golden")
            g_score, g_notes, g_ok = self._score_golden(output, golden_payload)
            scores.append(EvalScore(metric="golden", score=g_score, notes=g_notes))
            details["golden"] = {"passed": g_ok, "notes": g_notes, "expected": golden_payload}

        # --- schema checks from evaluation config or golden ---
        schema = None
        if isinstance(golden_payload, dict):
            schema = golden_payload.get("schema") or golden_payload.get("output_schema")
        # Prefer explicit fields on EvaluationSpec
        schema = getattr(ir.evaluation, "output_schema", None) or schema
        if schema:
            modes.append("schema")
            s_score, s_notes, s_ok = self._score_schema(output, schema)
            scores.append(EvalScore(metric="schema", score=s_score, notes=s_notes))
            details["schema"] = {"passed": s_ok, "notes": s_notes}

        # --- optional LLM judge ---
        judge_flag = (
            use_llm_judge
            if use_llm_judge is not None
            else os.environ.get("AGENTFORGE_EVAL_LLM_JUDGE", "0") == "1"
        )
        if judge_flag:
            modes.append("llm_judge")
            j_score, j_notes = self._llm_judge(ir, text, rubric)
            scores.append(EvalScore(metric="llm_judge", score=j_score, notes=j_notes))
            details["llm_judge"] = {"score": j_score, "notes": j_notes}

        overall = sum(s.score for s in scores) / max(len(scores), 1)
        # Hard fail golden/schema if present and failed
        hard_fail = False
        if details.get("golden") and not details["golden"]["passed"]:
            hard_fail = True
        if details.get("schema") and not details["schema"]["passed"]:
            hard_fail = True

        passed = (overall >= ir.evaluation.pass_threshold) and not hard_fail
        return EvalReport(
            passed=passed,
            threshold=ir.evaluation.pass_threshold,
            scores=scores,
            overall=overall,
            rubric=rubric,
            mode="+".join(modes),
            details=details,
        )

    def _load_golden(
        self,
        golden: dict[str, Any] | Path | str | None,
        ir: WorkflowIR,
    ) -> dict[str, Any] | None:
        if golden is None:
            # Convention: sibling golden.json next to nothing — check env path
            path = os.environ.get("AGENTFORGE_EVAL_GOLDEN")
            if path:
                golden = path
            else:
                # IR evaluation may carry golden_path
                gp = getattr(ir.evaluation, "golden_path", None)
                if gp:
                    golden = gp
                else:
                    return None
        if isinstance(golden, dict):
            return golden
        path = Path(str(golden))
        if not path.exists():
            return {"__missing__": str(path)}
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() in {".yaml", ".yml"}:
            import yaml

            data = yaml.safe_load(text)
            return data if isinstance(data, dict) else {"expected_output": data}
        data = json.loads(text)
        return data if isinstance(data, dict) else {"expected_output": data}

    def _score_golden(
        self, output: dict[str, Any], golden: dict[str, Any]
    ) -> tuple[float, str, bool]:
        if golden.get("__missing__"):
            return 0.0, f"golden file missing: {golden['__missing__']}", False

        text = str(output.get("output", ""))
        ok = True
        notes: list[str] = []

        if "expected_output" in golden:
            expected = str(golden["expected_output"])
            if golden.get("match") == "exact":
                if text != expected:
                    ok = False
                    notes.append("exact output mismatch")
            elif golden.get("match") == "contains" or "contains" not in golden:
                if expected and expected not in text:
                    # Also allow expected as regex if match=regex
                    if golden.get("match") == "regex":
                        if not re.search(expected, text, re.IGNORECASE):
                            ok = False
                            notes.append("regex mismatch")
                    else:
                        ok = False
                        notes.append("expected substring missing")
                else:
                    notes.append("contains ok")

        if "contains" in golden:
            needle = str(golden["contains"])
            if needle not in text:
                ok = False
                notes.append(f"missing contains={needle!r}")
            else:
                notes.append("contains ok")

        if "regex" in golden:
            if not re.search(str(golden["regex"]), text, re.IGNORECASE | re.DOTALL):
                ok = False
                notes.append("regex mismatch")
            else:
                notes.append("regex ok")

        if "min_length" in golden:
            if len(text) < int(golden["min_length"]):
                ok = False
                notes.append("below min_length")

        if "forbidden" in golden:
            for bad in golden["forbidden"] or []:
                if str(bad).lower() in text.lower():
                    ok = False
                    notes.append(f"forbidden={bad!r}")

        for key, expected in (golden.get("fields") or {}).items():
            actual = output.get(key)
            if actual != expected:
                ok = False
                notes.append(f"field {key} mismatch")

        score = 1.0 if ok else 0.0
        return score, "; ".join(notes) or ("pass" if ok else "fail"), ok

    def _score_schema(
        self, output: dict[str, Any], schema: dict[str, Any]
    ) -> tuple[float, str, bool]:
        """Lightweight schema: required keys and optional type names."""
        required = list(schema.get("required") or schema.get("required_keys") or [])
        types = dict(schema.get("properties") or schema.get("types") or {})
        missing = [k for k in required if k not in output]
        type_errors: list[str] = []
        type_map = {
            "string": str,
            "str": str,
            "number": (int, float),
            "integer": int,
            "int": int,
            "object": dict,
            "dict": dict,
            "array": list,
            "list": list,
            "boolean": bool,
            "bool": bool,
        }
        for key, typ in types.items():
            if key not in output:
                continue
            expected = typ.get("type") if isinstance(typ, dict) else typ
            py = type_map.get(str(expected).lower())
            if py and not isinstance(output[key], py):
                type_errors.append(f"{key} expected {expected}")
        ok = not missing and not type_errors
        notes = []
        if missing:
            notes.append(f"missing={missing}")
        if type_errors:
            notes.extend(type_errors)
        return (1.0 if ok else 0.0), ("; ".join(notes) or "schema ok"), ok

    def _llm_judge(self, ir: WorkflowIR, text: str, rubric: str) -> tuple[float, str]:
        """Optional LLM-as-judge. Mock-safe: deterministic score when mock mode."""
        mock = os.environ.get("AGENTFORGE_LLM_MOCK", "1") == "1" or not os.environ.get(
            "AGENTFORGE_LLM_API_KEY"
        )
        if mock:
            # Deterministic mock judge: reward non-empty, non-blocked outputs
            score = 0.85 if text and "blocked" not in text.lower() else 0.4
            return score, "mock llm-as-judge"
        try:
            from agentforge.runtimes.base.helpers import llm_respond

            prompt = (
                f"Rubric: {rubric}\n"
                f"Output:\n{text[:2000]}\n"
                "Reply with JSON only: {\"score\": 0.0-1.0, \"notes\": \"...\"}"
            )
            raw = llm_respond("You are an evaluation judge.", prompt, agent_id="eval-judge")
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                return float(data.get("score", 0.5)), str(data.get("notes", "llm judge"))
            return 0.5, f"unparseable judge response: {raw[:120]}"
        except Exception as exc:  # pragma: no cover
            return 0.5, f"llm judge error: {exc}"
