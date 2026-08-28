"""Map natural-language time hints to OHLCV bar limits (trading days)."""

from __future__ import annotations

import re

DEFAULT_OHLCV_LIMIT = 63

_LIMIT_PRESETS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"半年|6\s*个?月|六个月"), 120),
    (re.compile(r"(?:一|1)\s*年|12\s*个?月|十二个月"), 252),
    (re.compile(r"3\s*个?月|三个月|一季(?:度)?"), 63),
    (re.compile(r"1\s*个?月|一个月"), 22),
]

_N_DAYS_RE = re.compile(
    r"(?:最近|近|过去)?\s*(\d{1,3})\s*(?:个?交易日?|日|天)",
    re.IGNORECASE,
)


def parse_ohlcv_limit(message: str = "", *, focus: str | None = None) -> int:
    """Return trading-day bar count; default ~3 months when no window is mentioned."""
    text = f"{message or ''} {focus or ''}".strip()
    if not text:
        return DEFAULT_OHLCV_LIMIT

    for pattern, limit in _LIMIT_PRESETS:
        if pattern.search(text):
            return limit

    match = _N_DAYS_RE.search(text)
    if match:
        return max(5, min(400, int(match.group(1))))

    return DEFAULT_OHLCV_LIMIT


def ohlcv_window_label(limit: int) -> str:
    labels = {22: "1个月", 63: "3个月", 120: "半年", 252: "1年"}
    return labels.get(limit, f"{limit}日")
