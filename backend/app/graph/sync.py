from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import settings
from app.data.announcements import fetch_announcements
from app.data.market_flow import (
    fetch_macro_snapshot,
    fetch_margin_summary,
    fetch_northbound_flow,
)
from app.data.fundamentals import fetch_fundamentals
from app.data.qlib_store import normalize_symbol
from app.data.sector_pulse import fetch_market_breadth
from app.data.sentiment import fetch_sentiment
from app.graph.extractor import extract_supply_chain_triples
from app.graph.builder import (
    apply_announcements_to_graph,
    apply_fundamentals_to_graph,
    apply_sentiment_to_graph,
    bootstrap_csi300_skeleton,
    default_sample_symbols,
)
from app.graph.market_builder import (
    apply_macro_indicators_to_graph,
    apply_margin_to_graph,
    apply_market_snapshot_to_graph,
    apply_northbound_to_graph,
)
from app.graph.models import SyncBatchResult, SyncStockResult
from app.graph.rate_limit import FetchThrottle
from app.graph.store import graph_store
from app.knowledge.archiver import (
    archive_announcements,
    archive_breadth,
    archive_macro,
    archive_margin,
    archive_market_snapshot,
    archive_northbound,
    archive_sentiment,
    payload_fingerprint,
)

log = logging.getLogger(__name__)

_throttle: FetchThrottle | None = None


def _get_throttle() -> FetchThrottle:
    global _throttle
    if _throttle is None or _throttle.min_interval_s != settings.graph_fetch_min_interval_s:
        _throttle = FetchThrottle(settings.graph_fetch_min_interval_s)
    return _throttle


def _within_cooldown(symbol: str) -> tuple[bool, str]:
    row = graph_store.get_sync_log(symbol)
    if not row:
        return False, ""
    try:
        last = datetime.fromisoformat(str(row["last_sync_at"]).replace("Z", "+00:00"))
    except ValueError:
        return False, ""
    cooldown = timedelta(hours=settings.graph_sync_cooldown_hours)
    if datetime.now(UTC) - last < cooldown:
        remaining = cooldown - (datetime.now(UTC) - last)
        hours = max(0.1, remaining.total_seconds() / 3600)
        return True, f"冷却中（约 {hours:.1f}h 后可再同步）"
    return False, ""


def _market_within_cooldown() -> tuple[bool, str]:
    last = graph_store.get_meta("last_market_sync_at")
    if not last:
        return False, ""
    try:
        prev = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except ValueError:
        return False, ""
    cooldown = timedelta(hours=settings.graph_sync_cooldown_hours)
    if datetime.now(UTC) - prev < cooldown:
        remaining = cooldown - (datetime.now(UTC) - prev)
        hours = max(0.1, remaining.total_seconds() / 3600)
        return True, f"市场层冷却中（约 {hours:.1f}h 后可再同步）"
    return False, ""


def _evidence_hash(titles: list[str]) -> str:
    raw = "\n".join(sorted(t.strip() for t in titles if t.strip()))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


async def _maybe_archive_sentiment(payload: dict, *, symbol: str, force: bool) -> bool:
    headlines = payload.get("headlines") or []
    fp = payload_fingerprint({"headlines": headlines, "symbol": symbol})
    meta_key = f"archive_sentiment_fp:{symbol.lower()}"
    if not force and graph_store.get_meta(meta_key) == fp:
        return False
    archived = await archive_sentiment(payload, symbol=symbol, path_id=None)
    if archived is not None or payload.get("status") == "empty":
        graph_store.set_meta(meta_key, fp)
    return archived is not None


async def _maybe_archive_announcements(payload: dict, *, symbol: str, force: bool) -> bool:
    items = payload.get("announcements") or []
    fp = payload_fingerprint({"announcements": items, "symbol": symbol})
    meta_key = f"archive_announcement_fp:{symbol.lower()}"
    if not force and graph_store.get_meta(meta_key) == fp:
        return False
    archived = await archive_announcements(payload, symbol=symbol, path_id=None)
    if archived is not None or payload.get("status") == "empty":
        graph_store.set_meta(meta_key, fp)
    return archived is not None


async def sync_one_stock(symbol: str, *, force: bool = False) -> SyncStockResult:
    sym = normalize_symbol(symbol)
    if not force:
        cooling, reason = _within_cooldown(sym)
        if cooling:
            graph_store.set_sync_log(sym, status="skipped", message=reason)
            return SyncStockResult(
                symbol=sym,
                status="skipped",
                skipped=True,
                reason=reason,
            )

    throttle = _get_throttle()
    company_name: str | None = None
    sector: str | None = None
    sentiment_count = 0
    announcement_count = 0
    news_linked = 0
    events_linked = 0

    try:
        await throttle.wait()
        fundamentals = await fetch_fundamentals(sym)
        if fundamentals.get("status") == "ok":
            meta = apply_fundamentals_to_graph(sym, fundamentals)
            company_name = meta.get("name")
            sector = meta.get("sector")
        else:
            log.info("fundamentals unavailable for %s: %s", sym, fundamentals.get("message"))

        await throttle.wait()
        sentiment = await fetch_sentiment(sym, limit=settings.graph_sentiment_limit)
        sentiment_count = len(sentiment.get("headlines") or [])
        if sentiment.get("status") in ("ok", "empty"):
            await _maybe_archive_sentiment(sentiment, symbol=sym, force=force)
            news_linked = apply_sentiment_to_graph(
                sym, sentiment, limit=settings.graph_sentiment_limit
            )

        await throttle.wait()
        announcements = await fetch_announcements(
            sym,
            limit=settings.graph_announcement_limit,
            days=settings.graph_announcement_days,
        )
        announcement_count = len(announcements.get("announcements") or [])
        if announcements.get("status") in ("ok", "empty"):
            await _maybe_archive_announcements(announcements, symbol=sym, force=force)
            events_linked = apply_announcements_to_graph(
                sym,
                announcements,
                limit=settings.graph_announcement_limit,
            )

        evidence: list[str] = []
        for row in sentiment.get("headlines") or []:
            t = row.get("新闻标题") or row.get("title")
            if t:
                evidence.append(str(t))
        for row in announcements.get("announcements") or []:
            t = row.get("公告标题") or row.get("title")
            if t:
                evidence.append(str(t))
        if evidence and settings.graph_extract_triples_enabled:
            ev_hash = _evidence_hash(evidence)
            meta_key = f"extract_fp:{sym}"
            if force or graph_store.get_meta(meta_key) != ev_hash:
                await extract_supply_chain_triples(
                    sym,
                    company_name=company_name or sym,
                    sector=sector or "",
                    evidence_titles=evidence,
                )
                graph_store.set_meta(meta_key, ev_hash)

        graph_store.set_sync_log(
            sym,
            status="ok",
            message=f"news={news_linked},events={events_linked}",
        )
        return SyncStockResult(
            symbol=sym,
            status="ok",
            sentiment_count=sentiment_count,
            announcement_count=announcement_count,
            news_linked=news_linked,
            events_linked=events_linked,
            company_name=company_name,
            sector=sector,
        )
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)[:200]
        log.warning("graph sync failed %s: %s", sym, msg)
        graph_store.set_sync_log(sym, status="error", message=msg)
        return SyncStockResult(symbol=sym, status="error", reason=msg)


async def sync_sample_stocks(
    symbols: list[str] | None = None,
    *,
    force: bool = False,
    bootstrap: bool = True,
) -> SyncBatchResult:
    if not settings.graph_enabled:
        return SyncBatchResult(
            status="disabled",
            requested=0,
            synced=0,
            skipped=0,
            errors=0,
            min_interval_s=settings.graph_fetch_min_interval_s,
            cooldown_hours=settings.graph_sync_cooldown_hours,
            summary="GRAPH_ENABLED=false",
        )

    graph_store.ensure()
    if bootstrap:
        await bootstrap_csi300_skeleton(max_symbols=300)

    targets = symbols or default_sample_symbols()
    if not targets:
        return SyncBatchResult(
            status="error",
            requested=0,
            synced=0,
            skipped=0,
            errors=1,
            min_interval_s=settings.graph_fetch_min_interval_s,
            cooldown_hours=settings.graph_sync_cooldown_hours,
            summary="未配置样本股票 GRAPH_SYNC_SAMPLE_SYMBOLS",
        )

    graph_store.set_meta("sample_symbols", json.dumps(targets, ensure_ascii=False))

    results: list[SyncStockResult] = []
    synced = skipped = errors = 0
    for sym in targets:
        try:
            sym = normalize_symbol(sym)
        except ValueError as exc:
            results.append(SyncStockResult(symbol=sym, status="error", reason=str(exc)))
            errors += 1
            continue
        row = await sync_one_stock(sym, force=force)
        results.append(row)
        if row.skipped:
            skipped += 1
        elif row.status == "ok":
            synced += 1
        else:
            errors += 1

    summary = (
        f"样本同步完成：请求 {len(targets)}，成功 {synced}，跳过 {skipped}，失败 {errors}；"
        f"请求间隔 ≥{settings.graph_fetch_min_interval_s}s，"
        f"冷却 {settings.graph_sync_cooldown_hours}h"
    )
    return SyncBatchResult(
        status="ok" if errors == 0 else "partial",
        requested=len(targets),
        synced=synced,
        skipped=skipped,
        errors=errors,
        min_interval_s=settings.graph_fetch_min_interval_s,
        cooldown_hours=settings.graph_sync_cooldown_hours,
        results=results,
        summary=summary,
    )


async def sync_market_layer(*, force: bool = False) -> dict[str, Any]:
    """同步宏观/市场层：宽度、北向、两融、宏观指标 → 归档 + 图谱。"""
    if not settings.graph_enabled:
        return {"status": "disabled"}

    if not force:
        cooling, reason = _market_within_cooldown()
        if cooling:
            return {"status": "skipped", "reason": reason}

    throttle = _get_throttle()
    graph_store.ensure()

    await throttle.wait()
    breadth = await fetch_market_breadth()
    if breadth.get("status") == "ok":
        await archive_breadth(breadth)

    await throttle.wait()
    north = await fetch_northbound_flow()
    if north.get("status") == "ok":
        await archive_northbound(north)
        apply_northbound_to_graph(north)

    await throttle.wait()
    margin = await fetch_margin_summary()
    if margin.get("status") == "ok":
        await archive_margin(margin)
        apply_margin_to_graph(margin)

    await throttle.wait()
    macro = await fetch_macro_snapshot()
    macro_count = 0
    if macro.get("status") == "ok":
        await archive_macro(macro)
        macro_count = apply_macro_indicators_to_graph(macro)

    snap_id = apply_market_snapshot_to_graph(
        breadth=breadth if breadth.get("status") == "ok" else None,
        northbound=north if north.get("status") == "ok" else None,
        margin=margin if margin.get("status") == "ok" else None,
    )
    await archive_market_snapshot(
        {
            "status": "ok",
            "source": "composite",
            "summary": f"市场快照 {snap_id}",
            "metrics": {
                "snapshot_id": snap_id,
                "breadth_ok": breadth.get("status") == "ok",
                "northbound_ok": north.get("status") == "ok",
                "margin_ok": margin.get("status") == "ok",
                "macro_count": macro_count,
            },
        }
    )

    graph_store.set_meta("last_market_sync_at", datetime.now(UTC).isoformat())

    return {
        "status": "ok",
        "snapshot_id": snap_id,
        "breadth": breadth.get("status"),
        "northbound": north.get("status"),
        "margin": margin.get("status"),
        "macro": macro.get("status"),
        "macro_nodes": macro_count,
    }


async def sync_incremental(
    symbol: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """
    单股增量更新：尊重冷却期，归档/摘要/三元组在无新变化时跳过。
  适合页面「增量更新」一键操作。
    """
    from app.graph.summarizer import rollup_period
    from app.knowledge.policy_sync import sync_policy_sources

    if not settings.graph_enabled:
        return {"status": "disabled"}

    graph_store.ensure()
    sym = normalize_symbol(symbol)
    period = datetime.now(UTC).strftime("%Y-%m")

    stock = await sync_one_stock(sym, force=force)
    market = await sync_market_layer(force=force)
    policy = await sync_policy_sources(max_total=2)
    rollup = await rollup_period(period, scope="symbol", key=sym, force=force)

    parts: list[str] = []
    if stock.skipped:
        parts.append(f"{sym} {stock.reason or '已跳过'}")
    elif stock.status == "ok":
        parts.append(f"{sym} 已同步")
    rollup_note = "月摘要已跳过" if rollup.skipped else "月摘要已更新"
    if market.get("status") == "skipped":
        parts.append(str(market.get("reason") or "市场层已跳过"))
    parts.append(rollup_note)
    if int(policy.get("ingested") or 0) > 0:
        parts.append(f"政策 +{policy['ingested']}")

    return {
        "status": "ok",
        "symbol": sym,
        "summary": "；".join(parts),
        "stock": stock.model_dump(),
        "market": market,
        "policy": policy,
        "rollup": rollup.model_dump(),
    }
