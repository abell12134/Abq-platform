from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

KnowledgeType = Literal[
    "sentiment",
    "breadth",
    "sector_pulse",
    "analysis_ref",
    "announcement",
    "northbound",
    "margin",
    "macro",
    "market_snapshot",
]


class KnowledgeEvent(BaseModel):
    id: str
    ts: str
    type: KnowledgeType
    source: str = "akshare"
    symbol: str | None = None
    theme: str | None = None
    path_id: str | None = None
    payload_hash: str = ""
    headlines: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""


class KnowledgeDeltaResult(BaseModel):
    status: str
    type: str
    symbol: str | None = None
    since_days: int = 7
    new_items: list[str] = Field(default_factory=list)
    removed_items: list[str] = Field(default_factory=list)
    metric_changes: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    event_count: int = 0
