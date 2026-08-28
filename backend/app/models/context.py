from __future__ import annotations

from pydantic import BaseModel, Field


class KeyFinding(BaseModel):
    step_id: str = ""
    agent: str = ""
    text: str


class ContextSnapshot(BaseModel):
    summary: str = ""
    key_findings: list[KeyFinding] = Field(default_factory=list)
    carried_outputs: list[str] = Field(default_factory=list)
    total_raw_tokens: int = 0
    total_compressed_tokens: int = 0

    def finding_lines(self) -> list[str]:
        return [f"[{f.step_id}] {f.agent}: {f.text}" for f in self.key_findings]
