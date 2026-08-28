from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any, Literal

from app.config import settings
from app.graph.models import GraphNode, RollupResult
from app.graph.store import graph_store, index_node_id, sector_node_id, stock_node_id
from app.knowledge.archiver import list_events
from app.knowledge.models import KnowledgeEvent

log = logging.getLogger(__name__)

RollupScope = Literal["symbol", "sector", "market"]


def _parse_period(period: str) -> tuple[int, int]:
    m = re.match(r"^(\d{4})-(\d{2})$", period.strip())
    if not m:
        raise ValueError("period 格式应为 YYYY-MM")
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        raise ValueError("月份无效")
    return year, month


def _in_period(ts: str, year: int, month: int) -> bool:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return False
    return dt.year == year and dt.month == month


def _titles_from_events(events: list[KnowledgeEvent]) -> list[str]:
    titles: list[str] = []
    for ev in events:
        for row in ev.headlines:
            t = (
                row.get("新闻标题")
                or row.get("公告标题")
                or row.get("title")
            )
            if t:
                titles.append(str(t).strip())
    return titles


def _rule_summary(titles: list[str], *, period: str, scope: str, key: str) -> str:
    if not titles:
        return f"{period} {scope}:{key} 无归档事件。"
    uniq = list(dict.fromkeys(titles))
    sample = "；".join(uniq[:8])
    extra = f"等共 {len(uniq)} 条" if len(uniq) > 8 else f"共 {len(uniq)} 条"
    return f"{period} {scope}:{key} 主题摘要（规则）：{sample}（{extra}）"


async def _llm_summary(
    titles: list[str],
    *,
    period: str,
    scope: str,
    key: str,
) -> str | None:
    if not settings.graph_rollup_llm_enabled or not titles:
        return None
    try:
        from app.llm.chat import LlmChat
        from app.llm.router import LlmRouter

        router = LlmRouter()
        resolved = router.resolve(tier="local")
        chat = LlmChat(resolved.provider, model=resolved.model)
        bullet = "\n".join(f"- {t}" for t in titles[:40])
        prompt = (
            f"你是金融研究助手。请用 3-5 句话总结以下 {period} 期间"
            f"（scope={scope}, key={key}）的舆情/公告主题变化，"
            "不要编造未出现的事实，不要投资建议。\n\n"
            f"{bullet}"
        )
        result = await chat.complete(
            [{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=600,
        )
        text = (result.content or "").strip()
        return text or None
    except Exception as exc:  # noqa: BLE001
        log.warning("rollup llm failed: %s", exc)
        return None


def digest_node_id(period: str, scope: str, key: str) -> str:
    safe = re.sub(r"[^\w.\-]+", "_", key)[:40]
    return f"digest:{period}:{scope}:{safe}"


def _events_fingerprint(events: list[KnowledgeEvent]) -> str:
    parts = sorted(f"{e.id}:{e.payload_hash or ''}" for e in events)
    raw = "\n".join(parts) if parts else "empty"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


async def collect_symbol_events(symbol: str, year: int, month: int) -> list[KnowledgeEvent]:
    sym = symbol.lower()
    out: list[KnowledgeEvent] = []
    for etype in ("sentiment", "announcement"):
        events = await list_events(etype, symbol=sym, limit=500)
        out.extend(e for e in events if _in_period(e.ts, year, month))
    return out


async def collect_sector_events(sector: str, year: int, month: int) -> list[KnowledgeEvent]:
    symbols = graph_store.stocks_in_sector(sector)
    out: list[KnowledgeEvent] = []
    for sym in symbols:
        out.extend(await collect_symbol_events(sym, year, month))
    return out


async def collect_market_events(year: int, month: int) -> list[KnowledgeEvent]:
    out: list[KnowledgeEvent] = []
    for etype in ("breadth", "northbound", "margin", "macro", "market_snapshot"):
        events = await list_events(etype, limit=500)
        out.extend(e for e in events if _in_period(e.ts, year, month))
    return out


async def rollup_period(
    period: str,
    *,
    scope: RollupScope = "symbol",
    key: str,
    use_llm: bool | None = None,
    force: bool = False,
) -> RollupResult:
    if not settings.graph_enabled:
        return RollupResult(
            status="disabled",
            period=period,
            scope=scope,
            key=key,
            summary="GRAPH_ENABLED=false",
        )

    year, month = _parse_period(period)
    graph_store.ensure()

    events: list[KnowledgeEvent] = []
    if scope == "symbol":
        events = await collect_symbol_events(key, year, month)
    elif scope == "market":
        events = await collect_market_events(year, month)
    elif scope == "sector":
        events = await collect_sector_events(key, year, month)
    else:
        return RollupResult(
            status="error",
            period=period,
            scope=scope,
            key=key,
            summary=f"未知 scope: {scope}",
        )

    titles = _titles_from_events(events)
    did = digest_node_id(period, scope, key)
    fingerprint = _events_fingerprint(events)

    if not force:
        existing = graph_store.get_node(did)
        if existing and str(existing.props.get("source_fingerprint") or "") == fingerprint:
            return RollupResult(
                status="skipped",
                period=period,
                scope=scope,
                key=key,
                digest_id=did,
                event_count=len(events),
                summary=str(existing.props.get("summary") or "摘要已是最新，未重复生成"),
                used_llm=bool(existing.props.get("used_llm")),
                skipped=True,
            )

    llm_on = settings.graph_rollup_llm_enabled if use_llm is None else use_llm
    summary = None
    used_llm = False
    if llm_on:
        summary = await _llm_summary(titles, period=period, scope=scope, key=key)
        used_llm = bool(summary)
    if not summary:
        summary = _rule_summary(titles, period=period, scope=scope, key=key)

    graph_store.upsert_node(
        GraphNode(
            id=did,
            type="Digest",
            label=f"{period} {key}",
            props={
                "period": period,
                "scope": scope,
                "key": key,
                "granularity": "monthly",
                "event_count": len(events),
                "title_count": len(titles),
                "source_fingerprint": fingerprint,
                "summary": summary,
                "used_llm": used_llm,
                "generated_at": datetime.now(UTC).isoformat(),
            },
        )
    )

    if scope == "symbol":
        sid = stock_node_id(key.lower())
        if graph_store.get_node(sid):
            graph_store.link_edge(did, sid, "SUMMARIZES", props={"period": period})
    elif scope == "sector":
        sec_id = sector_node_id(key)
        if graph_store.get_node(sec_id):
            graph_store.link_edge(did, sec_id, "SUMMARIZES", props={"period": period})
    elif scope == "market":
        idx = index_node_id("csi300")
        if graph_store.get_node(idx):
            graph_store.link_edge(did, idx, "SUMMARIZES", props={"period": period})

    if settings.embedding_enabled and summary:
        try:
            from app.llm.embedding_client import embedding_client
            from app.memory.store import memory_store

            emb = await embedding_client.embed_query(summary)
            memory_store.put(
                ("knowledge", "digest", scope, key),
                did,
                text=summary,
                metadata={
                    "period": period,
                    "scope": scope,
                    "key": key,
                    "type": "digest",
                },
                embedding=emb,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("digest embed failed %s: %s", did, exc)

    graph_store.set_meta(f"last_rollup_{scope}_{key}", datetime.now(UTC).isoformat())

    return RollupResult(
        status="ok" if events else "empty",
        period=period,
        scope=scope,
        key=key,
        digest_id=did,
        event_count=len(events),
        summary=summary,
        used_llm=used_llm,
    )


async def rollup_current_month_for_symbols(
    symbols: list[str],
    *,
    force: bool = False,
) -> list[RollupResult]:
    period = datetime.now(UTC).strftime("%Y-%m")
    results: list[RollupResult] = []
    for sym in symbols:
        results.append(
            await rollup_period(period, scope="symbol", key=sym.lower(), force=force)
        )
    return results
