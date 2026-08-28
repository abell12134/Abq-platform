from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.data.qlib_store import normalize_symbol
from app.factors.universe import fetch_universe_symbols
from app.graph.models import GraphNode
from app.graph.store import (
    company_node_id,
    graph_store,
    index_node_id,
    news_node_id,
    sector_node_id,
    stock_node_id,
)

log = logging.getLogger(__name__)

CSI300_INDEX_CODE = "csi300"
CSI300_DISPLAY = "沪深300"


def _parse_sample_symbols(raw: str) -> list[str]:
    out: list[str] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(normalize_symbol(part))
        except ValueError:
            log.warning("skip invalid sample symbol: %s", part)
    return out


async def bootstrap_csi300_skeleton(*, max_symbols: int = 300) -> dict[str, Any]:
    """Create Index + Stock nodes from cached CSI300 list (one universe fetch at most)."""
    graph_store.ensure()
    symbols, meta = await fetch_universe_symbols("csi300", max_symbols=max_symbols)
    index_id = index_node_id(CSI300_INDEX_CODE)
    graph_store.upsert_node(
        GraphNode(
            id=index_id,
            type="Index",
            label=CSI300_DISPLAY,
            props={
                "code": CSI300_INDEX_CODE,
                "index_code": meta.get("index_code"),
                "constituent_count": len(symbols),
                "source": meta.get("source"),
            },
        )
    )

    linked = 0
    for sym in symbols:
        sid = stock_node_id(sym)
        graph_store.upsert_node(
            GraphNode(
                id=sid,
                type="Stock",
                label=sym,
                props={"symbol": sym, "universe": CSI300_INDEX_CODE},
            )
        )
        graph_store.link_edge(sid, index_id, "IN_INDEX", props={"universe": CSI300_INDEX_CODE})
        linked += 1

    now = datetime.now(UTC).isoformat()
    graph_store.set_meta("last_bootstrap_at", now)
    graph_store.set_meta("csi300_count", str(len(symbols)))
    return {
        "status": "ok",
        "index": CSI300_INDEX_CODE,
        "stocks": len(symbols),
        "edges_in_index": linked,
        "universe_source": meta.get("source"),
        "bootstrapped_at": now,
    }


def _sector_from_company_info(info: dict[str, Any]) -> str | None:
    for key in ("所属行业", "行业", "证监会行业", "申万行业"):
        val = info.get(key)
        if val and str(val).strip():
            return str(val).strip()
    return None


def _company_name(info: dict[str, Any], fallback: str) -> str:
    for key in ("A股简称", "公司名称", "证券简称", "name"):
        val = info.get(key)
        if val and str(val).strip():
            return str(val).strip()
    return fallback


def _headline_key(headline: dict[str, Any]) -> str:
    title = str(headline.get("新闻标题") or headline.get("title") or "").strip()
    ts = str(headline.get("发布时间") or headline.get("time") or "")[:10]
    raw = f"{title}|{ts}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def apply_fundamentals_to_graph(symbol: str, payload: dict[str, Any]) -> dict[str, Any]:
    sym = normalize_symbol(symbol)
    sid = stock_node_id(sym)
    info = payload.get("company_info") or {}
    name = _company_name(info, sym)
    sector_name = _sector_from_company_info(info)

    graph_store.upsert_node(
        GraphNode(
            id=sid,
            type="Stock",
            label=name,
            props={
                "symbol": sym,
                "name": name,
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )
    )

    cid = company_node_id(sym)
    graph_store.upsert_node(
        GraphNode(
            id=cid,
            type="Company",
            label=name,
            props={
                "symbol": sym,
                "company_info": {k: str(v) for k, v in list(info.items())[:30]},
            },
        )
    )
    graph_store.link_edge(sid, cid, "LISTED_AS")

    sector_linked: str | None = None
    if sector_name:
        sec_id = sector_node_id(sector_name)
        graph_store.upsert_node(
            GraphNode(
                id=sec_id,
                type="Sector",
                label=sector_name,
                props={"name": sector_name},
            )
        )
        graph_store.link_edge(sid, sec_id, "IN_SECTOR")
        sector_linked = sector_name

    return {"name": name, "sector": sector_linked}


def apply_sentiment_to_graph(symbol: str, payload: dict[str, Any], *, limit: int = 5) -> int:
    sym = normalize_symbol(symbol)
    sid = stock_node_id(sym)
    if not graph_store.get_node(sid):
        graph_store.upsert_node(
            GraphNode(id=sid, type="Stock", label=sym, props={"symbol": sym})
        )

    headlines = (payload.get("headlines") or [])[:limit]
    linked = 0
    for row in headlines:
        title = str(row.get("新闻标题") or row.get("title") or "").strip()
        if not title:
            continue
        key = _headline_key(row)
        nid = news_node_id(key)
        url = row.get("新闻链接") or row.get("url")
        graph_store.upsert_node(
            GraphNode(
                id=nid,
                type="News",
                label=title[:120],
                props={
                    "title": title,
                    "url": url,
                    "time": row.get("发布时间") or row.get("time"),
                    "source": payload.get("source") or "akshare",
                },
            )
        )
        graph_store.link_edge(nid, sid, "MENTIONS")
        linked += 1
    return linked


def _announcement_key(row: dict[str, Any]) -> str:
    title = str(row.get("公告标题") or row.get("title") or "").strip()
    date = str(row.get("公告日期") or row.get("date") or "")[:10]
    code = str(row.get("编码") or row.get("art_code") or "")
    raw = f"{code}|{title}|{date}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def event_node_id(key: str) -> str:
    return f"event:{key[:80]}"


def apply_announcements_to_graph(symbol: str, payload: dict[str, Any], *, limit: int = 8) -> int:
    sym = normalize_symbol(symbol)
    sid = stock_node_id(sym)
    if not graph_store.get_node(sid):
        graph_store.upsert_node(
            GraphNode(id=sid, type="Stock", label=sym, props={"symbol": sym})
        )

    items = (payload.get("announcements") or [])[:limit]
    linked = 0
    for row in items:
        title = str(row.get("公告标题") or row.get("title") or "").strip()
        if not title:
            continue
        key = _announcement_key(row)
        eid = event_node_id(key)
        graph_store.upsert_node(
            GraphNode(
                id=eid,
                type="Event",
                label=title[:120],
                props={
                    "title": title,
                    "event_type": "announcement",
                    "notice_type": row.get("公告类型"),
                    "date": str(row.get("公告日期") or ""),
                    "url": row.get("网址") or row.get("url"),
                    "source": payload.get("source") or "akshare",
                },
            )
        )
        graph_store.link_edge(eid, sid, "ABOUT")
        linked += 1
    return linked


def default_sample_symbols() -> list[str]:
    from app.config import settings

    return _parse_sample_symbols(settings.graph_sync_sample_symbols)
