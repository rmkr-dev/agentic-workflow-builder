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

SUPERVISOR_ROLES = frozenset({"supervisor", "orchestrator", "manager", "router"})
DEFAULT_MOCK_SUPERVISOR_HOPS = 8


def new_thread_id() -> str:
    return f"run-{uuid.uuid4().hex[:12]}"


def detect_llm_mode() -> str:
    """Return ``mock`` or ``live`` based on env (default mock for CI)."""
    forced_mock = os.environ.get("AGENTFORGE_LLM_MOCK", "1").strip().lower()
    if forced_mock in {"1", "true", "yes", "on"}:
        return "mock"
    api_key = (
        os.environ.get("AGENTFORGE_LLM_API_KEY", "").strip()
        or os.environ.get("OPENAI_API_KEY", "").strip()
    )
    return "live" if api_key else "mock"


def resolve_llm_config(agent_llm: Any = None) -> dict[str, Any]:
    """Resolve provider-neutral LLM settings from environment only."""
    model_env = getattr(agent_llm, "model_env", "AGENTFORGE_LLM_MODEL") if agent_llm else "AGENTFORGE_LLM_MODEL"
    key_env = getattr(agent_llm, "api_key_env", "AGENTFORGE_LLM_API_KEY") if agent_llm else "AGENTFORGE_LLM_API_KEY"
    base_env = getattr(agent_llm, "base_url_env", "AGENTFORGE_LLM_BASE_URL") if agent_llm else "AGENTFORGE_LLM_BASE_URL"
    default_model = getattr(agent_llm, "model", "gpt-4o-mini") if agent_llm else "gpt-4o-mini"
    default_provider = getattr(agent_llm, "provider", "openai") if agent_llm else "openai"
    temperature = getattr(agent_llm, "temperature", 0.0) if agent_llm else 0.0
    max_tokens = getattr(agent_llm, "max_tokens", None) if agent_llm else None

    model = os.environ.get(model_env) or default_model
    api_key = os.environ.get(key_env, "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()
    base_url = os.environ.get(base_env, "").strip()
    provider = os.environ.get("AGENTFORGE_LLM_PROVIDER", default_provider)
    # Default mock=1 keeps CI deterministic; live requires MOCK disabled + API key
    forced_mock = os.environ.get("AGENTFORGE_LLM_MOCK", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    mode = "mock" if forced_mock or not api_key else "live"
    return {
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "mock": mode == "mock",
        "mode": mode,
    }


def mock_llm_respond(system_prompt: str, user_input: str, *, agent_id: str = "agent") -> str:
    """Deterministic mock LLM used when no API key is configured."""
    snippet = (user_input or "").strip().replace("\n", " ")
    if len(snippet) > 120:
        snippet = snippet[:117] + "..."
    return f"[{agent_id}] {system_prompt.split('.')[0].strip()}: {snippet or 'OK'}"


def live_llm_respond(
    system_prompt: str,
    user_input: str,
    *,
    agent_id: str = "agent",
    config: dict[str, Any] | None = None,
) -> str:
    """Call an OpenAI-compatible chat completions endpoint using env credentials."""
    import httpx

    cfg = config or resolve_llm_config()
    api_key = cfg.get("api_key") or ""
    if not api_key:
        raise RuntimeError("live LLM requested but no API key is configured")
    base = (cfg.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    url = f"{base}/chat/completions"
    payload: dict[str, Any] = {
        "model": cfg.get("model") or "gpt-4o-mini",
        "temperature": float(cfg.get("temperature") or 0.0),
        "messages": [
            {"role": "system", "content": system_prompt or f"You are {agent_id}."},
            {"role": "user", "content": user_input or ""},
        ],
    }
    if cfg.get("max_tokens"):
        payload["max_tokens"] = int(cfg["max_tokens"])
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    try:
        return str(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"unexpected LLM response shape: {data!r}") from exc


def llm_respond(
    system_prompt: str,
    user_input: str,
    *,
    agent_id: str = "agent",
    config: dict[str, Any] | None = None,
) -> str:
    """Dispatch to mock or live provider based on resolved config."""
    cfg = config or resolve_llm_config()
    if cfg.get("mock", True):
        return mock_llm_respond(system_prompt, user_input, agent_id=agent_id)
    return live_llm_respond(system_prompt, user_input, agent_id=agent_id, config=cfg)


def supervisor_worker_ids(ir: Any) -> list[str]:
    """Infer worker agent/node ids for supervisor-style graphs."""
    nodes = list(getattr(ir, "nodes", []) or [])
    router_targets: list[str] = []
    for n in nodes:
        ntype = getattr(n, "type", None)
        ntype_val = str(getattr(ntype, "value", ntype) or "").upper()
        if ntype_val in {"ROUTER", "CONDITION"}:
            routes = dict(getattr(n, "routes", {}) or {})
            for label, target in routes.items():
                if label == "done" or target in {"end", "END"}:
                    continue
                if target not in router_targets:
                    router_targets.append(target)
    if router_targets:
        return router_targets
    workers: list[str] = []
    agents = getattr(ir, "agents", {}) or {}
    for agent_id, agent in agents.items():
        role = str(getattr(agent, "role", "") or "").lower()
        if role in SUPERVISOR_ROLES:
            continue
        workers.append(agent_id)
    return workers


def mock_supervisor_route(
    *,
    workers: list[str],
    node_outputs: dict[str, Any],
    user_input: str = "",
    supervisor_visits: int = 1,
    max_hops: int = DEFAULT_MOCK_SUPERVISOR_HOPS,
    forced_route: str | None = None,
) -> str:
    """Pick next worker or ``done`` for deterministic mock supervisor routing.

    Visits workers that have not yet produced outputs (keyword-biased order),
    then finishes. Bounded by ``max_hops``.
    """
    if forced_route and forced_route not in {"", "auto"}:
        # Ignore premature done on the first tick so examples invoke workers
        if forced_route == "done" and supervisor_visits <= 1 and workers:
            pass
        # Ignore routes to workers that already produced output (avoids loops)
        elif forced_route in workers and forced_route in node_outputs:
            pass
        elif forced_route in set(workers) | {"done"}:
            return forced_route

    if supervisor_visits > max_hops or not workers:
        return "done"

    pending = [w for w in workers if w not in node_outputs]
    if not pending:
        return "done"

    lower = (user_input or "").lower()
    # Keyword bias: prefer write/research workers when mentioned
    scored: list[tuple[int, str]] = []
    for w in pending:
        score = 0
        wl = w.lower()
        if "write" in wl and any(k in lower for k in ("write", "draft", "summary", "answer")):
            score += 2
        if "research" in wl and any(k in lower for k in ("research", "find", "search", "look")):
            score += 2
        scored.append((score, w))
    scored.sort(key=lambda t: (-t[0], workers.index(t[1]) if t[1] in workers else 0))
    return scored[0][1]

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
