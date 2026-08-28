from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.knowledge.archiver import archive_breadth, archive_sentiment
from app.llm.embedding_client import embedding_client
from app.memory.episodic import extract_and_store_episode
from app.memory.extractors import extract_path_memory_meta
from app.memory.search import _parse_tool_payload
from app.memory.store import memory_store
from app.models.pipeline import PipelineReports
from app.persistence.paths import path_store

log = logging.getLogger(__name__)


async def index_path_memory(
    path_id: str,
    *,
    meta: dict[str, Any],
    entry_kind: str,
) -> None:
    one_liner = meta.get("judge_one_liner")
    if not one_liner or not settings.embedding_enabled:
        return
    symbols: list[str] = meta.get("symbols") or []
    symbol = symbols[0] if symbols else "all"
    namespace = ("paths", entry_kind, symbol.lower())
    text = one_liner
    if meta.get("judge_stance"):
        text = f"[{meta['judge_stance']}] {text}"
    try:
        emb = await embedding_client.embed_query(text)
        memory_store.put(
            namespace,
            path_id,
            text=text,
            metadata={
                "path_id": path_id,
                "kind": entry_kind,
                "symbols": symbols,
                "judge_stance": meta.get("judge_stance"),
                "updated": meta.get("updated"),
            },
            embedding=emb,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("index_path_memory %s failed: %s", path_id, exc)


async def index_knowledge_event(
    *,
    event_type: str,
    text: str,
    symbol: str | None,
    event_id: str,
    path_id: str | None,
    ts: str,
    source: str,
) -> None:
    if not text or not settings.embedding_enabled:
        return
    if event_type == "breadth":
        namespace = ("knowledge", "breadth", "market")
    else:
        namespace = ("knowledge", event_type, (symbol or "unknown").lower())
    try:
        emb = await embedding_client.embed_query(text)
        memory_store.put(
            namespace,
            event_id,
            text=text,
            metadata={
                "event_id": event_id,
                "path_id": path_id,
                "ts": ts,
                "symbol": symbol,
                "source": source,
                "type": event_type,
            },
            embedding=emb,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("index_knowledge_event %s failed: %s", event_id, exc)


async def archive_steps_knowledge(path_id: str, steps: list[dict[str, Any]]) -> None:
    for step in steps:
        agent = step.get("agent") or ""
        if agent == "fetch_sentiment":
            payload = _parse_tool_payload(step)
            if not payload:
                continue
            sym = str(payload.get("symbol") or "")
            event = await archive_sentiment(payload, symbol=sym, path_id=path_id)
            if event:
                await index_knowledge_event(
                    event_type="sentiment",
                    text=event.summary,
                    symbol=event.symbol,
                    event_id=event.id,
                    path_id=path_id,
                    ts=event.ts,
                    source=event.source,
                )
        elif agent == "fetch_market_breadth":
            payload = _parse_tool_payload(step)
            if not payload:
                continue
            event = await archive_breadth(payload, path_id=path_id)
            if event:
                await index_knowledge_event(
                    event_type="breadth",
                    text=event.summary,
                    symbol=None,
                    event_id=event.id,
                    path_id=path_id,
                    ts=event.ts,
                    source=event.source,
                )


async def post_analyze_archive(path_id: str) -> None:
    """Run after analysis completes: meta extraction, jsonl archive, vector index."""
    entry = await path_store.get_entry_raw(path_id)
    if entry is None:
        return

    reports_data = await path_store.load_reports(path_id)
    meta_patch = extract_path_memory_meta(entry, reports_data)
    updated = await path_store.update_memory_meta(path_id, **meta_patch)
    if updated is None:
        return

    steps = await path_store.load_steps(path_id)
    await archive_steps_knowledge(path_id, steps)

    meta_patch["updated"] = updated.updated
    await index_path_memory(path_id, meta=meta_patch, entry_kind=updated.kind)

    if reports_data and settings.embedding_enabled:
        reports = PipelineReports.model_validate(reports_data)
        if reports.sentiment and reports.sentiment.content:
            sym = (updated.symbols or [updated.target or ""])[0]
            if sym:
                await index_knowledge_event(
                    event_type="sentiment",
                    text=reports.sentiment.content[:500],
                    symbol=sym,
                    event_id=f"{path_id}_sentiment",
                    path_id=path_id,
                    ts=updated.updated,
                    source="agent_report",
                )

    user_message = ""
    for step in reversed(steps):
        if step.get("agent") == "user" and step.get("role") == "user":
            user_message = str(step.get("result") or "")
            break
    await extract_and_store_episode(updated, reports_data, user_message)


async def reindex_all(*, scope: str = "all") -> dict[str, Any]:
    memory_store.ensure()
    count = 0
    if scope in ("all", "paths"):
        entries = await path_store.list_entries()
        for entry in entries:
            if entry.status != "done" or not entry.judge_one_liner:
                continue
            await index_path_memory(
                entry.id,
                meta={
                    "judge_one_liner": entry.judge_one_liner,
                    "judge_stance": entry.judge_stance,
                    "symbols": entry.symbols,
                    "updated": entry.updated,
                },
                entry_kind=entry.kind,
            )
            count += 1
    return {"status": "ok", "indexed": count, "total_items": memory_store.count()}
