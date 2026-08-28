"""Market breadth and sector pulse (East Money). Used by market pipeline."""

from __future__ import annotations

import logging
from typing import Any

from app.data.market_quotes import _http_json

log = logging.getLogger(__name__)

_EM_HOST = "https://push2.eastmoney.com"
_BREADTH_URL = (
    f"{_EM_HOST}/api/qt/ulist.np/get?fltt=2&secids=1.000001,0.399001,0.399006"
    "&fields=f2,f3,f4,f12,f14,f104,f105,f106"
)
_SECTOR_URL = (
    f"{_EM_HOST}/api/qt/clist/get?pn=1&pz=15&po=1&np=1&fltt=2&invt=2&fid=f3"
    "&fs=m:90+t:2&fields=f12,f14,f2,f3,f62,f184"
)
_EMOTION_URL = (
    "https://push2ex.eastmoney.com/getTopicZTPool?ut=7eea3edcaed734bea9cbfc24409ed989"
    "&dpt=wz.ztzt&Pageindex=0&pagesize=200&sort=fbt:asc"
)


def _num(v: Any, default: float | None = None) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and v.strip() not in ("", "-"):
        try:
            return float(v)
        except ValueError:
            return default
    return default


def _int(v: Any) -> int | None:
    n = _num(v)
    if n is None:
        return None
    return int(n)


async def fetch_market_breadth() -> dict[str, Any]:
    """全市场宽度：沪/深/创业板涨跌家数 + 主要指数 + 涨停池规模。"""
    indices: list[dict[str, Any]] = []
    advance = 0
    decline = 0
    flat = 0
    breadth_parts: list[dict[str, Any]] = []

    j = _http_json(_BREADTH_URL, "https://quote.eastmoney.com/", retries=3, timeout=10.0)
    if j and j.get("data") and j["data"].get("diff"):
        for row in j["data"]["diff"]:
            code = str(row.get("f12") or "")
            up = _int(row.get("f104"))
            down = _int(row.get("f105"))
            unchanged = _int(row.get("f106"))
            indices.append(
                {
                    "code": code,
                    "name": row.get("f14"),
                    "price": _num(row.get("f2")),
                    "pct_change": _num(row.get("f3")),
                    "change": _num(row.get("f4")),
                    "advance": up,
                    "decline": down,
                    "unchanged": unchanged,
                }
            )
            if up is not None:
                advance += up
            if down is not None:
                decline += down
            if unchanged is not None:
                flat += unchanged
            if up is not None and down is not None:
                breadth_parts.append(
                    {
                        "code": code,
                        "name": row.get("f14"),
                        "advance": up,
                        "decline": down,
                        "unchanged": unchanged,
                    }
                )

    limit_up = 0
    zt = _http_json(_EMOTION_URL, "https://quote.eastmoney.com/", retries=2, timeout=10.0)
    if zt and isinstance(zt.get("data"), dict):
        pool = zt["data"].get("pool") or []
        limit_up = len(pool) if isinstance(pool, list) else 0

    total = advance + decline + flat
    advance_ratio = round(advance / total, 4) if total > 0 else None

    return {
        "status": "ok" if indices and total > 0 else ("partial" if indices else "unavailable"),
        "source": "eastmoney",
        "indices": indices,
        "advance": advance if total > 0 else None,
        "decline": decline if total > 0 else None,
        "unchanged": flat if total > 0 else None,
        "advance_ratio": advance_ratio,
        "limit_up_count": limit_up,
        "by_exchange": breadth_parts,
        "note": "涨跌家数来自上证/深证/创业板指数行情字段 f104/f105/f106 汇总。",
    }


async def fetch_sector_pulse(*, limit: int = 12, theme_hint: str = "") -> dict[str, Any]:
    """行业板块涨跌幅排行（脉冲）。"""
    url = _SECTOR_URL.replace("pz=15", f"pz={max(5, min(limit, 30))}")
    j = _http_json(url, "https://quote.eastmoney.com/", retries=3, timeout=10.0)
    sectors: list[dict[str, Any]] = []
    if j and j.get("data") and j["data"].get("diff"):
        for row in j["data"]["diff"]:
            name = str(row.get("f14") or "")
            sectors.append(
                {
                    "code": row.get("f12"),
                    "name": name,
                    "price": _num(row.get("f2")),
                    "pct_change": _num(row.get("f3")),
                    "net_inflow": _num(row.get("f62")),
                    "leader": row.get("f184"),
                }
            )

    focus_matches: list[dict[str, Any]] = []
    hint = (theme_hint or "").strip().lower()
    if hint and sectors:
        for s in sectors:
            name = str(s.get("name") or "").lower()
            if hint in name or any(part in name for part in hint.split() if len(part) >= 2):
                focus_matches.append(s)

    top_gainers = sorted(
        [s for s in sectors if isinstance(s.get("pct_change"), (int, float))],
        key=lambda x: float(x["pct_change"]),
        reverse=True,
    )[:6]
    top_losers = sorted(
        [s for s in sectors if isinstance(s.get("pct_change"), (int, float))],
        key=lambda x: float(x["pct_change"]),
    )[:6]

    status = "ok" if sectors else "unavailable"
    return {
        "status": status,
        "source": "eastmoney",
        "sectors": sectors,
        "top_gainers": top_gainers,
        "top_losers": top_losers,
        "focus_matches": focus_matches,
        "theme_hint": theme_hint or None,
    }
