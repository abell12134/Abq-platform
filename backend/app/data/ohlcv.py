from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

from app.config import settings
from app.data.baostock_daily import fetch_baostock_bars
from app.data.bar_merge import merge_klines
from app.data.market_quotes import fetch_remote_bars, to_instrument
from app.data.qlib_store import fetch_ohlcv_local, get_calendar_last_date, normalize_symbol

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _today_sh() -> str:
    return dt.datetime.now(_SHANGHAI).date().isoformat()


def _needs_backfill(local_last: str | None) -> bool:
    if not local_last:
        return True
    return local_last < _today_sh()


def _next_day(date_str: str) -> str:
    d = dt.date.fromisoformat(date_str) + dt.timedelta(days=1)
    return d.isoformat()


async def _backfill_bars(
    qlib_sym: str,
    *,
    after: str,
    limit: int,
) -> tuple[list[dict[str, Any]], str]:
    instrument = to_instrument(qlib_sym)
    end = _today_sh()

    try:
        remote = await asyncio.to_thread(fetch_remote_bars, instrument, limit=limit + 30)
    except Exception:
        remote = None
    if remote:
        bars, source = remote
        gap = [b for b in bars if b["date"] > after]
        if gap:
            return gap, source

    if settings.ohlcv_backfill_baostock:
        try:
            start = _next_day(after)
            bs_bars = await fetch_baostock_bars(qlib_sym, start, end)
            if bs_bars:
                return bs_bars, "baostock"
        except Exception:
            pass

    return [], "none"


async def fetch_ohlcv(symbol: str, *, limit: int = 30) -> dict[str, Any]:
    """统一 OHLCV：本地 qlib + 远程补全缺口（移植 abq quotes 合并策略）。"""
    qlib_sym = normalize_symbol(symbol)
    local_last_cal = await get_calendar_last_date()
    local = await fetch_ohlcv_local(symbol, limit=max(limit, 60))
    bars = local["bars"]
    local_last = local["summary"]["last_date"]

    backfill_meta: dict[str, Any] = {
        "local_last_date": local_last,
        "calendar_last_date": local_last_cal,
        "backfilled": False,
        "backfill_source": None,
        "backfill_bars": 0,
    }

    if settings.ohlcv_backfill_enabled and _needs_backfill(local_last):
        gap_bars, source = await _backfill_bars(qlib_sym, after=local_last, limit=limit)
        if gap_bars:
            bars = merge_klines(bars, gap_bars)
            backfill_meta.update(
                {
                    "backfilled": True,
                    "backfill_source": source,
                    "backfill_bars": len(gap_bars),
                }
            )

    bars = bars[-limit:]
    last = bars[-1]
    source = local["source"]
    if backfill_meta["backfilled"]:
        source = f"{source}+{backfill_meta['backfill_source']}"

    return {
        "source": source,
        "symbol": qlib_sym,
        "price_unit": "yuan",
        "bars": bars,
        "summary": {
            "last_date": last["date"],
            "close": last.get("close"),
            "volume": last.get("volume"),
            "bars_returned": len(bars),
            **backfill_meta,
        },
    }
