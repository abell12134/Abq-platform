from __future__ import annotations

import gzip
import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

from app.config import settings
from app.graph.builder import default_sample_symbols
from app.graph.summarizer import rollup_current_month_for_symbols, rollup_period
from app.knowledge.policy_sync import sync_policy_sources

log = logging.getLogger(__name__)


def _knowledge_root() -> Path:
    return settings.data_dir / "knowledge"


def _archive_dir() -> Path:
    return _knowledge_root() / "archive"


def rotate_jsonl_archives(*, before_period: str | None = None) -> dict:
    """
    将早于指定月份（默认上月）的 jsonl 归档为 gzip。
    before_period: YYYY-MM，该月之前的文件会被归档。
    """
    if not settings.graph_jsonl_rotate_enabled:
        return {"status": "disabled", "archived": 0}

    if before_period:
        year, month = map(int, before_period.split("-"))
    else:
        now = datetime.now(UTC)
        if now.month == 1:
            year, month = now.year - 1, 12
        else:
            year, month = now.year, now.month - 1
    cutoff = datetime(year, month, 1, tzinfo=UTC)

    archived = 0
    root = _knowledge_root()
    if not root.exists():
        return {"status": "ok", "archived": 0}

    for path in root.rglob("*.jsonl"):
        if "archive" in path.parts:
            continue
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        except OSError:
            continue
        if mtime >= cutoff:
            continue
        rel = path.relative_to(root)
        dest = _archive_dir() / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        period_tag = mtime.strftime("%Y-%m")
        gz_path = dest.with_name(f"{path.stem}.{period_tag}.jsonl.gz")
        with path.open("rb") as src, gzip.open(gz_path, "wb") as out:
            shutil.copyfileobj(src, out)
        path.unlink()
        archived += 1

    return {"status": "ok", "archived": archived, "cutoff": cutoff.isoformat()}


async def run_monthly_rollup(
    *,
    period: str | None = None,
    symbols: list[str] | None = None,
) -> dict:
    period = period or datetime.now(UTC).strftime("%Y-%m")
    syms = symbols or default_sample_symbols()
    symbol_results = await rollup_current_month_for_symbols(syms)
    market = await rollup_period(period, scope="market", key="market")

    from app.graph.store import graph_store

    graph_store.ensure()
    sector_results = []
    for name in graph_store.list_sector_names(limit=20):
        sector_results.append(await rollup_period(period, scope="sector", key=name))

    return {
        "status": "ok",
        "period": period,
        "symbols": [r.model_dump() for r in symbol_results],
        "market": market.model_dump(),
        "sectors": [r.model_dump() for r in sector_results],
    }


async def run_scheduled_maintenance() -> dict:
    """每月维护：jsonl 归档 + Rollup + 政策增量同步。"""
    rotate = rotate_jsonl_archives()
    rollup = await run_monthly_rollup()
    policy = await sync_policy_sources()

    from app.graph.store import graph_store

    graph_store.set_meta("last_maintenance_at", datetime.now(UTC).isoformat())
    graph_store.set_meta(
        "last_maintenance_summary",
        json.dumps(
            {
                "rotate": rotate,
                "rollup_period": rollup.get("period"),
                "policy_ingested": policy.get("ingested"),
            },
            ensure_ascii=False,
        ),
    )
    return {"rotate": rotate, "rollup": rollup, "policy": policy}


async def maybe_run_startup_maintenance() -> None:
    if not settings.graph_scheduler_enabled or not settings.graph_scheduler_on_startup:
        return
    from app.graph.store import graph_store

    graph_store.ensure()
    last = graph_store.get_meta("last_maintenance_at")
    now = datetime.now(UTC)
    if last:
        try:
            prev = datetime.fromisoformat(last.replace("Z", "+00:00"))
            if prev.year == now.year and prev.month == now.month:
                return
        except ValueError:
            pass
    log.info("running scheduled graph maintenance")
    await run_scheduled_maintenance()
