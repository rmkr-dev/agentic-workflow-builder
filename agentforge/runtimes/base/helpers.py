"""Shared runtime helpers: mock LLM, expression eval, state store."""

from __future__ import annotations

import ast
import json
import os
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any


SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"]?[\w-]{8,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
]


def new_thread_id() -> str:
    return f"run-{uuid.uuid4().hex[:12]}"


def resolve_llm_config(agent_llm: Any) -> dict[str, Any]:
    """Resolve provider-neutral LLM settings from environment only."""
    model = os.environ.get(getattr(agent_llm, "model_env", "AGENTFORGE_LLM_MODEL")) or agent_llm.model
    api_key = os.environ.get(getattr(agent_llm, "api_key_env", "AGENTFORGE_LLM_API_KEY"), "")
    base_url = os.environ.get(getattr(agent_llm, "base_url_env", "AGENTFORGE_LLM_BASE_URL"), "")
    provider = os.environ.get("AGENTFORGE_LLM_PROVIDER", agent_llm.provider)
    use_mock = os.environ.get("AGENTFORGE_LLM_MOCK", "1") == "1" or not api_key
    return {
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "temperature": getattr(agent_llm, "temperature", 0.0),
        "mock": use_mock,
    }


def mock_llm_respond(system_prompt: str, user_input: str, *, agent_id: str = "agent") -> str:
    """Deterministic mock LLM used when no API key is configured."""
    snippet = (user_input or "").strip().replace("\n", " ")
    if len(snippet) > 120:
        snippet = snippet[:117] + "..."
    return f"[{agent_id}] {system_prompt.split('.')[0].strip()}: {snippet or 'OK'}"


SAFE_BUILTINS: dict[str, Any] = {
    "True": True,
    "False": False,
    "None": None,
    "len": len,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "min": min,
    "max": max,
    "abs": abs,
}


def eval_condition(expr: str, state: dict[str, Any]) -> bool:
    """Safely evaluate a boolean expression against workflow state."""
    if not expr:
        return True
    # Simple route sugar
    if expr in state:
        return bool(state[expr])
    try:
        tree = ast.parse(expr, mode="eval")
        for node in ast.walk(tree):
            if isinstance(node, (ast.Call, ast.Attribute, ast.Lambda, ast.Import, ast.ImportFrom)):
                # Allow attribute only on names already in state via restricted compile
                if isinstance(node, ast.Call):
                    raise ValueError("function calls not allowed in conditions")
                if isinstance(node, (ast.Lambda, ast.Import, ast.ImportFrom)):
                    raise ValueError("unsafe expression")
        code = compile(tree, "<condition>", "eval")
        return bool(eval(code, {"__builtins__": SAFE_BUILTINS}, dict(state)))  # noqa: S307
    except Exception:
        # Fallback: equality forms like "route == 'a'"
        m = re.match(r"^(\w+)\s*==\s*['\"]([^'\"]+)['\"]$", expr.strip())
        if m:
            return str(state.get(m.group(1))) == m.group(2)
        return False


def apply_transform(expr: str, state: dict[str, Any]) -> dict[str, Any]:
    if not expr:
        return state
    # Support "output = input" style and JSON merge patches
    if expr.strip().startswith("{"):
        patch = json.loads(expr)
        return {**state, **patch}
    m = re.match(r"^(\w+)\s*=\s*(.+)$", expr.strip())
    if m:
        key, rhs = m.group(1), m.group(2).strip()
        if rhs in state:
            state = {**state, key: state[rhs]}
        else:
            try:
                state = {**state, key: ast.literal_eval(rhs)}
            except Exception:
                state = {**state, key: rhs.strip("'\"")}
    return state


def redact_secrets(text: str) -> str:
    out = text
    for pat in SECRET_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    return out


class SQLiteRunStore:
    """Local SQLite store for checkpoints, events, and run metadata."""

    def __init__(self, path: str | Path = ".agentforge/runs.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                  thread_id TEXT PRIMARY KEY,
                  status TEXT NOT NULL,
                  state_json TEXT NOT NULL,
                  checkpoint_id TEXT,
                  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  thread_id TEXT NOT NULL,
                  event_type TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS cancelled (
                  thread_id TEXT PRIMARY KEY
                );
                """
            )

    def save_run(
        self,
        thread_id: str,
        status: str,
        state: dict[str, Any],
        checkpoint_id: str | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO runs(thread_id, status, state_json, checkpoint_id)
                VALUES(?,?,?,?)
                ON CONFLICT(thread_id) DO UPDATE SET
                  status=excluded.status,
                  state_json=excluded.state_json,
                  checkpoint_id=excluded.checkpoint_id,
                  updated_at=CURRENT_TIMESTAMP
                """,
                (thread_id, status, json.dumps(state), checkpoint_id),
            )

    def get_run(self, thread_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM runs WHERE thread_id=?", (thread_id,)).fetchone()
            if not row:
                return None
            return {
                "thread_id": row["thread_id"],
                "status": row["status"],
                "state": json.loads(row["state_json"]),
                "checkpoint_id": row["checkpoint_id"],
            }

    def add_event(self, thread_id: str, event_type: str, payload: dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO events(thread_id, event_type, payload_json) VALUES(?,?,?)",
                (thread_id, event_type, json.dumps(payload)),
            )

    def list_events(self, thread_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT event_type, payload_json, created_at FROM events WHERE thread_id=? ORDER BY id",
                (thread_id,),
            ).fetchall()
            return [
                {
                    "type": r["event_type"],
                    "payload": json.loads(r["payload_json"]),
                    "at": r["created_at"],
                }
                for r in rows
            ]

    def cancel(self, thread_id: str) -> None:
        with self._conn() as conn:
            conn.execute("INSERT OR IGNORE INTO cancelled(thread_id) VALUES(?)", (thread_id,))
            conn.execute(
                "UPDATE runs SET status=? WHERE thread_id=?",
                ("CANCELLED", thread_id),
            )

    def is_cancelled(self, thread_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM cancelled WHERE thread_id=?", (thread_id,)
            ).fetchone()
            return row is not None
