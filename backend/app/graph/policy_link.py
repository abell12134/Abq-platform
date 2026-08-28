from __future__ import annotations

from datetime import UTC, datetime

from app.config import settings
from app.graph.models import GraphNode
from app.graph.store import graph_store, sector_node_id, stock_node_id


def policy_node_id(doc_id: str) -> str:
    return f"policy:{doc_id}"


def link_policy_document(
    *,
    doc_id: str,
    title: str,
    url: str | None = None,
    symbol: str | None = None,
    theme: str | None = None,
    issuer: str | None = None,
) -> None:
    if not settings.graph_enabled:
        return

    graph_store.ensure()
    pid = policy_node_id(doc_id)
    graph_store.upsert_node(
        GraphNode(
            id=pid,
            type="Policy",
            label=title[:120],
            props={
                "doc_id": doc_id,
                "title": title,
                "url": url,
                "issuer": issuer,
                "linked_at": datetime.now(UTC).isoformat(),
            },
        )
    )

    if symbol:
        sym = symbol.strip().lower()
        sid = stock_node_id(sym)
        if not graph_store.get_node(sid):
            graph_store.upsert_node(
                GraphNode(
                    id=sid,
                    type="Stock",
                    label=sym,
                    props={"symbol": sym},
                )
            )
        graph_store.link_edge(
            pid,
            sid,
            "AFFECTS",
            props={"confidence": 0.85, "source": "ingest", "symbol": sym},
        )

    if theme:
        sec_id = sector_node_id(theme)
        graph_store.upsert_node(
            GraphNode(
                id=sec_id,
                type="Sector",
                label=theme,
                props={"name": theme},
            )
        )
        graph_store.link_edge(
            pid,
            sec_id,
            "AFFECTS",
            props={"confidence": 0.8, "source": "ingest", "theme": theme},
        )
