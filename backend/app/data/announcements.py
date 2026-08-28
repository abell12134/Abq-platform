from __future__ import annotations

from datetime import datetime, timedelta
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


async def fetch_announcements(
    symbol: str,
    *,
    limit: int = 10,
    days: int = 90,
) -> dict[str, Any]:
    """个股公告（巨潮/东财），默认近 90 日、最多 limit 条。"""
    qlib_sym = normalize_symbol(symbol)
    digits = to_digits(symbol)
    try:
        import akshare as ak
    except ImportError:
        return _unavailable(qlib_sym, "akshare 未安装", limit)

    end = datetime.now().date()
    begin = end - timedelta(days=max(7, days))
    begin_s = begin.strftime("%Y-%m-%d")
    end_s = end.strftime("%Y-%m-%d")

    try:
        df = await run_sync(
            ak.stock_individual_notice_report,
            security=digits,
            symbol="全部",
            begin_date=begin_s,
            end_date=end_s,
            timeout_s=25,
        )
        rows = _df_records(df, limit=limit)
        return {
            "source": "akshare",
            "symbol": qlib_sym,
            "status": "ok" if rows else "empty",
            "announcements": rows,
            "summary": {
                "count": len(rows),
                "latest_title": rows[0].get("公告标题") if rows else None,
                "latest_date": str(rows[0].get("公告日期")) if rows else None,
                "window": f"{begin_s} ~ {end_s}",
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
        "announcements": [],
        "limit": limit,
    }
