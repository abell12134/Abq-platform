"""Cross-sectional factor stock screener — rank universe by composite factor score."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from app.data.qlib_store import normalize_symbol
from app.factors import ops
from app.factors.compute import FactorComputeError
from app.factors.evaluate import load_qlib_eval_panel
from app.factors.panel import Panel, synthetic_panel
from app.factors.runtime import compute_factor_panel
from app.factors.store import FactorStoreError, factor_store
from app.factors.synth import SynthMethod, _weight_for, combine_factor_panels
from app.factors.universe import fetch_universe_symbols
from app.models.factors import FactorRecord, FactorScreenApplyRequest, FactorScreenRequest
from app.models.portfolio import PortfolioMember, PortfolioUpdate
from app.persistence.portfolio_store import portfolio_store

log = logging.getLogger(__name__)

SCREEN_STATUSES = frozenset({"live", "paper_tracking", "passed_auto"})


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _signed_zscore(values: pd.DataFrame, rec: FactorRecord) -> pd.DataFrame:
    z = ops.op_zscore(values)
    ic_stats = (rec.metrics or {}).get("ic_stats") or {}
    ic_mean = ic_stats.get("ic_mean")
    if isinstance(ic_mean, (int, float)) and ic_mean < 0:
        z = -z
    return z


def _resolve_factor_ids(body: FactorScreenRequest) -> list[str]:
    if body.factor_ids:
        return list(dict.fromkeys(body.factor_ids))
    picked: list[str] = []
    for rec in factor_store.list_factors():
        if rec.universe == "market":
            continue
        if rec.universe != body.universe:
            continue
        if rec.status not in SCREEN_STATUSES:
            continue
        picked.append(rec.id)
        if len(picked) >= body.max_factors:
            break
    if not picked:
        raise FactorStoreError(
            f"股票池 {body.universe} 下没有可用的截面因子（需 live/paper_tracking/passed_auto）"
        )
    return picked


def _load_records(factor_ids: list[str], universe: str) -> list[FactorRecord]:
    records: list[FactorRecord] = []
    for fid in factor_ids:
        rec = factor_store.get(fid)
        if rec is None:
            raise FactorStoreError(f"因子不存在: {fid}")
        if rec.universe == "market":
            raise FactorStoreError(f"{fid} 为择时因子，不能用于截面选股")
        if rec.universe != universe:
            raise FactorStoreError(f"{fid} 属于 {rec.universe}，与股票池 {universe} 不一致")
        records.append(rec)
    return records


async def run_factor_screen(body: FactorScreenRequest) -> dict[str, Any]:
    factor_store.ensure()
    factor_ids = _resolve_factor_ids(body)
    records = _load_records(factor_ids, body.universe)

    symbols, universe_meta = await fetch_universe_symbols(
        body.universe,
        max_symbols=body.max_symbols,
    )

    if body.use_synthetic:
        panel: Panel = synthetic_panel(n_stocks=max(12, len(symbols)), n_days=body.lookback, seed=17)
        panel_meta = {"source": "synthetic", "n_stocks": len(panel["close"].columns)}
        screen_symbols = list(panel["close"].columns.astype(str))
    else:
        panel, panel_meta = await load_qlib_eval_panel(symbols, body.lookback)
        screen_symbols = [str(c) for c in panel["close"].columns]

    method: SynthMethod = body.method
    frames: list[pd.DataFrame] = []
    weights: list[float] = []
    factor_info: list[dict[str, Any]] = []

    success_records: list[FactorRecord] = []
    for rec in records:
        try:
            values = compute_factor_panel(rec, panel)
            z = _signed_zscore(values, rec)
            frames.append(z)
            weights.append(_weight_for(method, rec))
            success_records.append(rec)
            ic_stats = (rec.metrics or {}).get("ic_stats") or {}
            factor_info.append(
                {
                    "id": rec.id,
                    "name": rec.name,
                    "status": rec.status,
                    "ic_mean": ic_stats.get("ic_mean"),
                    "weight": weights[-1],
                }
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("screener skip factor %s: %s", rec.id, exc)

    if not frames:
        raise FactorComputeError("所有因子计算失败，无法完成选股")

    combined = combine_factor_panels(frames, weights)
    valid = combined.dropna(how="all")
    if valid.empty:
        raise FactorComputeError("合成得分面板为空")

    last = valid.iloc[-1]
    as_of = valid.index[-1]
    as_of_str = str(as_of.date()) if hasattr(as_of, "date") else str(as_of)

    ranked = last.dropna().sort_values(ascending=False)
    picks: list[dict[str, Any]] = []
    for rank, (sym, score) in enumerate(ranked.head(body.top_n).items(), start=1):
        sym_norm = normalize_symbol(str(sym))
        factor_scores: dict[str, float] = {}
        for rec, frame in zip(success_records, frames, strict=True):
            row = frame.iloc[-1]
            val = row.get(sym)
            if val is None or val != val:
                val = row.get(sym_norm) or row.get(str(sym))
            if val is not None and val == val:
                factor_scores[rec.id] = round(float(val), 4)
        picks.append(
            {
                "rank": rank,
                "symbol": sym_norm,
                "score": round(float(score), 4),
                "factor_scores": factor_scores,
            }
        )

    return {
        "status": "ok",
        "as_of": as_of_str,
        "generated_at": _now(),
        "universe": body.universe,
        "method": method,
        "factor_ids": [r.id for r in success_records],
        "factors": factor_info,
        "top_n": body.top_n,
        "picks": picks,
        "meta": {
            "universe": universe_meta,
            "panel": panel_meta,
            "screen_universe_size": len(screen_symbols),
            "use_synthetic": body.use_synthetic,
        },
    }


def apply_screen_to_portfolio(body: FactorScreenApplyRequest) -> dict[str, Any]:
    portfolio_store.ensure()
    rec = portfolio_store.get(body.portfolio_id)
    if rec is None:
        raise FileNotFoundError(body.portfolio_id)

    symbols = [normalize_symbol(s) for s in body.symbols if str(s).strip()]
    if not symbols:
        raise ValueError("symbols 不能为空")

    if body.mode == "replace":
        members = [PortfolioMember(symbol=s) for s in symbols]
    else:
        existing = {m.symbol for m in rec.members}
        members = list(rec.members)
        for sym in symbols:
            if sym not in existing:
                members.append(PortfolioMember(symbol=sym))
                existing.add(sym)

    updated = portfolio_store.update(body.portfolio_id, PortfolioUpdate(members=members))
    return {
        "status": "ok",
        "portfolio_id": updated.id,
        "name": updated.name,
        "mode": body.mode,
        "added": len(symbols) if body.mode == "replace" else len(updated.members) - len(rec.members),
        "member_count": len(updated.members),
        "members": [m.model_dump() for m in updated.members],
    }
