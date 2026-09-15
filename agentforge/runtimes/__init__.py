"""Runtime registry."""

from __future__ import annotations

from agentforge.runtimes.base import RuntimeAdapter
from agentforge.runtimes.langgraph import LangGraphAdapter
from agentforge.runtimes.microsoft import MicrosoftAdapter

_ADAPTERS: dict[str, RuntimeAdapter] = {}


def get_adapter(name: str) -> RuntimeAdapter:
    """Return a process-wide adapter instance (shared durable checkpoints)."""
    key = (name or "langgraph").lower()
    if key in {"langgraph", "lg", "mock"}:
        cache_key = "langgraph"
        if cache_key not in _ADAPTERS:
            _ADAPTERS[cache_key] = LangGraphAdapter()
        return _ADAPTERS[cache_key]
    if key in {"microsoft", "ms", "agent_framework", "af"}:
        cache_key = "microsoft"
        if cache_key not in _ADAPTERS:
            _ADAPTERS[cache_key] = MicrosoftAdapter()
        return _ADAPTERS[cache_key]
    raise ValueError(f"Unknown runtime '{name}'. Use langgraph or microsoft.")


def reset_adapters() -> None:
    """Drop cached adapters (tests that need isolated checkpointers)."""
    _ADAPTERS.clear()


__all__ = [
    "LangGraphAdapter",
    "MicrosoftAdapter",
    "RuntimeAdapter",
    "get_adapter",
    "reset_adapters",
]
