"""Policy engines for budget, tools, models, approval, security, execution."""

from __future__ import annotations

import time

from agentforge.schema import PoliciesSpec


class PolicyViolation(RuntimeError):
    pass


class PolicyEngine:
    def __init__(self, policies: PoliciesSpec) -> None:
        self.policies = policies
        self.steps = 0
        self.llm_calls = 0
        self.tool_calls = 0
        self.started_at = time.monotonic()

    def reset(self) -> None:
        self.steps = 0
        self.llm_calls = 0
        self.tool_calls = 0
        self.started_at = time.monotonic()

    def check_timeout(self) -> None:
        b = self.policies.budget
        limit = float(b.timeout_seconds or 0)
        if limit <= 0:
            return
        elapsed = time.monotonic() - self.started_at
        if elapsed > limit:
            raise PolicyViolation(
                f"timeout_seconds exceeded ({limit:.1f}s elapsed {elapsed:.1f}s)"
            )

    def check_budget_step(self) -> None:
        self.check_timeout()
        self.steps += 1
        self.llm_calls += 1
        b = self.policies.budget
        if self.steps > b.max_steps:
            raise PolicyViolation(f"max_steps exceeded ({b.max_steps})")
        if self.llm_calls > b.max_llm_calls:
            raise PolicyViolation(f"max_llm_calls exceeded ({b.max_llm_calls})")

    def check_tool(self, tool_id: str) -> None:
        self.check_timeout()
        self.tool_calls += 1
        b = self.policies.budget
        if self.tool_calls > b.max_tool_calls:
            raise PolicyViolation(f"max_tool_calls exceeded ({b.max_tool_calls})")
        tp = self.policies.tool
        if tp.default_deny and tp.allowed_tools and tool_id not in tp.allowed_tools:
            raise PolicyViolation(f"tool '{tool_id}' not allowlisted")

    def check_model(self, provider: str, model: str) -> None:
        mp = self.policies.model
        if mp.allowed_providers and provider not in mp.allowed_providers:
            raise PolicyViolation(f"provider '{provider}' not allowed")
        if mp.allowed_models and model not in mp.allowed_models:
            raise PolicyViolation(f"model '{model}' not allowed")
