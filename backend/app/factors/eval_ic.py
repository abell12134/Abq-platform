"""IC / IR and layered NAV. Shared by catalog eval, LLM mine, and GP."""

from __future__ import annotations

import numpy as np
import pandas as pd

IC_MEAN_CS = 0.02
ICIR_MIN = 0.25
IC_POS_RATIO_MIN = 0.0  # informational; Gate 1 uses ICIR + |IC|
IC_MEAN_TIMING = 0.05
OOS_IC_MIN = 0.01
OOS_RATIO_MIN = 0.0  # same sign required; magnitude floor is OOS_IC_MIN
MAX_CORR = 0.7
FORWARD_DAYS = 5
MIN_VALID_PER_DATE = 5
MAX_MISSING = 0.30
MAD_N = 3.0
TRAIN_FRAC = 0.7


def winsorize_mad(series: pd.Series, n: float = MAD_N) -> pd.Series:
    median = series.median()
    mad = (series - median).abs().median()
    if mad == 0 or pd.isna(mad):
        return series
    scale = n * mad * 1.4826
    return series.clip(lower=median - scale, upper=median + scale)


def winsorize_cross_sectional(factor: pd.DataFrame, n: float = MAD_N) -> pd.DataFrame:
    return factor.apply(lambda row: winsorize_mad(row, n), axis=1)


def forward_returns(close: pd.DataFrame, n: int = FORWARD_DAYS) -> pd.DataFrame:
    return close.shift(-n) / close - 1.0


def _spearman_pair(a: pd.Series, b: pd.Series) -> float:
    if a.size < 3:
        return float("nan")
    corr = a.rank(method="average").corr(b.rank(method="average"), method="pearson")
    return float(corr) if pd.notna(corr) else float("nan")


def rank_ic_series(
    factor: pd.DataFrame,
    fwd: pd.DataFrame,
    *,
    max_missing: float = MAX_MISSING,
    min_valid: int = MIN_VALID_PER_DATE,
) -> pd.Series:
    dates = factor.index.intersection(fwd.index)
    codes = factor.columns.intersection(fwd.columns)
    if len(dates) == 0 or len(codes) == 0:
        return pd.Series(dtype=float, name="rank_ic")
    f = factor.loc[dates, codes]
    r = fwd.loc[dates, codes]
    total = len(codes)
    ic_vals: list[float] = []
    for dt in dates:
        fv = f.loc[dt].dropna()
        rv = r.loc[dt].dropna()
        common = fv.index.intersection(rv.index)
        if len(common) < min_valid:
            ic_vals.append(np.nan)
            continue
        if total > 0 and (1 - len(common) / total) > max_missing:
            ic_vals.append(np.nan)
            continue
        ic_vals.append(_spearman_pair(fv[common], rv[common]))
    return pd.Series(ic_vals, index=dates, name="rank_ic")


def timing_ic_series(signal: pd.Series, fwd: pd.Series) -> pd.Series:
    aligned = pd.concat([signal, fwd], axis=1, keys=["s", "r"]).dropna()
    if aligned.empty:
        return pd.Series(dtype=float, name="timing_ic")
    corr = _spearman_pair(aligned["s"], aligned["r"])
    return pd.Series([corr], index=[aligned.index[-1]], name="timing_ic")


def serialize_ic_series(ic: pd.Series, *, max_points: int = 120) -> list[dict[str, float | str]]:
    """Down-sample daily IC for storage and charting."""
    valid = ic.dropna()
    if valid.empty:
        return []
    rows: list[dict[str, float | str]] = []
    for dt, val in valid.items():
        date_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
        rows.append({"date": date_str, "ic": round(float(val), 6)})
    if len(rows) <= max_points:
        return rows
    stride = max(1, len(rows) // max_points)
    return rows[::stride][-max_points:]


def timing_ic_series_rolling(
    signal: pd.Series,
    fwd: pd.Series,
    *,
    window: int = 20,
    min_periods: int = 12,
) -> pd.Series:
    aligned = pd.concat([signal, fwd], axis=1, keys=["s", "r"]).dropna()
    if len(aligned) < min_periods:
        return pd.Series(dtype=float, name="timing_ic")
    out: list[float] = []
    idx: list = []
    for end in range(min_periods - 1, len(aligned)):
        start = max(0, end - window + 1)
        chunk = aligned.iloc[start : end + 1]
        out.append(_spearman_pair(chunk["s"], chunk["r"]))
        idx.append(aligned.index[end])
    return pd.Series(out, index=idx, name="timing_ic")


def ic_summary(ic: pd.Series) -> dict:
    valid = ic.dropna()
    if valid.empty:
        return {
            "ic_mean": None,
            "ic_std": None,
            "icir": None,
            "ic_pos_ratio": None,
            "valid_days": 0,
        }
    mean = float(valid.mean())
    std = float(valid.std(ddof=1)) if len(valid) > 1 else 0.0
    icir = mean / std if std > 0 else 0.0
    return {
        "ic_mean": round(mean, 6),
        "ic_std": round(std, 6),
        "icir": round(icir, 4),
        "ic_pos_ratio": round(float((valid > 0).mean()), 4),
        "valid_days": int(len(valid)),
    }


def split_is_oos(ic: pd.Series, train_frac: float = TRAIN_FRAC) -> tuple[pd.Series, pd.Series]:
    valid = ic.dropna()
    if len(valid) < 6:
        return valid, pd.Series(dtype=float)
    split = max(3, int(len(valid) * train_frac))
    if split >= len(valid) - 2:
        split = len(valid) - 3
    return valid.iloc[:split], valid.iloc[split:]


def mean_cs_corr(a: pd.DataFrame, b: pd.DataFrame) -> float:
    """Mean of daily cross-sectional Spearman between two factors."""
    dates = a.index.intersection(b.index)
    cols = a.columns.intersection(b.columns)
    if len(dates) == 0 or len(cols) == 0:
        return float("nan")
    corrs: list[float] = []
    for dt in dates:
        x = a.loc[dt, cols].dropna()
        y = b.loc[dt, cols].dropna()
        common = x.index.intersection(y.index)
        if len(common) < MIN_VALID_PER_DATE:
            continue
        c = _spearman_pair(x[common], y[common])
        if pd.notna(c):
            corrs.append(float(c))
    if not corrs:
        return float("nan")
    return float(np.mean(corrs))


def group_equity(factor: pd.DataFrame, fwd: pd.DataFrame, n_groups: int = 5) -> pd.DataFrame:
    if n_groups < 1:
        raise ValueError("n_groups must be >= 1")
    dates = sorted(factor.index.intersection(fwd.index))
    codes = factor.columns.intersection(fwd.columns)
    if not dates or len(codes) == 0:
        return pd.DataFrame()
    acc = {f"Group_{i + 1}": 1.0 for i in range(n_groups)}
    rows: list[dict[str, float]] = []
    index: list = []
    for dt in dates:
        f = factor.loc[dt, codes].dropna()
        r = fwd.loc[dt, codes].dropna()
        common = f.index.intersection(r.index)
        if len(common) < n_groups * 2:
            continue
        ranked = pd.qcut(f[common].rank(method="first"), n_groups, labels=False, duplicates="drop")
        if ranked.nunique() < n_groups:
            continue
        index.append(dt)
        row: dict[str, float] = {}
        for g in range(n_groups):
            members = common[ranked == g]
            ret = float(r[members].mean()) if len(members) else 0.0
            acc[f"Group_{g + 1}"] *= 1.0 + ret
            row[f"Group_{g + 1}"] = acc[f"Group_{g + 1}"]
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows, index=index)
