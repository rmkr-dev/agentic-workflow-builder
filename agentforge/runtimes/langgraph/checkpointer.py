"""Durable LangGraph checkpointer so HITL resume works across CLI processes."""

from __future__ import annotations

import os
import pickle
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver


def default_checkpoint_path() -> Path:
    root = Path(os.environ.get("AGENTFORGE_DATA_DIR", ".agentforge"))
    return root / "checkpoints.pkl"


class DurableMemorySaver(MemorySaver):
    """MemorySaver that flushes storage/writes/blobs to a pickle file.

    LangGraph's default ``MemorySaver`` is process-local, so ``agentforge run``
    followed by ``agentforge resume`` in a new process could never continue a
    HITL interrupt. This wrapper persists checkpoints under ``.agentforge/``.
    """

    def __init__(self, path: str | Path | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.path = Path(path) if path is not None else default_checkpoint_path()
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = pickle.loads(self.path.read_bytes())
        except Exception:
            return
        if not isinstance(data, dict):
            return
        storage = data.get("storage") or {}
        for thread_id, nsmap in storage.items():
            if not isinstance(nsmap, dict):
                continue
            for ns, ckpts in nsmap.items():
                if isinstance(ckpts, dict):
                    self.storage[thread_id][ns].update(ckpts)
        writes = data.get("writes") or {}
        if isinstance(writes, dict):
            self.writes.update(writes)
        blobs = data.get("blobs") or {}
        if isinstance(blobs, dict):
            self.blobs.update(blobs)

    def _flush_unlocked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        storage_dump: dict[str, dict[str, dict[str, Any]]] = {}
        for thread_id, nsmap in self.storage.items():
            storage_dump[thread_id] = {ns: dict(ckpts) for ns, ckpts in nsmap.items()}
        payload = {
            "storage": storage_dump,
            "writes": dict(self.writes),
            "blobs": dict(self.blobs),
        }
        tmp = self.path.with_name(self.path.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_bytes(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))
        last_exc: OSError | None = None
        for attempt in range(12):
            try:
                os.replace(str(tmp), str(self.path))
                return
            except OSError as exc:
                last_exc = exc
                time.sleep(0.01 * (attempt + 1))
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        if last_exc is not None:
            raise last_exc

    def put(self, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            result = super().put(*args, **kwargs)
            self._flush_unlocked()
            return result

    def put_writes(self, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            result = super().put_writes(*args, **kwargs)
            self._flush_unlocked()
            return result

    def delete_thread(self, thread_id: str) -> None:
        with self._lock:
            super().delete_thread(thread_id)
            self._flush_unlocked()


def empty_nested_dict() -> defaultdict[Any, Any]:
    return defaultdict(dict)
