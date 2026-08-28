from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiofiles

from app.config import settings
from app.knowledge.models import KnowledgeEvent, KnowledgeType

log = logging.getLogger(__name__)


def _knowledge_root() -> Path:
    return settings.data_dir / "knowledge"


def _event_path(event_type: KnowledgeType, *, symbol: str | None = None, theme: str | None = None) -> Path:
    root = _knowledge_root()
    if event_type in ("breadth", "northbound", "margin", "macro", "market_snapshot"):
        return root / "market" / f"{event_type}.jsonl"
    if event_type == "sector_pulse" and theme:
        safe = theme.replace("/", "_")[:40]
        return root / "by_theme" / safe / "sector_pulse.jsonl"
    sym = (symbol or "unknown").lower()
    return root / "by_symbol" / sym / f"{event_type}.jsonl"


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "isoformat") and not isinstance(value, str):
        try:
            return value.isoformat()
        except Exception:  # noqa: BLE001
            return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def _payload_hash(payload: dict) -> str:
    raw = json.dumps(_json_safe(payload), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def payload_fingerprint(payload: dict) -> str:
    """Stable hash for incremental archive / skip checks."""
    return _payload_hash(payload)


async def _read_hashes(path: Path) -> set[str]:
    if not path.exists():
        return set()
    hashes: set[str] = set()
    async with aiofiles.open(path, encoding="utf-8") as f:
        async for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            h = row.get("payload_hash")
            if h:
                hashes.add(str(h))
    return hashes


async def append_event(event: KnowledgeEvent) -> bool:
    """Append knowledge event to jsonl. Returns False if dedup skipped."""
    if not settings.knowledge_archive_enabled:
        return False

    path = _event_path(
        event.type,
        symbol=event.symbol,
        theme=event.theme,
    )
    path.parent.mkdir(parents=True, exist_ok=True)

    if settings.knowledge_dedup_by_hash and event.payload_hash:
        existing = await _read_hashes(path)
        if event.payload_hash in existing:
            return False

    async with aiofiles.open(path, "a", encoding="utf-8") as f:
        await f.write(event.model_dump_json(ensure_ascii=False) + "\n")
    return True


def _headline_titles(headlines: list[dict]) -> list[str]:
    titles: list[str] = []
    for row in headlines:
        title = row.get("新闻标题") or row.get("title") or row.get("headline")
        if title:
            titles.append(str(title).strip())
    return titles


def sentiment_summary(payload: dict) -> str:
    headlines = payload.get("headlines") or []
    titles = _headline_titles(headlines)
    count = len(headlines)
    latest = titles[0] if titles else None
    if latest:
        return f"共 {count} 条，最新：{latest[:80]}"
    return f"共 {count} 条舆情"


def _announcement_titles(items: list[dict]) -> list[str]:
    titles: list[str] = []
    for row in items:
        title = row.get("公告标题") or row.get("title")
        if title:
            titles.append(str(title).strip())
    return titles


def announcement_summary(payload: dict) -> str:
    items = payload.get("announcements") or []
    titles = _announcement_titles(items)
    count = len(items)
    latest = titles[0] if titles else None
    if latest:
        return f"公告 {count} 条，最新：{latest[:80]}"
    return f"公告 {count} 条"


def breadth_summary(payload: dict) -> str:
    metrics = payload.get("metrics") or payload
    advance = metrics.get("advance")
    ratio = metrics.get("advance_ratio")
    limit_up = metrics.get("limit_up_count")
    parts: list[str] = []
    if advance is not None:
        parts.append(f"上涨家数 {advance}")
    if ratio is not None:
        parts.append(f"宽度比 {float(ratio):.2f}")
    if limit_up is not None:
        parts.append(f"涨停 {limit_up} 家")
    return "，".join(parts) if parts else "大盘宽度快照"


async def archive_sentiment(
    payload: dict,
    *,
    symbol: str,
    path_id: str | None = None,
) -> KnowledgeEvent | None:
    if payload.get("status") not in ("ok", "empty"):
        return None
    headlines = _json_safe(payload.get("headlines") or [])
    event = KnowledgeEvent(
        id=f"evt_{uuid4().hex[:10]}",
        ts=datetime.now(UTC).isoformat(),
        type="sentiment",
        source=str(payload.get("source") or "akshare"),
        symbol=(payload.get("symbol") or symbol).lower(),
        path_id=path_id,
        payload_hash=_payload_hash({"headlines": headlines, "symbol": symbol}),
        headlines=headlines,
        summary=sentiment_summary(payload),
    )
    if await append_event(event):
        return event
    return None


async def archive_announcements(
    payload: dict,
    *,
    symbol: str,
    path_id: str | None = None,
) -> KnowledgeEvent | None:
    if payload.get("status") not in ("ok", "empty"):
        return None
    items = _json_safe(payload.get("announcements") or [])
    event = KnowledgeEvent(
        id=f"evt_{uuid4().hex[:10]}",
        ts=datetime.now(UTC).isoformat(),
        type="announcement",
        source=str(payload.get("source") or "akshare"),
        symbol=(payload.get("symbol") or symbol).lower(),
        path_id=path_id,
        payload_hash=_payload_hash({"announcements": items, "symbol": symbol}),
        headlines=items,
        summary=announcement_summary(payload),
    )
    if await append_event(event):
        return event
    return None


async def _archive_market_metric(
    payload: dict,
    *,
    event_type: KnowledgeType,
    path_id: str | None = None,
) -> KnowledgeEvent | None:
    if payload.get("status") not in ("ok",):
        return None
    metrics = _json_safe(dict(payload.get("metrics") or {}))
    if payload.get("indicators"):
        metrics["indicators"] = _json_safe(payload.get("indicators"))
    event = KnowledgeEvent(
        id=f"evt_{uuid4().hex[:10]}",
        ts=datetime.now(UTC).isoformat(),
        type=event_type,
        source=str(payload.get("source") or "akshare"),
        path_id=path_id,
        payload_hash=_payload_hash(metrics),
        metrics=metrics,
        summary=str(payload.get("summary") or event_type),
    )
    if await append_event(event):
        return event
    return None


async def archive_northbound(payload: dict, *, path_id: str | None = None) -> KnowledgeEvent | None:
    return await _archive_market_metric(payload, event_type="northbound", path_id=path_id)


async def archive_margin(payload: dict, *, path_id: str | None = None) -> KnowledgeEvent | None:
    return await _archive_market_metric(payload, event_type="margin", path_id=path_id)


async def archive_macro(payload: dict, *, path_id: str | None = None) -> KnowledgeEvent | None:
    return await _archive_market_metric(payload, event_type="macro", path_id=path_id)


async def archive_market_snapshot(
    payload: dict,
    *,
    path_id: str | None = None,
) -> KnowledgeEvent | None:
    return await _archive_market_metric(payload, event_type="market_snapshot", path_id=path_id)


async def archive_breadth(payload: dict, *, path_id: str | None = None) -> KnowledgeEvent | None:
    if payload.get("status") not in ("ok",):
        return None
    metrics = _json_safe(
        {
            k: payload.get(k)
            for k in (
                "advance",
                "decline",
                "unchanged",
                "advance_ratio",
                "limit_up_count",
                "status",
            )
            if payload.get(k) is not None
        }
    )
    event = KnowledgeEvent(
        id=f"evt_{uuid4().hex[:10]}",
        ts=datetime.now(UTC).isoformat(),
        type="breadth",
        source=str(payload.get("source") or "akshare"),
        path_id=path_id,
        payload_hash=_payload_hash(metrics),
        metrics=metrics,
        summary=breadth_summary(payload),
    )
    if await append_event(event):
        return event
    return None


async def list_events(
    event_type: KnowledgeType,
    *,
    symbol: str | None = None,
    theme: str | None = None,
    limit: int = 50,
) -> list[KnowledgeEvent]:
    path = _event_path(event_type, symbol=symbol, theme=theme)
    if not path.exists():
        return []
    rows: list[KnowledgeEvent] = []
    async with aiofiles.open(path, encoding="utf-8") as f:
        async for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(KnowledgeEvent.model_validate(json.loads(line)))
            except Exception:  # noqa: BLE001
                continue
    return rows[-limit:]
