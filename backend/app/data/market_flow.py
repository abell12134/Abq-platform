from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from app.data.akshare_client import run_sync


def _safe_float(v: Any) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


async def fetch_northbound_flow() -> dict[str, Any]:
    """沪深港通北向资金最新快照（东财）。"""
    try:
        import akshare as ak
    except ImportError:
        return {"status": "unavailable", "message": "akshare 未安装"}

    try:
        df = await run_sync(ak.stock_hsgt_hist_em, symbol="北向资金", timeout_s=25)
        if df is None or df.empty:
            return {"status": "empty", "source": "akshare", "metrics": {}}
        row = df.iloc[-1]
        metrics = {
            "trade_date": str(row.get("日期") or row.get("交易日") or ""),
            "net_buy": _safe_float(row.get("当日成交净买额") or row.get("成交净买额")),
            "net_inflow": _safe_float(row.get("当日资金流入") or row.get("资金净流入")),
            "index_pct": _safe_float(row.get("上证指数") or row.get("指数涨跌幅")),
        }
        return {
            "status": "ok",
            "source": "akshare",
            "kind": "northbound",
            "metrics": metrics,
            "summary": _northbound_summary(metrics),
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "unavailable", "source": "akshare", "message": str(exc), "metrics": {}}


def _northbound_summary(metrics: dict[str, Any]) -> str:
    net = metrics.get("net_buy") or metrics.get("net_inflow")
    date = metrics.get("trade_date") or ""
    if net is None:
        return f"北向资金 {date} 数据缺失"
    return f"北向资金 {date} 净买额 {net:.2f} 亿"


async def fetch_margin_summary() -> dict[str, Any]:
    """沪深两市融资融券最新汇总。"""
    try:
        import akshare as ak
    except ImportError:
        return {"status": "unavailable", "message": "akshare 未安装"}

    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=14)).strftime("%Y%m%d")
    try:
        sse_df = await run_sync(ak.stock_margin_sse, start_date=start, end_date=end, timeout_s=25)
        metrics: dict[str, Any] = {"trade_date": "", "sse_financing_balance": None, "sse_margin_balance": None}
        if sse_df is not None and not sse_df.empty:
            row = sse_df.iloc[-1]
            metrics["trade_date"] = str(row.get("信用交易日期") or row.get("日期") or "")
            metrics["sse_financing_balance"] = _safe_float(
                row.get("融资余额") or row.get("融资余额(元)")
            )
            metrics["sse_margin_balance"] = _safe_float(
                row.get("融券余额") or row.get("融券余额(元)")
            )
        try:
            sz_df = await run_sync(
                ak.stock_margin_szse,
                date=end,
                timeout_s=20,
            )
            if sz_df is not None and not sz_df.empty:
                row = sz_df.iloc[-1]
                metrics["sz_financing_balance"] = _safe_float(row.get("融资余额"))
                metrics["sz_margin_balance"] = _safe_float(row.get("融券余额"))
                if not metrics["trade_date"]:
                    metrics["trade_date"] = str(row.get("日期") or end)
        except Exception:  # noqa: BLE001
            pass

        if not metrics.get("trade_date"):
            return {"status": "empty", "source": "akshare", "kind": "margin", "metrics": metrics}

        return {
            "status": "ok",
            "source": "akshare",
            "kind": "margin",
            "metrics": metrics,
            "summary": _margin_summary(metrics),
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "unavailable", "source": "akshare", "message": str(exc), "metrics": {}}


def _margin_summary(metrics: dict[str, Any]) -> str:
    date = metrics.get("trade_date") or ""
    fin = metrics.get("sse_financing_balance")
    if fin is None:
        return f"两融 {date} 数据缺失"
    return f"两融 {date} 沪市融资余额 {fin:.0f}"


async def fetch_macro_snapshot() -> dict[str, Any]:
    """宏观指标快照：LPR + M2 同比（最新一期）。"""
    try:
        import akshare as ak
    except ImportError:
        return {"status": "unavailable", "message": "akshare 未安装"}

    indicators: list[dict[str, Any]] = []
    try:
        lpr_df = await run_sync(ak.macro_china_lpr, timeout_s=20)
        if lpr_df is not None and not lpr_df.empty:
            row = lpr_df.iloc[-1]
            indicators.append(
                {
                    "name": "LPR",
                    "period": str(row.get("TRADE_DATE") or row.iloc[0]),
                    "value_1y": _safe_float(row.get("LPR1Y") if "LPR1Y" in row else row.iloc[1]),
                    "value_5y": _safe_float(row.get("LPR5Y") if "LPR5Y" in row else None),
                }
            )
    except Exception:  # noqa: BLE001
        pass

    try:
        m2_df = await run_sync(ak.macro_china_m2_yearly, timeout_s=20)
        if m2_df is not None and not m2_df.empty:
            row = m2_df.iloc[-1]
            indicators.append(
                {
                    "name": "M2同比",
                    "period": str(row.get("月份") or row.iloc[0]),
                    "value": _safe_float(row.get("同比增长") if "同比增长" in row else row.iloc[-1]),
                }
            )
    except Exception:  # noqa: BLE001
        pass

    if not indicators:
        return {"status": "empty", "source": "akshare", "kind": "macro", "indicators": []}

    parts = [f"{i['name']} {i.get('period')}" for i in indicators[:3]]
    return {
        "status": "ok",
        "source": "akshare",
        "kind": "macro",
        "indicators": indicators,
        "summary": "宏观：" + "；".join(parts),
    }
