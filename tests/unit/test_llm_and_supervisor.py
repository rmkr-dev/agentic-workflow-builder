"""Unit tests for LLM mode detection and supervisor mock routing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agentforge.cli.app import normalize_cli_argv
from agentforge.parser.loader import SpecLoader
from agentforge.runtimes import get_adapter
from agentforge.runtimes.base import RunRequest
from agentforge.runtimes.base.helpers import (
    detect_llm_mode,
    live_llm_respond,
    mock_supervisor_route,
    resolve_llm_config,
    supervisor_worker_ids,
)

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def test_detect_llm_mode_defaults_mock(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AGENTFORGE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("AGENTFORGE_LLM_MOCK", "1")
    assert detect_llm_mode() == "mock"
    assert resolve_llm_config()["mode"] == "mock"


def test_detect_llm_mode_live_when_key_and_mock_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTFORGE_LLM_MOCK", "0")
    monkeypatch.setenv("AGENTFORGE_LLM_API_KEY", "sk-test-key")
    assert detect_llm_mode() == "live"
    cfg = resolve_llm_config()
    assert cfg["mode"] == "live"
    assert cfg["mock"] is False


def test_detect_llm_mode_stays_mock_with_key_if_forced(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTFORGE_LLM_MOCK", "1")
    monkeypatch.setenv("AGENTFORGE_LLM_API_KEY", "sk-test-key")
    assert detect_llm_mode() == "mock"
    assert resolve_llm_config()["mock"] is True


def test_live_llm_respond_posts_chat_completions(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTFORGE_LLM_MOCK", "0")
    monkeypatch.setenv("AGENTFORGE_LLM_API_KEY", "sk-test")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "live answer"}}],
    }
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.post.return_value = mock_resp

    with patch("httpx.Client", return_value=mock_client):
        text = live_llm_respond("sys", "hi", agent_id="a", config=resolve_llm_config())
    assert text == "live answer"
    assert mock_client.post.called
    args, kwargs = mock_client.post.call_args
    assert args[0].endswith("/chat/completions")
    assert kwargs["headers"]["Authorization"] == "Bearer sk-test"


def test_normalize_cli_argv_moves_global_flags():
    assert normalize_cli_argv(["run", "wf.yaml", "--non-interactive", "--input", "x"]) == [
        "--non-interactive",
        "run",
        "wf.yaml",
        "--input",
        "x",
    ]
    assert normalize_cli_argv(["--json", "doctor", "--full"]) == ["--json", "doctor", "--full"]
    assert normalize_cli_argv(["doctor", "--json", "--full"]) == ["--json", "doctor", "--full"]


def test_mock_supervisor_route_visits_workers_then_done():
    workers = ["worker_research", "worker_write"]
    assert (
        mock_supervisor_route(workers=workers, node_outputs={}, supervisor_visits=1) == "worker_research"
    )
    assert (
        mock_supervisor_route(
            workers=workers,
            node_outputs={"worker_research": "done"},
            supervisor_visits=2,
        )
        == "worker_write"
    )
    assert (
        mock_supervisor_route(
            workers=workers,
            node_outputs={"worker_research": "a", "worker_write": "b"},
            supervisor_visits=3,
        )
        == "done"
    )


def test_mock_supervisor_ignores_premature_done():
    workers = ["worker_research", "worker_write"]
    assert (
        mock_supervisor_route(
            workers=workers,
            node_outputs={},
            supervisor_visits=1,
            forced_route="done",
        )
        == "worker_research"
    )


def test_supervisor_example_runs_workers():
    ir = SpecLoader().load(EXAMPLES / "04-supervisor" / "workflow.yaml")
    assert supervisor_worker_ids(ir) == ["worker_research", "worker_write"]
    adapter = get_adapter("langgraph")
    adapter.compile(ir)
    result = adapter.run(
        ir,
        RunRequest(input={"input": "research then write a summary", "auto_approve": True}),
    )
    assert result.status.value == "COMPLETED", result.error
    outs = result.output.get("node_outputs") or {}
    assert "worker_research" in outs, outs
    assert "worker_write" in outs, outs
    assert "supervisor" in outs
