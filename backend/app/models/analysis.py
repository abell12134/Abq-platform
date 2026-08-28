from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

PathStatus = Literal["running", "done", "error"]
PathKind = Literal["market", "single", "portfolio"]
Realm = Literal["a-share", "etf"]
ModelTier = Literal["primary", "local"]


class LlmRef(BaseModel):
    tier: ModelTier
    provider: str
    model: str


class ToolCall(BaseModel):
    id: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    output: str | None = None
    output_ref: str | None = None
    status: Literal["ok", "error", "running"] = "ok"
    suggested_action: str | None = None


class AnalysisStep(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    agent: str
    role: Literal["user", "assistant", "tool", "agent", "compact"] = "assistant"
    thought: str = ""
    result: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    llm: LlmRef | None = None
    ts: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class AnalyzeRequest(BaseModel):
    message: str
    session_id: str | None = None
    kind: PathKind = "single"
    realm: Realm = "a-share"
    target: str | None = None
    focus: str | None = None
    agent_ids: list[str] | None = None
    prompt_id: str | None = None
    primary_model: str | None = None
    enable_debate: bool = True
    debate_rounds: int = 1
    force_full: bool = False


class AnalysisPathIndexEntry(BaseModel):
    id: str
    title: str
    kind: PathKind
    realm: Realm
    status: PathStatus
    created: str
    updated: str
    target: str | None = None
    focus: str | None = None
    symbols: list[str] = Field(default_factory=list)
    judge_stance: str | None = None
    judge_one_liner: str | None = None
    data_as_of: str | None = None
    tags: list[str] = Field(default_factory=list)


class SseEvent(BaseModel):
    type: Literal["step", "token", "compaction", "phase", "error", "done", "reports", "memory"]
    step: AnalysisStep | None = None
    path_id: str | None = None
    step_id: str | None = None
    agent: str | None = None
    delta: str | None = None
    phase: str | None = None
    label: str | None = None
    snapshot: dict[str, Any] | None = None
    reports: dict[str, Any] | None = None
    message: str | None = None
