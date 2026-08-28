"""Read-only factor tools for ReAct agents (compact summaries, no full panels)."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from app.data.qlib_store import normalize_symbol
from app.factors.compute import compute_expr
from app.factors.evaluate import load_qlib_eval_panel
from app.factors.ir import expr_from_dict, uses_cross_section
from app.factors.panel import DEFAULT_EVAL_SYMBOLS, Panel, collapse_to_series, synthetic_panel
from app.factors.runtime import compute_factor_panel
from app.factors.store import factor_store

log = logging.getLogger(__name__)

DEFAULT_LIST_STATUSES = frozenset({"live", "paper_tracking", "passed_auto"})
LOOKBACK = 120


def _latest_cs_snapshot(values: pd.DataFrame, symbol: str) -> tuple[float | None, float | None, str | None]:
    if values.empty or symbol not in values.columns:
        return None, None, None
    valid = values.dropna(how="all")
    if valid.empty:
        return None, None, None
    row = valid.iloc[-1]
    as_of = str(valid.index[-1].date()) if hasattr(valid.index[-1], "date") else str(valid.index[-1])
    raw = row.get(symbol)
    if raw is None or raw != raw:
        return None, None, as_of
    peers = row.dropna()
    if peers.empty:
        return float(raw), None, as_of
    rank = peers.rank(pct=True, method="average").get(symbol)
    pct = float(rank * 100.0) if rank == rank else None
    return float(raw), pct, as_of


async def _load_panel_for_symbol(symbol: str, *, lookback: int, use_synthetic: bool) -> tuple[Panel, str]:
    sym = normalize_symbol(symbol)
    symbols = list(dict.fromkeys([sym, symbol, *DEFAULT_EVAL_SYMBOLS]))
    if use_synthetic:
        panel = synthetic_panel(n_stocks=max(8, len(symbols)), n_days=lookback, seed=9)
    else:
        panel, _meta = await load_qlib_eval_panel(symbols, lookback)
    close = panel.get("close", pd.DataFrame())
    if sym not in close.columns and symbol in close.columns:
        sym = symbol
    if sym not in close.columns:
        raise ValueError(f"标的 {sym} 不在评测面板")
    return panel, sym


async def list_factors_for_agent(
    *,
    status: str | None = None,
    theme: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    factor_store.ensure()
    items = factor_store.list_factors(status=status or None, theme=theme or None)
    if not status:
        items = [f for f in items if f.status in DEFAULT_LIST_STATUSES]
    rows: list[dict[str, Any]] = []
    for rec in items[: max(1, min(limit, 40))]:
        ic_stats = (rec.metrics or {}).get("ic_stats") or {}
        rows.append(
            {
                "id": rec.id,
                "name": rec.name,
                "status": rec.status,
                "origin": rec.origin,
                "theme": rec.theme,
                "universe": rec.universe,
                "ic_mean": ic_stats.get("ic_mean"),
                "icir": ic_stats.get("icir"),
            }
        )
    return {"count": len(rows), "factors": rows}


async def compute_factor_snapshot(
    factor_id: str,
    symbol: str,
    *,
    lookback: int = LOOKBACK,
    use_synthetic: bool = False,
    panel: Panel | None = None,
    sym: str | None = None,
) -> dict[str, Any]:
    factor_store.ensure()
    rec = factor_store.get(factor_id)
    if rec is None:
        return {"status": "error", "error": f"因子不存在: {factor_id}"}

    try:
        if panel is None:
            panel, sym = await _load_panel_for_symbol(symbol, lookback=lookback, use_synthetic=use_synthetic)
        elif sym is None:
            sym = normalize_symbol(symbol)
            close = panel.get("close", pd.DataFrame())
            if sym not in close.columns and symbol in close.columns:
                sym = symbol

        expr = expr_from_dict(rec.expr)
        allow_cs = rec.universe != "market" or uses_cross_section(expr)
        if rec.origin == "synth":
            values = compute_factor_panel(rec, panel)
        else:
            values = compute_expr(expr, panel, allow_cross_section=allow_cs)

        if rec.universe == "market":
            signal = collapse_to_series(values)
            series = signal.dropna()
            if series.empty:
                return {"status": "error", "error": "择时因子无有效值", "factor_id": factor_id}
            latest = float(series.iloc[-1])
            as_of = str(series.index[-1].date()) if hasattr(series.index[-1], "date") else str(series.index[-1])
            return {
                "status": "ok",
                "factor_id": factor_id,
                "name": rec.name,
                "symbol": sym,
                "mode": "timing",
                "as_of": as_of,
                "value": latest,
                "cross_section_percentile": None,
                "formula": rec.formula,
            }

        raw, pct, as_of = _latest_cs_snapshot(values, sym or normalize_symbol(symbol))
        if raw is None:
            return {"status": "error", "error": "截面因子在该标的上无有效值", "factor_id": factor_id}
        return {
            "status": "ok",
            "factor_id": factor_id,
            "name": rec.name,
            "symbol": sym,
            "mode": "cross_section",
            "as_of": as_of,
            "value": raw,
            "cross_section_percentile": pct,
            "formula": rec.formula,
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("compute_factor %s %s failed: %s", factor_id, symbol, exc)
        return {"status": "error", "error": str(exc), "factor_id": factor_id}


def factor_analysis_summary(factor_id: str) -> dict[str, Any]:
    factor_store.ensure()
    rec = factor_store.get(factor_id)
    if rec is None:
        return {"status": "error", "error": f"因子不存在: {factor_id}"}
    metrics = rec.metrics or {}
    ic_stats = metrics.get("ic_stats") or {}
    return {
        "status": "ok",
        "factor_id": rec.id,
        "name": rec.name,
        "origin": rec.origin,
        "gate_status": rec.status,
        "universe": rec.universe,
        "theme": rec.theme,
        "hypothesis": rec.hypothesis,
        "formula": rec.formula,
        "ic_stats": ic_stats,
        "gate1_passed": metrics.get("gate1_passed"),
        "gate2_passed": metrics.get("gate2_passed"),
        "gate3_passed": metrics.get("gate3_passed"),
        "reject_reason": rec.reject_reason or metrics.get("reject_reason"),
        "mode": metrics.get("mode"),
    }
