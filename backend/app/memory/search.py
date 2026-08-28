from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import settings
from app.llm.embedding_client import embedding_client
from app.llm.reranker_client import reranker_client
from app.memory.store import memory_store
from app.models.analysis import AnalysisPathIndexEntry
from app.persistence.paths import path_store

log = logging.getLogger(__name__)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def search_prior_analysis(
    *,
    symbol: str | None = None,
    kind: str | None = None,
    query: str | None = None,
    since_days: int | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    entries = await path_store.list_entries()
    cutoff = None
    if since_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=since_days)

    candidates: list[AnalysisPathIndexEntry] = []
    for entry in entries:
        if entry.status != "done":
            continue
        if kind and entry.kind != kind:
            continue
        if symbol:
            sym = symbol.lower()
            entry_syms = [s.lower() for s in (entry.symbols or [])]
            if entry.target and entry.target.lower() == sym:
                pass
            elif sym not in entry_syms:
                continue
        if cutoff:
            updated = _parse_dt(entry.updated)
            if updated and updated < cutoff:
                continue
        if not entry.judge_one_liner and not entry.judge_stance:
            continue
        candidates.append(entry)

    hits: list[dict[str, Any]] = []
    if query and settings.embedding_enabled:
        ns_symbol = (symbol or "all").lower()
        ns_kind = kind or "all"
        namespace = ("paths", ns_kind, ns_symbol)
        try:
            q_emb = await embedding_client.embed_query(query)
            vec_hits = memory_store.search(namespace, q_emb, limit=limit * 4)
            if vec_hits:
                docs = [h["text"] for h in vec_hits]
                ranked = await reranker_client.rerank(query, docs, top_n=limit)
                for idx, score in ranked:
                    if idx >= len(vec_hits):
                        continue
                    h = vec_hits[idx]
                    meta = h.get("metadata") or {}
                    hits.append(
                        {
                            "path_id": meta.get("path_id") or h.get("key"),
                            "judge_one_liner": h.get("text"),
                            "judge_stance": meta.get("judge_stance"),
                            "kind": meta.get("kind"),
                            "symbols": meta.get("symbols") or [],
                            "updated": meta.get("updated"),
                            "score": score,
                            "source": "vector",
                        }
                    )
        except Exception as exc:  # noqa: BLE001
            log.warning("vector path search failed: %s", exc)

    if not hits:
        candidates.sort(key=lambda e: e.updated, reverse=True)
        for entry in candidates[:limit]:
            hits.append(
                {
                    "path_id": entry.id,
                    "judge_one_liner": entry.judge_one_liner,
                    "judge_stance": entry.judge_stance,
                    "kind": entry.kind,
                    "symbols": entry.symbols,
                    "updated": entry.updated,
                    "score": 1.0,
                    "source": "metadata",
                }
            )

    return {
        "status": "ok" if hits else "empty",
        "hits": hits[:limit],
        "summary": f"检索到 {min(len(hits), limit)} 条历史研判",
    }


async def search_knowledge(
    query: str,
    *,
    symbol: str | None = None,
    knowledge_type: str = "sentiment",
    limit: int = 5,
) -> dict[str, Any]:
    if not query.strip():
        return {"status": "error", "message": "query 不能为空", "hits": []}

    if knowledge_type == "breadth":
        namespace = ("knowledge", "breadth", "market")
    elif knowledge_type == "policy":
        namespace = ("knowledge", "policy")
    elif symbol:
        namespace = ("knowledge", knowledge_type, symbol.lower())
    else:
        namespace = ("knowledge", knowledge_type)

    hits: list[dict[str, Any]] = []
    if settings.embedding_enabled:
        try:
            q_emb = await embedding_client.embed_query(query)
            filt = {"symbol": symbol.lower()} if symbol else None
            vec_hits = memory_store.search(
                namespace,
                q_emb,
                limit=limit * 4,
                metadata_filter=filt,
            )
            if vec_hits:
                docs = [h["text"] for h in vec_hits]
                ranked = await reranker_client.rerank(query, docs, top_n=limit)
                for idx, score in ranked:
                    if idx >= len(vec_hits):
                        continue
                    h = vec_hits[idx]
                    meta = h.get("metadata") or {}
                    hits.append(
                        {
                            "text": h.get("text"),
                            "score": score,
                            "source": meta.get("source", "knowledge"),
                            "event_id": meta.get("event_id"),
                            "path_id": meta.get("path_id"),
                            "ts": meta.get("ts"),
                            "symbol": meta.get("symbol"),
                        }
                    )
        except Exception as exc:  # noqa: BLE001
            log.warning("search_knowledge failed: %s", exc)

    return {
        "status": "ok" if hits else "empty",
        "hits": hits[:limit],
        "summary": f"检索到 {len(hits)} 条知识记录",
    }


def _parse_tool_payload(step: dict[str, Any]) -> dict[str, Any] | None:
    raw = step.get("result") or ""
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None
