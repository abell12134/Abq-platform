"""Wide OHLCV panels (index=date, columns=symbol) plus market broadcast."""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from app.factors.ir import MARKET_VARS, STOCK_VARS

Panel = dict[str, pd.DataFrame]

DEFAULT_EVAL_SYMBOLS = [
    "600519",
    "000001",
    "000002",
    "600036",
    "601318",
    "000858",
    "002415",
    "600276",
    "601166",
    "000568",
]


def panel_from_symbol_frames(frames: dict[str, pd.DataFrame]) -> Panel:
    """Each value is a long-ish OHLCV frame indexed by date."""
    if not frames:
        raise ValueError("无标的数据")
    fields = [c for c in ("open", "high", "low", "close", "volume", "amount") if True]
    panel: Panel = {}
    for field in fields:
        pieces = {}
        for sym, df in frames.items():
            if field not in df.columns:
                continue
            col = df[field]
            col.index = pd.to_datetime(col.index)
            pieces[sym] = col
        if pieces:
            wide = pd.DataFrame(pieces).sort_index()
            panel[field] = wide.astype(float)
    if "close" not in panel:
        raise ValueError("面板缺少 close")
    return panel


def broadcast_market(panel: Panel, market: pd.DataFrame) -> Panel:
    """Add mkt_* columns, same value across all stocks on a date."""
    if panel.get("close") is None or panel["close"].empty:
        raise ValueError("无法向空面板广播大盘")
    close = panel["close"]
    mkt = market.copy()
    mkt.index = pd.to_datetime(mkt.index)
    out = dict(panel)
    mapping = {
        "open": "mkt_open",
        "high": "mkt_high",
        "low": "mkt_low",
        "close": "mkt_close",
        "volume": "mkt_volume",
        "amount": "mkt_amount",
        "advance": "mkt_advance",
        "decline": "mkt_decline",
        "limit_up": "mkt_limit_up",
    }
    for src, dest in mapping.items():
        if src not in mkt.columns:
            continue
        series = mkt[src].reindex(close.index)
        out[dest] = pd.DataFrame(
            {col: series.to_numpy() for col in close.columns},
            index=close.index,
        )
    return out


def synthetic_panel(
    n_stocks: int = 10,
    n_days: int = 80,
    seed: int = 7,
) -> Panel:
    """Deterministic random-walk panel for tests (includes mkt_*)."""
    rng = pd.Series(range(n_days))
    idx = pd.bdate_range("2022-01-03", periods=n_days)
    frames: dict[str, pd.DataFrame] = {}
    mkt_close = 3000.0
    mkt_rows: list[dict] = []
    for i, _dt in enumerate(idx):
        mkt_close *= 1.0 + ((i * 17 + seed) % 11 - 5) / 400.0
        mkt_rows.append(
            {
                "open": mkt_close * 0.999,
                "high": mkt_close * 1.01,
                "low": mkt_close * 0.99,
                "close": mkt_close,
                "volume": 1e9 + i * 1e6,
                "amount": mkt_close * 1e9,
                "advance": 800 + (i % 40),
                "decline": 700 + ((i * 3) % 50),
            }
        )
    mkt = pd.DataFrame(mkt_rows, index=idx)
    for s in range(n_stocks):
        px = 10.0 + s
        rows = []
        for i, _dt in enumerate(idx):
            shock = ((i * (s + 3) + seed) % 13 - 6) / 200.0
            px *= 1.0 + shock
            vol = 1e6 * (1 + (s % 5) / 10) * (1 + (i % 7) / 20)
            rows.append(
                {
                    "open": px * 0.998,
                    "high": px * 1.02,
                    "low": px * 0.98,
                    "close": px,
                    "volume": vol,
                    "amount": px * vol,
                }
            )
        frames[f"s{s:02d}"] = pd.DataFrame(rows, index=idx)
    _ = rng  # keep seed-ish usage obvious
    return broadcast_market(panel_from_symbol_frames(frames), mkt)


def collapse_to_series(df: pd.DataFrame) -> pd.Series:
    """Timing: take the first column (mkt terminals are identical across names)."""
    if df.empty:
        return pd.Series(dtype=float)
    return df.iloc[:, 0].rename("signal")


def required_fields(var_names: Iterable[str]) -> tuple[set[str], set[str]]:
    names = set(var_names)
    return names & STOCK_VARS, names & MARKET_VARS
