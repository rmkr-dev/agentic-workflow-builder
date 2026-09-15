"""Simple memory backends."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class MemoryStore:
    def __init__(self, kind: str = "sqlite", path: str = ".agentforge/memory.db", max_messages: int = 50) -> None:
        self.kind = kind
        self.max_messages = max_messages
        self._buffer: list[dict[str, Any]] = []
        self.path = Path(path)
        if kind == "sqlite":
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(str(self.path)) as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, thread_id TEXT, payload TEXT)"
                )

    def add(self, thread_id: str, message: dict[str, Any]) -> None:
        if self.kind == "none":
            return
        if self.kind == "buffer":
            self._buffer.append(message)
            self._buffer = self._buffer[-self.max_messages :]
            return
        with sqlite3.connect(str(self.path)) as conn:
            conn.execute(
                "INSERT INTO messages(thread_id, payload) VALUES(?,?)",
                (thread_id, json.dumps(message)),
            )

    def list(self, thread_id: str) -> list[dict[str, Any]]:
        if self.kind == "buffer":
            return list(self._buffer)[-self.max_messages :]
        if self.kind == "none":
            return []
        with sqlite3.connect(str(self.path)) as conn:
            rows = conn.execute(
                "SELECT payload FROM messages WHERE thread_id=? ORDER BY id DESC LIMIT ?",
                (thread_id, self.max_messages),
            ).fetchall()
        return [json.loads(r[0]) for r in reversed(rows)]
