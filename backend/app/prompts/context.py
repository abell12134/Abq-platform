from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from app.models.analysis import PathKind, Realm
from app.models.pipeline import PipelineReports

_SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass
class PromptContext:
    path_kind: PathKind = "single"
    realm: Realm = "a-share"
    symbol: str | None = None
    company_name: str | None = None
    focus: str | None = None
    as_of: str | None = None
    model: str = ""
    snapshot_summary: str | None = None
    snapshot_findings: list[str] = field(default_factory=list)
    carried_output_refs: list[str] = field(default_factory=list)
    reports: PipelineReports | None = None
    debate_history: str = ""
    memory_hints: list[str] = field(default_factory=list)

    def vars(self) -> dict[str, str]:
        focus = (self.focus or "").strip() or "（无侧重，按标准链路）"
        symbol = self.symbol or "（未指定）"
        company = (self.company_name or "").strip() or symbol
        as_of = self.as_of or datetime.now(_SHANGHAI).strftime("%Y-%m-%d")
        return {
            "model": self.model,
            "as_of": as_of,
            "realm": self.realm,
            "symbol": symbol,
            "company_name": company,
            "focus": focus,
            "path_kind": self.path_kind,
        }
