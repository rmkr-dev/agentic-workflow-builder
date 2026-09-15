"""Runtime registry."""

from __future__ import annotations

from agentforge.runtimes.base import RuntimeAdapter
from agentforge.runtimes.langgraph import LangGraphAdapter
from agentforge.runtimes.microsoft import MicrosoftAdapter


def get_adapter(name: str) -> RuntimeAdapter:
    key = (name or "langgraph").lower()
    if key in {"langgraph", "lg"}:
        return LangGraphAdapter()
    if key in {"microsoft", "ms", "agent_framework", "af"}:
        return MicrosoftAdapter()
    if key == "mock":
        return LangGraphAdapter()  # mock LLM path inside LangGraph adapter
    raise ValueError(f"Unknown runtime '{name}'. Use langgraph or microsoft.")


__all__ = ["LangGraphAdapter", "MicrosoftAdapter", "RuntimeAdapter", "get_adapter"]
