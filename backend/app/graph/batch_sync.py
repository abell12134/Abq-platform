from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.config import settings
from app.factors.universe import fetch_universe_symbols
from app.graph.builder import bootstrap_csi300_skeleton
from app.graph.store import graph_store
from app.graph.summarizer import rollup_period
from app.graph.sync import sync_market_layer, sync_one_stock

log = logging.getLogger(__name__)


async def sync_csi300_month(
    *,
    period: str | None = None,
    max_symbols: int = 300,
    force: bool = False,
    symbol_rollup_llm: bool = False,
) -> dict[str, Any]:
    """
    CSI300 全成分股同步 + 各板块/大盘本月 Rollup。
    symbol_rollup_llm=False 时对 300 股用规则摘要，避免数百次 LLM 调用。
    """
    if not settings.graph_enabled:
        return {"status": "disabled"}

    period = period or datetime.now(UTC).strftime("%Y-%m")
    graph_store.ensure()
    await bootstrap_csi300_skeleton(max_symbols=max_symbols)

    # 300 股批量同步时关闭 LLM 三元组抽取，否则耗时数小时
    prev_extract = settings.graph_extract_triples_enabled
    settings.graph_extract_triples_enabled = False

    symbols, uni_meta = await fetch_universe_symbols("csi300", max_symbols=max_symbols)
    if not symbols:
        settings.graph_extract_triples_enabled = prev_extract
        return {"status": "error", "message": "无法获取 CSI300 成分股列表"}

    sync_stats = {"ok": 0, "skipped": 0, "errors": 0}
    try:
        for i, sym in enumerate(symbols, 1):
            row = await sync_one_stock(sym, force=force)
            if row.skipped:
                sync_stats["skipped"] += 1
            elif row.status == "ok":
                sync_stats["ok"] += 1
            else:
                sync_stats["errors"] += 1
            if i % 20 == 0 or i == len(symbols):
                log.info(
                    "CSI300 sync %s/%s ok=%s skip=%s err=%s",
                    i,
                    len(symbols),
                    sync_stats["ok"],
                    sync_stats["skipped"],
                    sync_stats["errors"],
                )
    finally:
        settings.graph_extract_triples_enabled = prev_extract

    market = await sync_market_layer(force=force)

    sectors = graph_store.list_sector_names(limit=500)
    sector_rollups: list[dict[str, Any]] = []
    for name in sectors:
        rr = await rollup_period(period, scope="sector", key=name, force=force, use_llm=True)
        sector_rollups.append(
            {
                "sector": name,
                "status": rr.status,
                "skipped": rr.skipped,
                "event_count": rr.event_count,
            }
        )

    market_rollup = await rollup_period(
        period, scope="market", key="market", force=force, use_llm=not force
    )

    symbol_rollups = {"ok": 0, "skipped": 0, "empty": 0}
    for sym in symbols:
        rr = await rollup_period(
            period,
            scope="symbol",
            key=sym.lower(),
            force=force,
            use_llm=symbol_rollup_llm,
        )
        if rr.skipped:
            symbol_rollups["skipped"] += 1
        elif rr.status == "empty":
            symbol_rollups["empty"] += 1
        else:
            symbol_rollups["ok"] += 1

    summary: dict[str, Any] = {
        "status": "ok",
        "period": period,
        "universe": uni_meta,
        "symbols_total": len(symbols),
        "sync": sync_stats,
        "market": market,
        "sectors_total": len(sectors),
        "sector_rollups": sector_rollups,
        "market_rollup": market_rollup.model_dump(),
        "symbol_rollups": symbol_rollups,
        "graph_stats": graph_store.stats().model_dump(),
    }

    out = settings.data_dir / "graph" / "csi300_batch_last.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
