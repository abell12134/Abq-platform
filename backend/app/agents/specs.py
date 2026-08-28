from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.llm.router import ModelTier


@dataclass
class AgentSpec:
    id: str
    name: str
    model_tier: ModelTier
    tool_names: list[str] = field(default_factory=list)
    persona: str = ""
    instructions: str = ""
    prompt_id: str = ""


def extract_symbol(text: str) -> str | None:
    m = re.search(r"\b((?:sh|sz|bj)?\d{6})\b", text, re.I)
    if m:
        return m.group(1)
    m = re.search(r"(\d{6})", text)
    return m.group(1) if m else None


def extract_symbols(text: str, *, limit: int = 12) -> list[str]:
    found = re.findall(r"\b((?:sh|sz|bj)?\d{6})\b", text, re.I)
    if not found:
        found = re.findall(r"\b(\d{6})\b", text)
    out: list[str] = []
    for sym in found:
        s = sym.lower()
        if s not in out:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def build_supervisor_agent() -> AgentSpec:
    from app.prompts.loader import load_agent

    return load_agent("supervisor")
