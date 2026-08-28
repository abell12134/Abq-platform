from __future__ import annotations

import json
import logging
import sqlite3
import struct
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np

from app.config import settings

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_items (
    id TEXT PRIMARY KEY,
    namespace TEXT NOT NULL,
    item_key TEXT NOT NULL,
    text TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    embedding BLOB,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_namespace ON memory_items(namespace);
CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_ns_key ON memory_items(namespace, item_key);
"""


def _pack_vector(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack_vector(blob: bytes) -> np.ndarray:
    n = len(blob) // 4
    return np.array(struct.unpack(f"{n}f", blob), dtype=np.float32)


def namespace_str(parts: tuple[str, ...]) -> str:
    return "/".join(parts)


class MemoryStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or settings.memory_db_path
        self._lock = threading.Lock()

    def ensure(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def put(
        self,
        namespace: tuple[str, ...],
        key: str,
        *,
        text: str,
        metadata: dict[str, Any] | None = None,
        embedding: list[float] | None = None,
    ) -> str:
        self.ensure()
        item_id = f"mem_{uuid4().hex[:12]}"
        ns = namespace_str(namespace)
        now = datetime.now(UTC).isoformat()
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        emb_blob = _pack_vector(embedding) if embedding else None
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO memory_items (id, namespace, item_key, text, metadata, embedding, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(namespace, item_key) DO UPDATE SET
                        text=excluded.text,
                        metadata=excluded.metadata,
                        embedding=excluded.embedding,
                        updated_at=excluded.updated_at
                    """,
                    (item_id, ns, key, text, meta_json, emb_blob, now, now),
                )
                conn.commit()
        return item_id

    def search(
        self,
        namespace: tuple[str, ...],
        query_embedding: list[float],
        *,
        limit: int = 20,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.ensure()
        ns = namespace_str(namespace)
        q = np.array(query_embedding, dtype=np.float32)
        q_norm = np.linalg.norm(q)
        if q_norm == 0:
            return []

        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM memory_items WHERE namespace = ? AND embedding IS NOT NULL",
                    (ns,),
                ).fetchall()

        hits: list[dict[str, Any]] = []
        for row in rows:
            meta = json.loads(row["metadata"] or "{}")
            if metadata_filter and not _match_filter(meta, metadata_filter):
                continue
            vec = _unpack_vector(row["embedding"])
            denom = np.linalg.norm(vec) * q_norm
            score = float(np.dot(q, vec) / denom) if denom > 0 else 0.0
            hits.append(
                {
                    "id": row["id"],
                    "key": row["item_key"],
                    "text": row["text"],
                    "metadata": meta,
                    "score": score,
                    "created_at": row["created_at"],
                }
            )
        hits.sort(key=lambda h: h["score"], reverse=True)
        return hits[:limit]

    def list_namespace(
        self,
        namespace: tuple[str, ...],
        *,
        limit: int = 50,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.ensure()
        ns = namespace_str(namespace)
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM memory_items WHERE namespace = ? ORDER BY updated_at DESC LIMIT ?",
                    (ns, limit * 3),
                ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            meta = json.loads(row["metadata"] or "{}")
            if metadata_filter and not _match_filter(meta, metadata_filter):
                continue
            out.append(
                {
                    "id": row["id"],
                    "key": row["item_key"],
                    "text": row["text"],
                    "metadata": meta,
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
            if len(out) >= limit:
                break
        return out

    def delete_namespace(self, namespace: tuple[str, ...]) -> int:
        self.ensure()
        ns = namespace_str(namespace)
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute("DELETE FROM memory_items WHERE namespace = ?", (ns,))
                conn.commit()
                return cur.rowcount

    def count(self) -> int:
        self.ensure()
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM memory_items").fetchone()
            return int(row["c"]) if row else 0


def _match_filter(meta: dict[str, Any], filt: dict[str, Any]) -> bool:
    for key, expected in filt.items():
        if meta.get(key) != expected:
            return False
    return True


memory_store = MemoryStore()
