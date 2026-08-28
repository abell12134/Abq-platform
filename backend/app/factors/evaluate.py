"""Run compute + gates on a panel and optionally persist metrics."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.factors.compute import FactorComputeError, compute_expr
from app.factors.gates import evaluate_cross_section, evaluate_timing
from app.factors.ir import expr_from_dict, parse_formula, uses_cross_section
from app.factors.panel import (
    DEFAULT_EVAL_SYMBOLS,
    Panel,
    broadcast_market,
    collapse_to_series,
    panel_from_symbol_frames,
    synthetic_panel,
)
from app.factors.paper import apply_gate5_status
from app.factors.runtime import compute_factor_panel
from app.factors.store import factor_store
from app.models.factors import FactorRecord


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        x = float(obj)
        if x != x or abs(x) == float("inf"):
            return None
        return x
    if isinstance(obj, (np.integer, int)) and not isinstance(obj, bool):
        return int(obj)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if obj is None or isinstance(obj, str):
        return obj
    return obj


async def load_qlib_eval_panel(
    symbols: list[str] | None,
    lookback: int,
) -> tuple[Panel, dict[str, Any]]:
    from app.data.qlib_store import fetch_ohlcv_local, normalize_symbol

    names = symbols or DEFAULT_EVAL_SYMBOLS
    frames: dict[str, pd.DataFrame] = {}
    skipped: list[str] = []
    for sym in names:
        try:
            data = await fetch_ohlcv_local(sym, limit=lookback)
        except Exception:
            skipped.append(sym)
            continue
        bars = data.get("bars") or []
        if len(bars) < 40:
            skipped.append(sym)
            continue
        df = pd.DataFrame(bars)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        frames[normalize_symbol(sym)] = df
    if len(frames) < 5:
        raise FactorComputeError(
            f"评测标的不足 5 只（成功 {len(frames)}，跳过 {skipped[:8]}）。请确认 qlib 数据。"
        )
    panel = panel_from_symbol_frames(frames)
    market_used = None
    for mkt in ("sh000300", "sz399300", "sh000001"):
        try:
            mdata = await fetch_ohlcv_local(mkt, limit=lookback)
        except Exception:
            continue
        mbars = mdata.get("bars") or []
        if len(mbars) < 40:
            continue
        mdf = pd.DataFrame(mbars)
        mdf["date"] = pd.to_datetime(mdf["date"])
        mdf = mdf.set_index("date")
        panel = broadcast_market(panel, mdf)
        market_used = mkt
        break
    meta = {
        "source": "qlib",
        "n_stocks": len(frames),
        "n_days": int(len(panel["close"].index)),
        "skipped": skipped,
        "market": market_used,
    }
    return panel, meta


def _other_panels(panel: Panel, skip_id: str | None, universe: str) -> dict[str, pd.DataFrame]:
    others: dict[str, pd.DataFrame] = {}
    allow_cs = universe != "market"
    for rec in factor_store.list_factors():
        if skip_id and rec.id == skip_id:
            continue
        if rec.universe == "market":
            continue
        try:
            expr = expr_from_dict(rec.expr)
            others[rec.id] = compute_expr(expr, panel, allow_cross_section=allow_cs)
        except Exception:
            try:
                others[rec.id] = compute_factor_panel(rec, panel)
            except Exception:
                continue
        if len(others) >= 24:
            break
    return others


def run_eval_on_panel(
    *,
    rec: FactorRecord | None,
    formula: str | None,
    universe: str,
    panel: Panel,
    persist: bool,
) -> dict[str, Any]:
    if rec is not None and rec.origin == "synth":
        from app.factors.synth import eval_synth_record

        return eval_synth_record(rec, panel, persist=persist)

    if rec is not None:
        expr = expr_from_dict(rec.expr)
        origin = rec.origin
        hypothesis = rec.hypothesis
        universe = rec.universe
        forward_days = rec.forward_days
    else:
        if not formula:
            raise FactorComputeError("需要 factor_id 或 formula")
        expr = parse_formula(formula)
        origin = "manual"
        hypothesis = ""
        forward_days = 5

    allow_cs = universe != "market"
    if universe == "market" and uses_cross_section(expr):
        raise FactorComputeError("择时因子不能使用 rank/zscore")

    values = compute_expr(expr, panel, allow_cross_section=allow_cs)
    if universe == "market":
        close = panel.get("mkt_close")
        if close is None:
            raise FactorComputeError("择时评测需要 mkt_close（指数未加载）")
        result = evaluate_timing(
            collapse_to_series(values),
            collapse_to_series(close),
            forward_days=forward_days,
            hypothesis=hypothesis,
            origin=origin,
        )
    else:
        if "close" not in panel:
            raise FactorComputeError("截面评测需要 close")
        others = (
            _other_panels(panel, rec.id if rec else None, universe) if rec is not None else {}
        )
        result = evaluate_cross_section(
            values,
            panel["close"],
            others=others,
            forward_days=forward_days,
            hypothesis=hypothesis,
            origin=origin,
        )

    metrics = _jsonable(result)
    updated = None
    if persist and rec is not None:
        rec.metrics = metrics
        rec.reject_reason = str(result.get("reject_reason") or "")
        ic_mean = (metrics.get("ic_stats") or {}).get("ic_mean")
        if rec.status in {"paper_tracking", "frozen"}:
            new_status, gate5_note, metrics = apply_gate5_status(rec, ic_mean, metrics)
            metrics["gate5_note"] = gate5_note
            rec.status = new_status
            if new_status == "retired":
                rec.reject_reason = gate5_note
        elif not rec.builtin and rec.origin != "catalog":
            rec.status = result["status"]
        rec.metrics = metrics
        updated = factor_store.save_eval(rec)

    return {
        "factor": (updated or rec).model_dump() if rec is not None else None,
        "metrics": metrics,
        "formula": rec.formula if rec is not None else formula,
    }


async def evaluate_request(
    *,
    factor_id: str | None,
    formula: str | None,
    universe: str | None,
    symbols: list[str] | None,
    lookback: int,
    use_synthetic: bool,
    persist: bool = True,
) -> dict[str, Any]:
    rec = factor_store.get(factor_id) if factor_id else None
    if factor_id and rec is None:
        raise FileNotFoundError(factor_id)
    uni = universe or (rec.universe if rec else "csi300")
    if use_synthetic:
        panel = synthetic_panel()
        meta: dict[str, Any] = {"source": "synthetic", "n_stocks": 10, "n_days": 80}
    else:
        panel, meta = await load_qlib_eval_panel(symbols, lookback)
    out = run_eval_on_panel(
        rec=rec,
        formula=formula,
        universe=uni,
        panel=panel,
        persist=persist and rec is not None,
    )
    out["panel"] = meta
    return out
