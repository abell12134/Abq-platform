from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PromptCategory = Literal["agent-persona", "analysis", "extraction", "summary"]
ModelTier = Literal["primary", "local"]
AgentStatus = Literal["active", "draft"]


class PromptRecord(BaseModel):
    id: str
    category: PromptCategory = "analysis"
    persona: str = ""
    instructions: str = ""
    complete: bool = False
    builtin: bool = False


class PromptCreate(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    category: PromptCategory = "analysis"
    persona: str = ""
    instructions: str = ""
    complete: bool = False


class PromptUpdate(BaseModel):
    category: PromptCategory | None = None
    persona: str | None = None
    instructions: str | None = None
    complete: bool | None = None


class AgentRecord(BaseModel):
    id: str
    name: str
    model_tier: ModelTier = "primary"
    tools: list[str] = Field(default_factory=list)
    prompt_id: str
    status: AgentStatus = "active"
    builtin: bool = False


class AgentDetail(AgentRecord):
    persona: str = ""
    instructions: str = ""


class AgentCreate(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=80)
    model_tier: ModelTier = "primary"
    tools: list[str] = Field(default_factory=list)
    prompt_id: str = Field(min_length=1, max_length=64)
    status: AgentStatus = "active"


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    model_tier: ModelTier | None = None
    tools: list[str] | None = None
    prompt_id: str | None = Field(default=None, min_length=1, max_length=64)
    status: AgentStatus | None = None


class ToolRecord(BaseModel):
    id: str
    name: str
    description: str
    guidance: str = ""
