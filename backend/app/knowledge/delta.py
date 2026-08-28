from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.knowledge.archiver import list_events
from app.knowledge.models import KnowledgeDeltaResult, KnowledgeType

_THEME_WORDS = ("业绩", "监管", "回购", "减持", "涨价", "降价", "政策", "立案", "处罚", "并购")


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _headline_titles(event) -> list[str]:
    titles: list[str] = []
    for row in event.headlines:
        title = row.get("新闻标题") or row.get("title")
        if title:
            titles.append(str(title).strip())
    return titles


def _keyword_delta(old_text: str, new_text: str) -> dict[str, int]:
    changes: dict[str, int] = {}
    for word in _THEME_WORDS:
        old_n = old_text.count(word)
        new_n = new_text.count(word)
        if new_n != old_n:
            changes[word] = new_n - old_n
    return changes


async def compute_knowledge_delta(
    event_type: KnowledgeType,
    *,
    symbol: str | None = None,
    theme: str | None = None,
    since_days: int = 7,
) -> KnowledgeDeltaResult:
    events = await list_events(event_type, symbol=symbol, theme=theme, limit=200)
    cutoff = datetime.now(UTC) - timedelta(days=since_days)
    filtered = [e for e in events if (_parse_ts(e.ts) or cutoff) >= cutoff]

    if len(filtered) < 1:
        return KnowledgeDeltaResult(
            status="empty",
            type=event_type,
            symbol=symbol,
            since_days=since_days,
            summary="该时间窗口内无归档记录",
            event_count=0,
        )

    if event_type == "breadth":
        return _delta_breadth(filtered, symbol=symbol, since_days=since_days)

    return _delta_sentiment(filtered, symbol=symbol, since_days=since_days)


def _delta_breadth(events, *, symbol: str | None, since_days: int) -> KnowledgeDeltaResult:
    latest = events[-1]
    earliest = events[0]
    metric_changes: dict[str, object] = {}
    for key in ("advance", "advance_ratio", "limit_up_count"):
        old_v = earliest.metrics.get(key)
        new_v = latest.metrics.get(key)
        if old_v is not None and new_v is not None and old_v != new_v:
            metric_changes[key] = {"from": old_v, "to": new_v, "delta": new_v - old_v if isinstance(new_v, (int, float)) else None}

    summary_parts = [latest.summary]
    if metric_changes:
        summary_parts.append(
            "较窗口初："
            + "；".join(
                f"{k} {v['from']}→{v['to']}" for k, v in metric_changes.items() if isinstance(v, dict)
            )
        )

    return KnowledgeDeltaResult(
        status="ok",
        type="breadth",
        symbol=symbol,
        since_days=since_days,
        metric_changes=metric_changes,
        summary="。".join(summary_parts),
        event_count=len(events),
    )


def _delta_sentiment(events, *, symbol: str | None, since_days: int) -> KnowledgeDeltaResult:
    latest = events[-1]
    earliest = events[0]
    old_titles = set(_headline_titles(earliest))
    new_titles = set(_headline_titles(latest))
    added = sorted(new_titles - old_titles)
    removed = sorted(old_titles - new_titles)

    old_blob = " ".join(_headline_titles(earliest))
    new_blob = " ".join(_headline_titles(latest))
    kw = _keyword_delta(old_blob, new_blob)

    parts = [f"窗口内 {len(events)} 次抓取"]
    if added:
        parts.append(f"新增标题 {len(added)} 条")
    if removed:
        parts.append(f"消失标题 {len(removed)} 条")
    if kw:
        parts.append("主题词变化 " + ", ".join(f"{k}{v:+d}" for k, v in kw.items()))

    return KnowledgeDeltaResult(
        status="ok",
        type="sentiment",
        symbol=symbol,
        since_days=since_days,
        new_items=added[:20],
        removed_items=removed[:20],
        metric_changes=kw,
        summary="；".join(parts),
        event_count=len(events),
    )
