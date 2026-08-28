from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Realm = Literal["a-share", "etf"]


class PortfolioMember(BaseModel):
    symbol: str
    added_at: str = ""
    note: str = ""


class PortfolioRecord(BaseModel):
    id: str
    name: str
    realm: Realm = "a-share"
    members: list[PortfolioMember] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


class PortfolioCreate(BaseModel):
    id: str = Field(min_length=1, max_length=48)
    name: str = Field(min_length=1, max_length=80)
    realm: Realm = "a-share"
    members: list[PortfolioMember] = Field(default_factory=list)


class PortfolioUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    members: list[PortfolioMember] | None = None


class PortfolioMemberSnapshot(BaseModel):
    symbol: str
    name: str | None = None
    note: str | None = None
    price: float | None = None
    pct_change: float | None = None
    chg_5d: float | None = None
    chg_20d: float | None = None


class PortfolioSnapshot(BaseModel):
    portfolio_id: str
    name: str
    realm: Realm = "a-share"
    as_of: str
    member_count: int
    equal_weight_pct_1d: float | None = None
    equal_weight_chg_5d: float | None = None
    equal_weight_chg_20d: float | None = None
    members: list[PortfolioMemberSnapshot] = Field(default_factory=list)
    best_today: PortfolioMemberSnapshot | None = None
    worst_today: PortfolioMemberSnapshot | None = None


class TrackRecord(BaseModel):
    id: str
    date: str
    recorded_at: str
    equal_weight_pct_1d: float | None = None
    equal_weight_chg_5d: float | None = None
    member_count: int = 0
    best_symbol: str | None = None
    best_name: str | None = None
    best_pct: float | None = None
    worst_symbol: str | None = None
    worst_name: str | None = None
    worst_pct: float | None = None
    note: str | None = None
    path_id: str | None = None


class TrackRecordCreate(BaseModel):
    note: str | None = None
    path_id: str | None = None
