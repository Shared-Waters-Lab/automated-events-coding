"""A small SQLite-backed JSON cache for API responses.

River and dam names recur constantly across events, so after a warm-up most
lookups never leave the machine. Misses are cached too (as empty results).
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

MISSING = object()


class JsonCache:
    def __init__(self, path: str | Path | None = None, *, ttl_seconds: float | None = None):
        """path=None keeps the cache in memory. ttl_seconds=None never expires."""
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path) if path is not None else ":memory:")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS kv ("
            " ns TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, fetched_at REAL NOT NULL,"
            " PRIMARY KEY (ns, key))"
        )
        self._conn.commit()
        self._ttl = ttl_seconds

    def get(self, ns: str, key: str) -> Any:
        row = self._conn.execute(
            "SELECT value, fetched_at FROM kv WHERE ns = ? AND key = ?", (ns, key)
        ).fetchone()
        if row is None:
            return MISSING
        value, fetched_at = row
        if self._ttl is not None and time.time() - fetched_at > self._ttl:
            return MISSING
        return json.loads(value)

    def set(self, ns: str, key: str, value: Any) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO kv (ns, key, value, fetched_at) VALUES (?, ?, ?, ?)",
            (ns, key, json.dumps(value, ensure_ascii=False), time.time()),
        )
        self._conn.commit()