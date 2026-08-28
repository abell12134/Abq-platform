from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from app.config import settings
from app.graph.models import GraphEdge, GraphNode, GraphStats, SubgraphResult


def _node_id(node_type: str, key: str) -> str:
    return f"{node_type.lower()}:{key}"


def stock_node_id(symbol: str) -> str:
    return _node_id("stock", symbol.lower())


def company_node_id(symbol: str) -> str:
    return _node_id("company", symbol.lower())


def sector_node_id(name: str) -> str:
    slug = name.strip().replace("/", "_").replace(" ", "_")[:60]
    return _node_id("sector", slug)


def index_node_id(code: str) -> str:
    return _node_id("index", code.lower())


def news_node_id(key: str) -> str:
    return _node_id("news", key[:80])


def macro_node_id(name: str, period: str) -> str:
    slug = f"{name}_{period}".replace("/", "_").replace(" ", "_")[:60]
    return _node_id("macro", slug)


def market_snapshot_node_id(day: str) -> str:
    return _node_id("marketsnapshot", day.replace("/", "-")[:20])


def digest_node_id_from_key(digest_id: str) -> str:
    return digest_id if digest_id.startswith("digest:") else f"digest:{digest_id}"


class GraphStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or settings.graph_db_path

    def ensure(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    label TEXT NOT NULL DEFAULT '',
                    props TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS edges (
                    id TEXT PRIMARY KEY,
                    src TEXT NOT NULL,
                    dst TEXT NOT NULL,
                    type TEXT NOT NULL,
                    props TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
                CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
                CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sync_log (
                    symbol TEXT PRIMARY KEY,
                    last_sync_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT ''
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def upsert_node(self, node: GraphNode) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO nodes (id, type, label, props)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    type = excluded.type,
                    label = excluded.label,
                    props = excluded.props
                """,
                (node.id, node.type, node.label, json.dumps(node.props, ensure_ascii=False)),
            )
            conn.commit()

    def upsert_edge(self, edge: GraphEdge) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO edges (id, src, dst, type, props)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    src = excluded.src,
                    dst = excluded.dst,
                    type = excluded.type,
                    props = excluded.props
                """,
                (
                    edge.id,
                    edge.src,
                    edge.dst,
                    edge.type,
                    json.dumps(edge.props, ensure_ascii=False),
                ),
            )
            conn.commit()

    def get_node(self, node_id: str) -> GraphNode | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if not row:
            return None
        return GraphNode(
            id=row["id"],
            type=row["type"],
            label=row["label"] or "",
            props=json.loads(row["props"] or "{}"),
        )

    def linked_neighbor_ids(
        self,
        node_id: str,
        *,
        edge_type: str | None = None,
    ) -> list[str]:
        with self._connect() as conn:
            if edge_type:
                rows = conn.execute(
                    """
                    SELECT dst AS nid FROM edges WHERE src = ? AND type = ?
                    UNION
                    SELECT src AS nid FROM edges WHERE dst = ? AND type = ?
                    """,
                    (node_id, edge_type, node_id, edge_type),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT dst AS nid FROM edges WHERE src = ?
                    UNION
                    SELECT src AS nid FROM edges WHERE dst = ?
                    """,
                    (node_id, node_id),
                ).fetchall()
        out = [str(r["nid"]) for r in rows if str(r["nid"]) != node_id]
        return list(dict.fromkeys(out))

    def stocks_in_sector(self, sector_name: str) -> list[str]:
        sec_id = sector_node_id(sector_name)
        ids = self.linked_neighbor_ids(sec_id, edge_type="IN_SECTOR")
        symbols: list[str] = []
        for nid in ids:
            if nid.startswith("stock:"):
                symbols.append(nid.split(":", 1)[1])
        return symbols

    def list_sector_names(self, limit: int = 80) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT label FROM nodes WHERE type = 'Sector' ORDER BY label LIMIT ?",
                (max(1, limit),),
            ).fetchall()
        return [str(r["label"]) for r in rows if r["label"]]

    def find_stock_id_by_label(self, fragment: str) -> str | None:
        frag = fragment.strip()
        if not frag:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM nodes WHERE type = 'Stock' AND label LIKE ? LIMIT 1",
                (f"%{frag[:30]}%",),
            ).fetchone()
        return str(row["id"]) if row else None

    def resolve_center(self, center: str) -> str:
        """Accept symbol (sh600519) or full node id (stock:sh600519)."""
        c = center.strip().lower()
        if ":" in c:
            return c
        sym = c
        nid = stock_node_id(sym)
        if self.get_node(nid):
            return nid
        return nid

    def subgraph(self, center: str, *, hops: int = 1, max_nodes: int = 80) -> SubgraphResult:
        hops = max(1, min(hops, 3))
        max_nodes = max(10, min(max_nodes, 200))
        center_id = self.resolve_center(center)
        if not self.get_node(center_id):
            return SubgraphResult(center=center_id, hops=hops)

        frontier = {center_id}
        seen_nodes = {center_id}
        seen_edges: set[str] = set()
        edges_out: list[GraphEdge] = []

        with self._connect() as conn:
            for _ in range(hops):
                if not frontier or len(seen_nodes) >= max_nodes:
                    break
                placeholders = ",".join("?" for _ in frontier)
                rows = conn.execute(
                    f"""
                    SELECT * FROM edges
                    WHERE src IN ({placeholders}) OR dst IN ({placeholders})
                    """,
                    (*frontier, *frontier),
                ).fetchall()
                next_frontier: set[str] = set()
                for row in rows:
                    eid = row["id"]
                    if eid in seen_edges:
                        continue
                    seen_edges.add(eid)
                    edges_out.append(
                        GraphEdge(
                            id=eid,
                            src=row["src"],
                            dst=row["dst"],
                            type=row["type"],
                            props=json.loads(row["props"] or "{}"),
                        )
                    )
                    for nid in (row["src"], row["dst"]):
                        if nid not in seen_nodes and len(seen_nodes) < max_nodes:
                            seen_nodes.add(nid)
                            next_frontier.add(nid)
                frontier = next_frontier

            node_rows = conn.execute(
                f"SELECT * FROM nodes WHERE id IN ({','.join('?' for _ in seen_nodes)})",
                tuple(seen_nodes),
            ).fetchall()

        nodes = [
            GraphNode(
                id=r["id"],
                type=r["type"],
                label=r["label"] or "",
                props=json.loads(r["props"] or "{}"),
            )
            for r in node_rows
        ]
        return SubgraphResult(center=center_id, hops=hops, nodes=nodes, edges=edges_out)

    def stats(self) -> GraphStats:
        with self._connect() as conn:
            node_count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            edge_count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            type_rows = conn.execute(
                "SELECT type, COUNT(*) AS c FROM nodes GROUP BY type"
            ).fetchall()
            bootstrap = conn.execute(
                "SELECT value FROM meta WHERE key = 'last_bootstrap_at'"
            ).fetchone()
            sample = conn.execute(
                "SELECT value FROM meta WHERE key = 'sample_symbols'"
            ).fetchone()
        sample_symbols: list[str] = []
        if sample and sample["value"]:
            try:
                sample_symbols = json.loads(sample["value"])
            except json.JSONDecodeError:
                sample_symbols = []
        return GraphStats(
            node_count=node_count,
            edge_count=edge_count,
            nodes_by_type={r["type"]: r["c"] for r in type_rows},
            last_bootstrap_at=bootstrap["value"] if bootstrap else None,
            sample_symbols=sample_symbols,
        )

    def set_meta(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO meta (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            conn.commit()

    def get_meta(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def get_sync_log(self, symbol: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sync_log WHERE symbol = ?", (symbol.lower(),)
            ).fetchone()
        if not row:
            return None
        return dict(row)

    def set_sync_log(self, symbol: str, *, status: str, message: str = "") -> None:
        from datetime import UTC, datetime

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sync_log (symbol, last_sync_at, status, message)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    last_sync_at = excluded.last_sync_at,
                    status = excluded.status,
                    message = excluded.message
                """,
                (symbol.lower(), datetime.now(UTC).isoformat(), status, message),
            )
            conn.commit()

    def link_edge(
        self,
        src: str,
        dst: str,
        edge_type: str,
        *,
        props: dict[str, Any] | None = None,
    ) -> GraphEdge:
        edge_id = self.edge_id(src, dst, edge_type)
        edge = GraphEdge(
            id=edge_id,
            src=src,
            dst=dst,
            type=edge_type,  # type: ignore[arg-type]
            props=props or {},
        )
        self.upsert_edge(edge)
        return edge

    @staticmethod
    def edge_id(src: str, dst: str, edge_type: str) -> str:
        raw = f"{src}\0{edge_type}\0{dst}"
        digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return f"edge:{digest}"


graph_store = GraphStore()
