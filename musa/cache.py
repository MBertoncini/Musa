"""Cache locale su SQLite.

Due scopi:
1. Essere gentili con OpenAlex (non rinterrogare gli stessi URL).
2. Rendere i re-run veloci e riproducibili.

La cache è un semplice key->value con timestamp. La chiave è l'URL completo della
richiesta (o un hash), il valore è il JSON di risposta.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any, Optional


class Cache:
    def __init__(self, directory: str, ttl_days: int = 30):
        os.makedirs(directory, exist_ok=True)
        self.dir = directory
        self.ttl = ttl_days * 86400
        self.path = os.path.join(directory, "cache.sqlite")
        self._conn = sqlite3.connect(self.path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS http_cache (
                key      TEXT PRIMARY KEY,
                value    TEXT NOT NULL,
                ts       REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                topic      TEXT,
                ts         REAL,
                payload    TEXT
            )
            """
        )
        self._conn.commit()

    # --- HTTP cache -------------------------------------------------------
    def get(self, key: str) -> Optional[Any]:
        cur = self._conn.execute(
            "SELECT value, ts FROM http_cache WHERE key = ?", (key,)
        )
        row = cur.fetchone()
        if not row:
            return None
        value, ts = row
        if self.ttl and (time.time() - ts) > self.ttl:
            return None  # scaduto: si comporta come miss
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None

    def set(self, key: str, value: Any) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO http_cache (key, value, ts) VALUES (?, ?, ?)",
            (key, json.dumps(value, ensure_ascii=False), time.time()),
        )
        self._conn.commit()

    def clear_http(self) -> None:
        self._conn.execute("DELETE FROM http_cache")
        self._conn.commit()

    # --- Sessioni (log del dossier per debug/riuso) -----------------------
    def save_session(self, session_id: str, topic: str, payload: Any) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO sessions (session_id, topic, ts, payload) "
            "VALUES (?, ?, ?, ?)",
            (session_id, topic, time.time(), json.dumps(payload, ensure_ascii=False)),
        )
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
