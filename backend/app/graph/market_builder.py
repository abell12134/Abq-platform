from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.graph.models import GraphNode
from app.graph.store import graph_store, index_node_id, macro_node_id, market_snapshot_node_id


def apply_northbound_to_graph(payload: dict[str, Any]) -> str | None:
    metrics = payload.get("metrics") or {}
    if not metrics:
        return None
    day = str(metrics.get("trade_date") or datetime.now(UTC).date())
    mid = macro_node_id("northbound", day)
    graph_store.upsert_node(
        GraphNode(
            id=mid,
            type="Macro",
            label=f"北向 {day}",
            props={"kind": "northbound", "metrics": metrics},
        )
    )
    idx = index_node_id("csi300")
    if graph_store.get_node(idx):
        graph_store.link_edge(mid, idx, "IMPACTS", props={"kind": "northbound"})
    return mid


def apply_margin_to_graph(payload: dict[str, Any]) -> str | None:
    metrics = payload.get("metrics") or {}
    if not metrics:
        return None
    day = str(metrics.get("trade_date") or datetime.now(UTC).date())
    mid = macro_node_id("margin", day)
    graph_store.upsert_node(
        GraphNode(
            id=mid,
            type="Macro",
            label=f"两融 {day}",
            props={"kind": "margin", "metrics": metrics},
        )
    )
    idx = index_node_id("csi300")
    if graph_store.get_node(idx):
        graph_store.link_edge(mid, idx, "IMPACTS", props={"kind": "margin"})
    return mid


def apply_macro_indicators_to_graph(payload: dict[str, Any]) -> int:
    indicators = payload.get("indicators") or []
    linked = 0
    idx = index_node_id("csi300")
    for row in indicators:
        name = str(row.get("name") or "macro")
        period = str(row.get("period") or "")
        mid = macro_node_id(name, period)
        graph_store.upsert_node(
            GraphNode(
                id=mid,
                type="Macro",
                label=f"{name} {period}",
                props=row,
            )
        )
        if graph_store.get_node(idx):
            graph_store.link_edge(mid, idx, "IMPACTS", props={"indicator": name})
        linked += 1
    return linked


def apply_market_snapshot_to_graph(
    *,
    breadth: dict[str, Any] | None = None,
    northbound: dict[str, Any] | None = None,
    margin: dict[str, Any] | None = None,
) -> str:
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    if northbound and (northbound.get("metrics") or {}).get("trade_date"):
        day = str(northbound["metrics"]["trade_date"])[:10]
    sid = market_snapshot_node_id(day)
    metrics: dict[str, Any] = {"as_of": day}
    if breadth:
        metrics["breadth"] = {
            k: breadth.get(k)
            for k in ("advance", "decline", "advance_ratio", "limit_up_count")
            if breadth.get(k) is not None
        }
    if northbound:
        metrics["northbound"] = northbound.get("metrics") or {}
    if margin:
        metrics["margin"] = margin.get("metrics") or {}

    graph_store.upsert_node(
        GraphNode(
            id=sid,
            type="MarketSnapshot",
            label=f"大盘快照 {day}",
            props=metrics,
        )
    )
    idx = index_node_id("csi300")
    if graph_store.get_node(idx):
        graph_store.link_edge(sid, idx, "IMPACTS", props={"scope": "market"})
    return sid
