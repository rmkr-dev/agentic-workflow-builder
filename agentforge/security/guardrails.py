"""Guardrail engine: allow / block / modify / escalate."""

from __future__ import annotations

import re
from dataclasses import dataclass

from agentforge.schema import GuardrailAction, GuardrailSpec


@dataclass
class GuardrailDecision:
    action: str
    message: str | None = None
    modified: str | None = None


class GuardrailEngine:
    def __init__(self, specs: list[GuardrailSpec]) -> None:
        self.specs = specs

    def check(
        self,
        text: str,
        *,
        extra_rules: list[str] | None = None,
        default_action: str = "block",
    ) -> GuardrailDecision:
        rules: list[tuple[str, GuardrailAction, str | None]] = []
        for g in self.specs:
            for rule in g.rules:
                rules.append((rule, g.on_match, g.message))
        for rule in extra_rules or []:
            rules.append((rule, GuardrailAction(default_action), None))

        for rule, action, message in rules:
            if self._matches(rule, text):
                if action == GuardrailAction.ALLOW:
                    return GuardrailDecision(action="allow")
                if action == GuardrailAction.BLOCK:
                    return GuardrailDecision(
                        action="block",
                        message=message or f"Blocked by guardrail rule: {rule}",
                    )
                if action == GuardrailAction.MODIFY:
                    modified = re.sub(rule, "[filtered]", text, flags=re.IGNORECASE)
                    return GuardrailDecision(action="modify", modified=modified, message=message)
                if action == GuardrailAction.ESCALATE:
                    return GuardrailDecision(action="escalate", message=message or rule)
        return GuardrailDecision(action="allow")

    def _matches(self, rule: str, text: str) -> bool:
        try:
            return re.search(rule, text, flags=re.IGNORECASE) is not None
        except re.error:
            return rule.lower() in text.lower()
