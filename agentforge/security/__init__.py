"""Security helpers."""

from __future__ import annotations

from agentforge.runtimes.base.helpers import SECRET_PATTERNS, redact_secrets
from agentforge.security.guardrails import GuardrailDecision, GuardrailEngine


def contains_secrets(text: str) -> bool:
    return any(p.search(text) for p in SECRET_PATTERNS)


__all__ = ["GuardrailDecision", "GuardrailEngine", "contains_secrets", "redact_secrets"]
