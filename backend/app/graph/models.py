from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

NodeType = Literal[
    "Index",
    "Stock",
    "Company",
    "Sector",
    "News",
    "Policy",
    "Macro",
    "Digest",
    "Event",
    "MarketSnapshot",
]
EdgeType = Literal[
    "LISTED_AS",
    "IN_INDEX",
    "IN_SECTOR",
    "SUBSECTOR_OF",
    "AFFECTS",
    "MENTIONS",
    "ABOUT",
    "IMPACTS",
    "SUMMARIZES",
    "SUPPLIES_TO",
    "COMPETES_WITH",
]


class GraphNode(BaseModel):
    id: str
    type: NodeType
    label: str = ""
    props: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    id: str
    src: str
    dst: str
    type: EdgeType
    props: dict[str, Any] = Field(default_factory=dict)


class SubgraphResult(BaseModel):
    center: str
    hops: int
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


class GraphStats(BaseModel):
    node_count: int = 0
    edge_count: int = 0
    nodes_by_type: dict[str, int] = Field(default_factory=dict)
    last_bootstrap_at: str | None = None
    sample_symbols: list[str] = Field(default_factory=list)


class SyncStockResult(BaseModel):
    symbol: str
    status: str
    skipped: bool = False
    reason: str = ""
    sentiment_count: int = 0
    announcement_count: int = 0
    news_linked: int = 0
    events_linked: int = 0
    company_name: str | None = None
    sector: str | None = None


class RollupResult(BaseModel):
    status: str
    period: str
    scope: str
    key: str
    digest_id: str = ""
    event_count: int = 0
    summary: str = ""
    used_llm: bool = False
    skipped: bool = False


class SyncBatchResult(BaseModel):
    status: str
    requested: int
    synced: int
    skipped: int
    errors: int
    min_interval_s: float
    cooldown_hours: float
    results: list[SyncStockResult] = Field(default_factory=list)
    summary: str = ""
