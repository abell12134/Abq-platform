from __future__ import annotations

from typing import Any


def clean_bars(bars: list[dict[str, Any]]) -> dict[str, Any]:
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    dropped = 0
    for row in sorted(bars, key=lambda r: r.get("date", "")):
        date = row.get("date")
        close = row.get("close")
        if not date or close is None:
            dropped += 1
            continue
        if date in seen:
            dropped += 1
            continue
        seen.add(date)
        cleaned.append(row)
    if not cleaned:
        raise ValueError("清洗后无有效 K 线")
    return {
        "bars": cleaned,
        "summary": {
            "input_bars": len(bars),
            "output_bars": len(cleaned),
            "dropped": dropped,
            "first_date": cleaned[0]["date"],
            "last_date": cleaned[-1]["date"],
        },
    }


def _sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def calc_indicators(bars: list[dict[str, Any]]) -> dict[str, Any]:
    if len(bars) < 2:
        raise ValueError("指标计算至少需要 2 根 K 线")
    closes = [float(b["close"]) for b in bars]
    volumes = [float(b.get("volume", 0) or 0) for b in bars]
    last = bars[-1]
    pct_1d = (closes[-1] - closes[-2]) / closes[-2] * 100 if closes[-2] else 0.0
    pct_5d = None
    if len(closes) >= 6:
        pct_5d = (closes[-1] - closes[-6]) / closes[-6] * 100
    pct_20d = None
    if len(closes) >= 21:
        pct_20d = (closes[-1] - closes[-21]) / closes[-21] * 100
    vol_avg_5 = _sma(volumes, 5)
    vol_ratio = volumes[-1] / vol_avg_5 if vol_avg_5 else None
    ma5 = _sma(closes, 5)
    ma10 = _sma(closes, 10)
    ma20 = _sma(closes, 20)
    close = closes[-1]
    position = "unknown"
    if ma20:
        if close > ma20 * 1.02:
            position = "above_ma20"
        elif close < ma20 * 0.98:
            position = "below_ma20"
        else:
            position = "near_ma20"
    return {
        "as_of": last.get("date"),
        "close": close,
        "volume": volumes[-1],
        "pct_change_1d": round(pct_1d, 2),
        "pct_change_5d": round(pct_5d, 2) if pct_5d is not None else None,
        "pct_change_20d": round(pct_20d, 2) if pct_20d is not None else None,
        "ma5": round(ma5, 4) if ma5 is not None else None,
        "ma10": round(ma10, 4) if ma10 is not None else None,
        "ma20": round(ma20, 4) if ma20 is not None else None,
        "volume_ratio_5d": round(vol_ratio, 2) if vol_ratio is not None else None,
        "price_vs_ma20": position,
        "summary": (
            f"收盘 {close:.2f}，1日 {pct_1d:+.2f}%"
            + (f"，5日 {pct_5d:+.2f}%" if pct_5d is not None else "")
            + (f"，量比5日 {vol_ratio:.2f}" if vol_ratio is not None else "")
        ),
    }
