from __future__ import annotations

import asyncio
import re
import tarfile
from pathlib import Path

import numpy as np

from app.config import settings

_extract_lock = asyncio.Lock()
_ready = False


def normalize_symbol(symbol: str) -> str:
    s = symbol.strip().lower().replace(".", "")
    if re.match(r"^(sh|sz|bj)\d+", s):
        return s
    digits = re.sub(r"\D", "", s)
    if not digits:
        raise ValueError(f"无法解析股票代码: {symbol}")
    if digits.startswith(("6", "5", "9")):
        return f"sh{digits}"
    if digits.startswith(("0", "3")):
        return f"sz{digits}"
    if digits.startswith(("4", "8")):
        return f"bj{digits}"
    return f"sh{digits}"


def to_baostock_code(qlib_symbol: str) -> str:
    """sh600519 → sh.600519"""
    s = normalize_symbol(qlib_symbol)
    return f"{s[:2]}.{s[2:]}"


def _extract_sync() -> None:
    tar_path = settings.qlib_tar_path
    root = settings.qlib_root
    if (root / "calendars" / "day.txt").exists():
        return
    if not tar_path.exists():
        raise FileNotFoundError(f"qlib 数据包不存在: {tar_path}")
    root.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(path=root.parent, filter="data")


async def ensure_qlib_ready() -> Path:
    global _ready
    if _ready and (settings.qlib_root / "calendars" / "day.txt").exists():
        return settings.qlib_root
    async with _extract_lock:
        if not (settings.qlib_root / "calendars" / "day.txt").exists():
            await asyncio.to_thread(_extract_sync)
        _ready = True
        return settings.qlib_root


def _load_calendar(root: Path) -> list[str]:
    cal_file = root / "calendars" / "day.txt"
    lines = cal_file.read_text(encoding="utf-8").strip().splitlines()
    return [ln.strip() for ln in lines if ln.strip()]


async def get_calendar_last_date() -> str | None:
    root = await ensure_qlib_ready()
    cal = _load_calendar(root)
    return cal[-1] if cal else None


def _read_feature(
    root: Path, symbol: str, field: str, calendar: list[str]
) -> list[tuple[str, float]]:
    bin_path = root / "features" / symbol / f"{field}.day.bin"
    if not bin_path.exists():
        return []
    arr = np.fromfile(bin_path, dtype="<f4")
    if arr.size < 2:
        return []
    start = int(arr[0])
    values = arr[1:]
    out: list[tuple[str, float]] = []
    for i, val in enumerate(values):
        idx = start + i
        if idx >= len(calendar):
            break
        if np.isnan(val):
            continue
        out.append((calendar[idx], float(val)))
    return out


def _align_series(
    series: dict[str, list[tuple[str, float]]],
    dates: list[str],
) -> dict[str, dict[str, float]]:
    by_date: dict[str, dict[str, float]] = {d: {} for d in dates}
    for field, pairs in series.items():
        lookup = dict(pairs)
        for d in dates:
            if d in lookup:
                by_date[d][field] = lookup[d]
    return by_date


async def fetch_ohlcv_local(
    symbol: str,
    *,
    limit: int = 30,
) -> dict:
    """从 qlib bin 读取日 K，价格还原为人民币（stored / factor）。"""
    root = await ensure_qlib_ready()
    qlib_sym = normalize_symbol(symbol)
    cal = _load_calendar(root)
    fields = ("open", "high", "low", "close", "volume", "amount")
    series: dict[str, list[tuple[str, float]]] = {
        f: _read_feature(root, qlib_sym, f, cal) for f in fields
    }
    factor_series = dict(_read_feature(root, qlib_sym, "factor", cal))
    if not series["close"]:
        raise ValueError(f"qlib 中未找到 {qlib_sym}，请检查代码或数据包")

    close_dates = [d for d, _ in series["close"]]
    n = min(limit, len(close_dates))
    dates = close_dates[-n:]
    aligned = _align_series(series, dates)

    rows: list[dict] = []
    for d in dates:
        f = factor_series.get(d) or 1.0
        if f <= 0:
            f = 1.0
        raw = aligned[d]
        if "close" not in raw:
            continue
        row: dict = {"date": d}
        for price_field in ("open", "high", "low", "close"):
            if price_field in raw:
                row[price_field] = raw[price_field] / f
        if "volume" in raw:
            row["volume"] = raw["volume"]
        if "amount" in raw:
            row["amount"] = raw["amount"]
        rows.append(row)

    if not rows:
        raise ValueError(f"qlib 中 {qlib_sym} 无有效 K 线")

    last = rows[-1]
    return {
        "source": "qlib_bin",
        "symbol": qlib_sym,
        "price_unit": "yuan",
        "bars": rows,
        "summary": {
            "last_date": last["date"],
            "close": last.get("close"),
            "volume": last.get("volume"),
            "bars_returned": len(rows),
        },
    }
