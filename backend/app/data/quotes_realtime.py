"""A 股实时行情（腾讯 → 东财回退）。"""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
from typing import Any

from app.data.akshare_client import run_sync, to_digits
from app.data.market_quotes import _http_json, secid, to_instrument
from app.data.qlib_store import normalize_symbol

log = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 abq-lab"
_EM_URL = (
    "http://push2.eastmoney.com/api/qt/stock/get"
    "?ut=fa5fd1943c7b386f172d6893dbfba10b&invt=2&fltt=2"
    "&fields=f43,f44,f45,f46,f47,f48,f57,f58,f60,f169,f170"
    "&secid={secid}"
)


def _num(value: Any) -> float | None:
    if value is None or value == "-":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fetch_tencent(qlib_symbol: str) -> dict[str, Any] | None:
    url = f"http://qt.gtimg.cn/q={qlib_symbol}"
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Referer": "https://gu.qq.com/"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("gbk", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.debug("tencent quote failed %s: %s", qlib_symbol, exc)
        return None

    m = re.search(r'"([^"]+)"', raw)
    if not m:
        return None
    parts = m.group(1).split("~")
    if len(parts) < 34:
        return None

    price = _num(parts[3])
    prev_close = _num(parts[4])
    if price is None:
        return None

    change = _num(parts[31]) if len(parts) > 31 else None
    pct = _num(parts[32]) if len(parts) > 32 else None
    if change is None and prev_close:
        change = round(price - prev_close, 4)
    if pct is None and prev_close:
        pct = round((price / prev_close - 1) * 100, 4)

    high = _num(parts[33]) if len(parts) > 33 else None
    low = _num(parts[34]) if len(parts) > 34 else None
    if high is not None and high <= 0:
        high = None
    if low is not None and low <= 0:
        low = None

    return {
        "source": "tencent",
        "symbol": qlib_symbol,
        "name": parts[1] or None,
        "code": parts[2] or to_digits(qlib_symbol),
        "price": price,
        "prev_close": prev_close,
        "open": _num(parts[5]),
        "high": high,
        "low": low,
        "volume": _num(parts[6]),
        "amount": _num(parts[37]) if len(parts) > 37 else None,
        "change": change,
        "pct_change": pct,
        "as_of": parts[30] if len(parts) > 30 and parts[30] else None,
        "status": "ok",
    }


def _fetch_eastmoney(qlib_symbol: str) -> dict[str, Any] | None:
    instrument = to_instrument(qlib_symbol)
    url = _EM_URL.format(secid=secid(instrument))
    data = _http_json(url, "https://quote.eastmoney.com/", retries=3, timeout=10.0)
    if not data:
        return None
    qt = (data.get("data") or {}) if isinstance(data, dict) else {}
    if not qt:
        return None

    price = _num(qt.get("f43"))
    if price is None:
        return None

    prev_close = _num(qt.get("f60"))
    change = _num(qt.get("f169"))
    pct = _num(qt.get("f170"))

    return {
        "source": "eastmoney",
        "symbol": qlib_symbol,
        "name": qt.get("f58"),
        "code": qt.get("f57") or to_digits(qlib_symbol),
        "price": price,
        "prev_close": prev_close,
        "open": _num(qt.get("f46")),
        "high": _num(qt.get("f44")),
        "low": _num(qt.get("f45")),
        "volume": _num(qt.get("f47")),
        "amount": _num(qt.get("f48")),
        "change": change,
        "pct_change": pct,
        "as_of": None,
        "status": "ok",
    }


def fetch_quote_sync(symbol: str) -> dict[str, Any]:
    qlib_symbol = normalize_symbol(symbol)
    for fetcher in (_fetch_tencent, _fetch_eastmoney):
        payload = fetcher(qlib_symbol)
        if payload:
            return payload
    return {
        "source": "unavailable",
        "symbol": qlib_symbol,
        "status": "unavailable",
        "error": "实时行情获取失败（腾讯/东财均不可用）",
    }


async def fetch_quote(symbol: str) -> dict[str, Any]:
    return await run_sync(fetch_quote_sync, symbol, timeout_s=12.0)
