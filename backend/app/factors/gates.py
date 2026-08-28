"""Five-gate admission. LLM / GP / hand-written share these thresholds."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.factors.eval_ic import (
    FORWARD_DAYS,
    IC_MEAN_CS,
    IC_MEAN_TIMING,
    ICIR_MIN,
    MAX_CORR,
    OOS_IC_MIN,
    forward_returns,
    ic_summary,
    mean_cs_corr,
    rank_ic_series,
    serialize_ic_series,
    split_is_oos,
    timing_ic_series_rolling,
    winsorize_cross_sectional,
)


def _finite(x: object) -> bool:
    return isinstance(x, (int, float)) and x == x and abs(x) != float("inf")


def _spearman(a: pd.Series, b: pd.Series, *, min_n: int = 8) -> float:
    """Pearson of ranks — avoids pandas' scipy dependency for Spearman."""
    aligned = pd.concat([a, b], axis=1, keys=["a", "b"]).dropna()
    if len(aligned) < min_n:
        return float("nan")
    ra = aligned["a"].rank(method="average")
    rb = aligned["b"].rank(method="average")
    return float(ra.corr(rb, method="pearson"))


def evaluate_cross_section(
    factor: pd.DataFrame,
    close: pd.DataFrame,
    *,
    others: dict[str, pd.DataFrame] | None = None,
    forward_days: int = FORWARD_DAYS,
    hypothesis: str = "",
    origin: str = "manual",
) -> dict[str, Any]:
    clean = winsorize_cross_sectional(factor)
    fwd = forward_returns(close, forward_days)
    ic = rank_ic_series(clean, fwd)
    stats = ic_summary(ic)
    ic_mean = stats["ic_mean"]
    icir = stats["icir"]

    gate1 = bool(
        _finite(ic_mean)
        and abs(float(ic_mean)) >= IC_MEAN_CS
        and _finite(icir)
        and abs(float(icir)) >= ICIR_MIN
    )
    gate1_detail = {
        "ic_mean": ic_mean,
        "icir": icir,
        "threshold_ic_mean": IC_MEAN_CS,
        "threshold_icir": ICIR_MIN,
    }

    max_corr = None
    corr_with = None
    if others:
        best = 0.0
        best_name = None
        for name, panel in others.items():
            c = mean_cs_corr(clean, panel)
            if c == c and abs(c) >= abs(best):
                best = float(c)
                best_name = name
        if best_name is not None:
            max_corr = round(best, 4)
            corr_with = best_name
    gate2 = max_corr is None or abs(max_corr) < MAX_CORR
    gate2_detail = {
        "max_corr": max_corr,
        "corr_with": corr_with,
        "threshold": MAX_CORR,
        "skipped": others is None,
    }

    is_ic, oos_ic = split_is_oos(ic)
    is_mean = float(is_ic.mean()) if not is_ic.empty else float("nan")
    oos_mean = float(oos_ic.mean()) if not oos_ic.empty else float("nan")
    same_sign = _finite(is_mean) and _finite(oos_mean) and (is_mean * oos_mean) > 0
    gate3 = bool(same_sign and abs(oos_mean) >= OOS_IC_MIN)
    gate3_detail = {
        "ic_is_mean": round(is_mean, 6) if _finite(is_mean) else None,
        "ic_oos_mean": round(oos_mean, 6) if _finite(oos_mean) else None,
        "threshold_oos": OOS_IC_MIN,
    }

    hyp_ok = len((hypothesis or "").strip()) >= 8
    if origin == "gp":
        gate4 = True
        gate4_note = "GP 可无假设，最多 passed_auto"
    else:
        gate4 = hyp_ok
        gate4_note = "ok" if hyp_ok else "缺少可解释经济逻辑（≥8 字）"

    status, reason = _status_from_gates(
        gate1, gate2, gate3, gate4, origin=origin, hyp_ok=hyp_ok
    )
    return {
        "mode": "cs",
        "ic_stats": stats,
        "ic_series": serialize_ic_series(ic),
        "gate1_passed": gate1,
        "gate1_detail": gate1_detail,
        "gate2_passed": gate2,
        "gate2_detail": gate2_detail,
        "gate3_passed": gate3,
        "gate3_detail": gate3_detail,
        "gate4_passed": gate4,
        "gate4_note": gate4_note,
        "status": status,
        "reject_reason": reason,
    }


def evaluate_timing(
    signal: pd.Series,
    close: pd.Series,
    *,
    forward_days: int = FORWARD_DAYS,
    hypothesis: str = "",
    origin: str = "gp",
) -> dict[str, Any]:
    fwd = close.shift(-forward_days) / close - 1.0
    aligned = pd.concat([signal, fwd], axis=1, keys=["s", "r"]).dropna()
    overall = _spearman(aligned["s"], aligned["r"]) if not aligned.empty else float("nan")
    n = len(aligned)
    split = max(8, int(n * 0.7)) if n >= 16 else n
    is_part = aligned.iloc[:split]
    oos_part = aligned.iloc[split:]
    is_corr = _spearman(is_part["s"], is_part["r"]) if len(is_part) >= 8 else float("nan")
    oos_corr = _spearman(oos_part["s"], oos_part["r"]) if len(oos_part) >= 8 else float("nan")

    stats = {
        "ic_mean": round(overall, 6) if _finite(overall) else None,
        "ic_std": None,
        "icir": None,
        "ic_pos_ratio": None,
        "valid_days": int(n),
    }
    gate1 = bool(_finite(overall) and abs(overall) >= IC_MEAN_TIMING)
    same_sign = _finite(is_corr) and _finite(oos_corr) and (is_corr * oos_corr) > 0
    gate3 = bool(same_sign and abs(oos_corr) >= OOS_IC_MIN)
    hyp_ok = len((hypothesis or "").strip()) >= 8
    gate4 = True if origin == "gp" else hyp_ok
    status, reason = _status_from_gates(
        gate1, True, gate3, gate4, origin=origin, hyp_ok=hyp_ok
    )
    ic_roll = timing_ic_series_rolling(aligned["s"], aligned["r"])
    return {
        "mode": "timing",
        "ic_stats": stats,
        "ic_series": serialize_ic_series(ic_roll),
        "gate1_passed": gate1,
        "gate1_detail": {
            "ic_mean": stats["ic_mean"],
            "threshold_ic_mean": IC_MEAN_TIMING,
        },
        "gate2_passed": True,
        "gate2_detail": {"skipped": True},
        "gate3_passed": gate3,
        "gate3_detail": {
            "ic_is_mean": round(is_corr, 6) if _finite(is_corr) else None,
            "ic_oos_mean": round(oos_corr, 6) if _finite(oos_corr) else None,
            "threshold_oos": OOS_IC_MIN,
        },
        "gate4_passed": gate4,
        "gate4_note": "GP 可无假设" if origin == "gp" else ("ok" if hyp_ok else "缺少经济逻辑"),
        "status": status,
        "reject_reason": reason,
    }


def _status_from_gates(
    g1: bool,
    g2: bool,
    g3: bool,
    g4: bool,
    *,
    origin: str,
    hyp_ok: bool,
) -> tuple[str, str]:
    if not g1:
        return "rejected", "初筛未过"
    if not g2:
        return "rejected", "与库内因子相关过高"
    if not g3:
        return "rejected", "样本外未过（反号或过弱）"
    if origin == "gp" and not hyp_ok:
        return "passed_auto", "过自动关卡，待补经济逻辑"
    if not g4:
        return "rejected", "缺少可解释经济逻辑"
    return "passed_auto", "过自动关卡"
