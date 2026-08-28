from fastapi import APIRouter, Query

from app.data.bar_processing import clean_bars
from app.data.ohlcv import fetch_ohlcv
from app.orchestration.time_window import (
    DEFAULT_OHLCV_LIMIT,
    ohlcv_window_label,
    parse_ohlcv_limit,
)

router = APIRouter(prefix="/quotes", tags=["quotes"])


@router.get("/{symbol}/ohlcv")
async def quote_ohlcv(
    symbol: str,
    limit: int | None = Query(None, ge=5, le=400),
    message: str | None = None,
    focus: str | None = None,
) -> dict:
    bar_limit = limit if limit is not None else parse_ohlcv_limit(message or "", focus=focus)
    ohlcv = await fetch_ohlcv(symbol, limit=bar_limit)
    cleaned = clean_bars(ohlcv["bars"])
    bars = cleaned["bars"]
    return {
        "symbol": ohlcv.get("symbol") or symbol,
        "limit": bar_limit,
        "window_label": ohlcv_window_label(bar_limit),
        "bars": bars,
        "summary": {
            **(ohlcv.get("summary") or {}),
            **(cleaned.get("summary") or {}),
        },
    }


@router.get("/ohlcv/default-limit")
async def default_ohlcv_limit() -> dict:
    return {"limit": DEFAULT_OHLCV_LIMIT, "window_label": ohlcv_window_label(DEFAULT_OHLCV_LIMIT)}
