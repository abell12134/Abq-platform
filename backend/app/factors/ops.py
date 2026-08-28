"""Whitelist operators on wide panels (index=date, columns=symbol). Lookahead banned."""

from __future__ import annotations

import numpy as np
import pandas as pd

EPS = 1e-12


def _as_float(df: pd.DataFrame) -> pd.DataFrame:
    if df.dtypes.eq(np.float64).all():
        return df
    return df.astype(np.float64)


def _require_n(n: int, *, min_n: int = 1, name: str = "window") -> None:
    if n < min_n:
        raise ValueError(f"{name} must be >= {min_n}, got {n}")


def align_pair(a: pd.DataFrame, b: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    idx = a.index.union(b.index)
    cols = a.columns.union(b.columns)
    return a.reindex(index=idx, columns=cols), b.reindex(index=idx, columns=cols)


def op_add(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    x, y = align_pair(_as_float(a), _as_float(b))
    return x.add(y)


def op_sub(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    x, y = align_pair(_as_float(a), _as_float(b))
    return x.sub(y)


def op_mul(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    x, y = align_pair(_as_float(a), _as_float(b))
    return x.mul(y)


def op_div(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    x, y = align_pair(_as_float(a), _as_float(b))
    denom = y.where(y.abs() > EPS)
    out = x.div(denom)
    return out.replace([np.inf, -np.inf], np.nan)


def op_abs(df: pd.DataFrame) -> pd.DataFrame:
    return _as_float(df).abs()


def op_log(df: pd.DataFrame) -> pd.DataFrame:
    x = _as_float(df)
    return np.log(x.where(x > 0))


def op_sign(df: pd.DataFrame) -> pd.DataFrame:
    return np.sign(_as_float(df))


def op_sqrt(df: pd.DataFrame) -> pd.DataFrame:
    x = _as_float(df)
    return np.sqrt(x.where(x >= 0))


def op_rank(df: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional percentile rank per date."""
    return df.rank(axis=1, method="average", pct=True, na_option="keep")


def op_zscore(df: pd.DataFrame) -> pd.DataFrame:
    x = _as_float(df)
    mean = x.mean(axis=1, skipna=True)
    std = x.std(axis=1, ddof=1, skipna=True)
    out = x.sub(mean, axis=0).div(std.where(std > 0), axis=0)
    return out.replace([np.inf, -np.inf], np.nan)


def op_delay(df: pd.DataFrame, n: int) -> pd.DataFrame:
    _require_n(n, min_n=1, name="delay")
    return _as_float(df).shift(n)


def op_delta(df: pd.DataFrame, n: int) -> pd.DataFrame:
    _require_n(n, min_n=1, name="delta")
    x = _as_float(df)
    return x.sub(x.shift(n))


def op_ts_mean(df: pd.DataFrame, n: int) -> pd.DataFrame:
    _require_n(n, min_n=1, name="ts_mean")
    return _as_float(df).rolling(window=n, min_periods=n).mean()


def op_ts_sum(df: pd.DataFrame, n: int) -> pd.DataFrame:
    _require_n(n, min_n=1, name="ts_sum")
    return _as_float(df).rolling(window=n, min_periods=n).sum()


def op_ts_std(df: pd.DataFrame, n: int) -> pd.DataFrame:
    _require_n(n, min_n=2, name="ts_std")
    return _as_float(df).rolling(window=n, min_periods=n).std(ddof=1)


def op_ts_max(df: pd.DataFrame, n: int) -> pd.DataFrame:
    _require_n(n, min_n=1, name="ts_max")
    return _as_float(df).rolling(window=n, min_periods=n).max()


def op_ts_min(df: pd.DataFrame, n: int) -> pd.DataFrame:
    _require_n(n, min_n=1, name="ts_min")
    return _as_float(df).rolling(window=n, min_periods=n).min()


def _last_pct_rank(arr: np.ndarray) -> float:
    if np.isnan(arr).all():
        return np.nan
    last = arr[-1]
    if np.isnan(last):
        return np.nan
    valid = arr[~np.isnan(arr)]
    if valid.size == 0:
        return np.nan
    less = (valid < last).sum()
    eq = (valid == last).sum()
    rank_avg = less + 0.5 * (eq + 1)
    return float(rank_avg / valid.size)


def op_ts_rank(df: pd.DataFrame, n: int) -> pd.DataFrame:
    _require_n(n, min_n=1, name="ts_rank")
    return _as_float(df).rolling(window=n, min_periods=n).apply(_last_pct_rank, raw=True)


def op_ts_corr(x: pd.DataFrame, y: pd.DataFrame, n: int) -> pd.DataFrame:
    _require_n(n, min_n=2, name="ts_corr")
    a, b = align_pair(_as_float(x), _as_float(y))
    corr = a.rolling(window=n, min_periods=n).corr(b)
    return corr.replace([np.inf, -np.inf], np.nan)
