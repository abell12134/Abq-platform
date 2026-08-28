"""远程日 K 接入（移植自 abq quant/webapp/quotes.py）。

优先级：腾讯 → 东财；失败时由 baostock 按日期区间补洞。
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

EM_PATH = (
    "/api/qt/stock/kline/get?secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
    "&fields2=f51,f52,f53,f54,f55,f56,f57&klt={klt}&fqt={fqt}&end={end}&lmt={lmt}"
)
EM_HOSTS = ("https://push2his.eastmoney.com", "http://push2his.eastmoney.com")
TX_FQ_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={param}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 abq-lab"
_EM_RETRY = 4
_EM_TIMEOUT = 12.0
_TX_RETRY = 3
_TX_TIMEOUT = 10.0

_cache: dict[str, tuple[float, list[dict]]] = {}
_TTL = 60.0


def to_instrument(qlib_symbol: str) -> str:
    """sh600519 → SH600519"""
    s = qlib_symbol.lower()
    return s[:2].upper() + s[2:]


def secid(instrument: str) -> str:
    mkt = instrument[:2].upper()
    code = instrument[2:]
    market = "1" if mkt == "SH" else "0"
    return f"{market}.{code}"


def _tx_symbol(instrument: str) -> str:
    return instrument[:2].lower() + instrument[2:]


def _tx_adjust(fqt: int) -> str:
    return {0: "", 1: "qfq", 2: "hfq"}.get(fqt, "qfq")


def _tx_kline_key(period: str, adjust: str) -> str:
    if adjust:
        return f"{adjust}{period}"
    return period


def _tx_num(v: Any, default: float = 0.0) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and v.strip():
        try:
            return float(v)
        except ValueError:
            return default
    return default


def _http_json(url: str, referer: str, retries: int, timeout: float) -> dict | None:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Referer": referer,
            "Connection": "close",
            "Accept": "application/json",
        },
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            log.debug("HTTP failed attempt=%s url=%s err=%s", attempt + 1, url[:96], exc)
            time.sleep(0.3 * (attempt + 1))
    return None


def _parse_tx_rows(rows: list) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        if not row or len(row) < 6:
            continue
        date = str(row[0])
        if len(date) == 8 and date.isdigit():
            date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
        out.append(
            {
                "date": date,
                "open": _tx_num(row[1]),
                "close": _tx_num(row[2]),
                "high": _tx_num(row[3]),
                "low": _tx_num(row[4]),
                "volume": _tx_num(row[5]),
                "amount": _tx_num(row[6]) if len(row) > 6 else 0.0,
            }
        )
    return out


def _fetch_tx_once(instrument: str, lmt: int, fqt: int = 1) -> list[dict] | None:
    symbol = _tx_symbol(instrument)
    param = f"{symbol},day,,,{lmt},{_tx_adjust(fqt)}"
    j = _http_json(TX_FQ_URL.format(param=param), "https://gu.qq.com/", _TX_RETRY, _TX_TIMEOUT)
    if not j:
        return None
    data = j.get("data") or {}
    block = data.get(symbol)
    if not block:
        return None
    key = _tx_kline_key("day", _tx_adjust(fqt))
    rows = block.get(key) or block.get("day") or block.get("qfqday")
    if not rows:
        return None
    return _parse_tx_rows(rows)


def _parse_em_klines(j: dict) -> list[dict] | None:
    data = j.get("data")
    if not data or not data.get("klines"):
        return None
    rows: list[dict] = []
    for ln in data["klines"]:
        parts = ln.split(",")
        rows.append(
            {
                "date": parts[0],
                "open": float(parts[1]),
                "close": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "volume": float(parts[5]),
                "amount": float(parts[6]) if len(parts) > 6 else 0.0,
            }
        )
    return rows


def _fetch_em_once(instrument: str, lmt: int, fqt: int = 1) -> list[dict] | None:
    end = dt.date.today().strftime("%Y%m%d")
    path = EM_PATH.format(secid=secid(instrument), klt=101, lmt=lmt, fqt=fqt, end=end)
    for host in EM_HOSTS:
        j = _http_json(host + path, "https://quote.eastmoney.com/", _EM_RETRY, _EM_TIMEOUT)
        if j is None:
            continue
        rows = _parse_em_klines(j)
        if rows:
            return rows
    return None


def fetch_remote_bars(instrument: str, *, limit: int = 120, fqt: int = 1) -> tuple[list[dict], str] | None:
    """同步拉远程日 K，返回 (bars, source)。"""
    cache_key = f"{instrument}:{limit}:{fqt}"
    now = time.time()
    cached = _cache.get(cache_key)
    if cached and now - cached[0] < _TTL:
        return cached[1], "cache"

    for fetcher, source in ((_fetch_tx_once, "tencent"), (_fetch_em_once, "eastmoney")):
        for lmt in (limit, min(limit, 60), min(limit, 15), 10):
            try:
                rows = fetcher(instrument, lmt, fqt)
            except Exception as exc:
                log.debug("%s fetch failed lmt=%s: %s", source, lmt, exc)
                rows = None
            if rows and len(rows) >= min(lmt, 5):
                _cache[cache_key] = (now, rows)
                return rows, source
    return None
