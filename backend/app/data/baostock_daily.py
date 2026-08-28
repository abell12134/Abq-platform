"""baostock 日线补洞（移植自 abq quant/data_pipeline/fetch_baostock.py / update_incremental.py）。"""

from __future__ import annotations

import asyncio
from typing import Any

from app.data.qlib_store import normalize_symbol, to_baostock_code


def _fetch_raw_sync(symbol: str, start: str, end: str) -> list[dict[str, Any]]:
    import baostock as bs

    code = to_baostock_code(symbol)
    fields = "date,open,high,low,close,volume,amount,tradestatus"
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock login failed: {lg.error_msg}")
    try:
        rs = bs.query_history_k_data_plus(
            code,
            fields,
            start_date=start,
            end_date=end,
            frequency="d",
            adjustflag="3",
        )
        if rs.error_code != "0":
            raise RuntimeError(rs.error_msg)
        rows: list[dict[str, Any]] = []
        while rs.next():
            row = rs.get_row_data()
            if len(row) < 8 or row[7] != "1":
                continue
            o, h, low_p, c, v = float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])
            if c <= 0 or v <= 0:
                continue
            rows.append(
                {
                    "date": row[0],
                    "open": o,
                    "high": h,
                    "low": low_p,
                    "close": c,
                    "volume": v,
                    "amount": float(row[6]) if row[6] else 0.0,
                }
            )
        return rows
    finally:
        bs.logout()


async def fetch_baostock_bars(symbol: str, start: str, end: str) -> list[dict[str, Any]]:
    qlib_sym = normalize_symbol(symbol)
    if start > end:
        return []
    return await asyncio.to_thread(_fetch_raw_sync, qlib_sym, start, end)
