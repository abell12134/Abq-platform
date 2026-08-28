from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from app.data.akshare_client import run_sync, to_digits
from app.data.qlib_store import normalize_symbol


def _profile_info(df: pd.DataFrame) -> dict[str, Any]:
    if df is None or df.empty:
        return {}
    row = df.iloc[0]
    return {str(k): _json_safe(row[k]) for k in df.columns if pd.notna(row[k])}


def _json_safe(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _indicator_rows(df: pd.DataFrame, *, limit: int = 6) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    trimmed = df.head(limit)
    rows = trimmed.where(pd.notna(trimmed), None).to_dict(orient="records")
    return [{k: _json_safe(v) for k, v in row.items()} for row in rows]


async def fetch_fundamentals(symbol: str) -> dict:
    qlib_sym = normalize_symbol(symbol)
    digits = to_digits(symbol)
    try:
        import akshare as ak
    except ImportError:
        return _unavailable(qlib_sym, "akshare 未安装")

    company_info: dict[str, Any] = {}
    financial_rows: list[dict[str, Any]] = []
    errors: list[str] = []

    try:
        profile_df = await run_sync(ak.stock_profile_cninfo, symbol=digits, timeout_s=20)
        company_info = _profile_info(profile_df)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"profile: {exc}")

    start_year = str(datetime.now().year - 2)
    try:
        indicator_df = await run_sync(
            ak.stock_financial_analysis_indicator,
            symbol=digits,
            start_year=start_year,
            timeout_s=25,
        )
        financial_rows = _indicator_rows(indicator_df, limit=6)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"indicator: {exc}")

    if not company_info and not financial_rows:
        return _unavailable(qlib_sym, "; ".join(errors) or "无数据")

    latest = financial_rows[0] if financial_rows else {}
    return {
        "source": "akshare",
        "symbol": qlib_sym,
        "status": "ok",
        "company_info": company_info,
        "financial_indicators": financial_rows,
        "summary": {
            "name": company_info.get("A股简称") or company_info.get("公司名称"),
            "latest_period": _json_safe(latest.get("日期")),
            "eps": latest.get("摊薄每股收益(元)") or latest.get("加权每股收益(元)"),
            "roe": latest.get("净资产收益率(%)"),
            "metrics_returned": len(financial_rows),
            "warnings": errors,
        },
    }


def _unavailable(symbol: str, reason: str) -> dict:
    return {
        "source": "akshare",
        "symbol": symbol,
        "status": "unavailable",
        "message": reason,
        "company_info": {},
        "financial_indicators": [],
    }
