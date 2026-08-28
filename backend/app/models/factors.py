from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

FactorOrigin = Literal["catalog", "manual", "llm", "gp", "synth"]
FactorStatus = Literal[
    "candidate",
    "rejected",
    "passed_auto",
    "paper_tracking",
    "frozen",
    "retired",
    "live",
]
FactorUniverse = Literal["csi300", "csi500", "market"]
FactorTheme = Literal[
    "momentum",
    "reversal",
    "volume",
    "volatility",
    "quality",
    "value",
    "liquidity",
    "microstructure",
    "sentiment",
    "growth",
    "leverage",
    "market",
]


class FactorRecord(BaseModel):
    id: str
    name: str
    origin: FactorOrigin
    status: FactorStatus = "candidate"
    theme: list[str] = Field(default_factory=list)
    universe: FactorUniverse = "csi300"
    formula: str
    expr: dict[str, Any]
    hypothesis: str = ""
    forward_days: int = 5
    metrics: dict[str, Any] = Field(default_factory=dict)
    reject_reason: str = ""
    builtin: bool = False
    created_at: str = ""
    updated_at: str = ""


class FactorCreate(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=80)
    formula: str = Field(min_length=1, max_length=2000)
    hypothesis: str = ""
    theme: list[str] = Field(default_factory=list)
    universe: FactorUniverse = "csi300"
    origin: FactorOrigin = "manual"


class FactorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    hypothesis: str | None = None
    status: FactorStatus | None = None
    theme: list[str] | None = None
    formula: str | None = Field(default=None, min_length=1, max_length=2000)


class FactorEvalRequest(BaseModel):
    factor_id: str | None = None
    formula: str | None = None
    universe: FactorUniverse | None = None
    symbols: list[str] | None = None
    lookback: int = Field(default=250, ge=40, le=2000)
    use_synthetic: bool = False


class FactorMineLlmRequest(BaseModel):
    universe: FactorUniverse = "csi300"
    rounds: int = Field(default=2, ge=1, le=5)
    k: int = Field(default=3, ge=1, le=6)
    theme_hint: str = Field(default="", max_length=200)
    use_synthetic: bool = True


class FactorMineGpRequest(BaseModel):
    track: Literal["market", "cs"] = "market"
    universe: FactorUniverse = "csi300"
    population: int = Field(default=80, ge=20, le=200)
    generations: int = Field(default=10, ge=3, le=30)
    use_synthetic: bool = True
    lookback: int = Field(default=500, ge=80, le=2000)


class FactorSynthesizeRequest(BaseModel):
    method: Literal["equal", "ic", "ic_ir"] = "equal"
    factor_ids: list[str] = Field(min_length=2, max_length=8)
    id: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, max_length=80)
    hypothesis: str = ""
    universe: FactorUniverse | None = None
    symbols: list[str] | None = None
    lookback: int = Field(default=250, ge=40, le=2000)
    use_synthetic: bool = True
    replace: bool = False


class PaperRevalidateRequest(BaseModel):
    factor_ids: list[str] | None = None
    lookback: int = Field(default=252, ge=60, le=520)


class FactorScreenRequest(BaseModel):
    universe: FactorUniverse = "csi300"
    factor_ids: list[str] = Field(default_factory=list, max_length=12)
    method: Literal["equal", "ic", "ic_ir"] = "ic_ir"
    top_n: int = Field(default=20, ge=1, le=100)
    max_factors: int = Field(default=6, ge=1, le=12)
    max_symbols: int = Field(default=80, ge=20, le=300)
    lookback: int = Field(default=120, ge=40, le=520)
    use_synthetic: bool = False


class FactorScreenApplyRequest(BaseModel):
    portfolio_id: str = Field(default="default", min_length=1, max_length=48)
    symbols: list[str] = Field(min_length=1, max_length=100)
    mode: Literal["merge", "replace"] = "merge"
