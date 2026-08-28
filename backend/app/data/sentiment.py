from __future__ import annotations

from typing import Any

import pandas as pd

from app.data.akshare_client import run_sync, to_digits
from app.data.qlib_store import normalize_symbol


def _df_records(df: pd.DataFrame, *, limit: int = 10) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    trimmed = df.head(limit)
    rows = trimmed.where(pd.notna(trimmed), None).to_dict(orient="records")

    def _json_safe(value: Any) -> Any:
        if hasattr(value, "isoformat") and not isinstance(value, str):
            try:
                return value.isoformat()
            except Exception:  # noqa: BLE001
                return str(value)
        return value

    return [{k: _json_safe(v) for k, v in row.items()} for row in rows]


async def fetch_sentiment(symbol: str, *, limit: int = 10) -> dict:
    qlib_sym = normalize_symbol(symbol)
    digits = to_digits(symbol)
    try:
        import akshare as ak
    except ImportError:
        return _unavailable(qlib_sym, "akshare 未安装", limit)

    try:
        news_df = await run_sync(ak.stock_news_em, symbol=digits, timeout_s=20)
        headlines = _df_records(news_df, limit=limit)
        return {
            "source": "akshare",
            "symbol": qlib_sym,
            "status": "ok" if headlines else "empty",
            "headlines": headlines,
            "summary": {
                "count": len(headlines),
                "latest_title": headlines[0].get("新闻标题") if headlines else None,
                "latest_time": headlines[0].get("发布时间") if headlines else None,
            },
        }
    except Exception as exc:  # noqa: BLE001
        return _unavailable(qlib_sym, str(exc), limit)


def _unavailable(symbol: str, reason: str, limit: int) -> dict:
    return {
        "source": "akshare",
        "symbol": symbol,
        "status": "unavailable",
        "message": reason,
        "headlines": [],
        "limit": limit,
    }
