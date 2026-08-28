from __future__ import annotations

from pydantic import BaseModel


class AgentReport(BaseModel):
    agent_id: str
    step_id: str
    content: str


class PipelineReports(BaseModel):
    """Structured agent outputs (decoupled from findings strings)."""

    data_summary: str | None = None
    tech: AgentReport | None = None
    fundamental: AgentReport | None = None
    sentiment: AgentReport | None = None
    market: AgentReport | None = None
    portfolio: AgentReport | None = None
    bull: AgentReport | None = None
    bear: AgentReport | None = None
    debate_history: str = ""
    judge: AgentReport | None = None
    factor_summary: str | None = None

    portfolio_summary: str | None = None

    def set_report(self, agent_id: str, step_id: str, content: str) -> None:
        report = AgentReport(agent_id=agent_id, step_id=step_id, content=content.strip())
        if agent_id in ("tech", "fundamental", "sentiment", "market", "portfolio", "bull", "bear", "judge"):
            setattr(self, agent_id, report)

    def merge(self, other: PipelineReports) -> PipelineReports:
        data = self.model_dump()
        for key, val in other.model_dump().items():
            if val is None or val == "" or val == {}:
                continue
            if key == "debate_history" and val:
                prev = data.get("debate_history") or ""
                data["debate_history"] = f"{prev}\n{val}".strip() if prev else val
            else:
                data[key] = val
        return PipelineReports.model_validate(data)

    def to_findings(self) -> list[str]:
        lines: list[str] = []
        if self.data_summary:
            lines.append(f"[data] {self.data_summary[:400]}")
        for field in ("tech", "fundamental", "sentiment", "market", "portfolio", "bull", "bear", "judge"):
            report: AgentReport | None = getattr(self, field)
            if report and report.content:
                preview = report.content[:400] + ("…" if len(report.content) > 400 else "")
                lines.append(f"[{report.step_id}] {report.agent_id}: {preview}")
        return lines

    def reports_markdown(self) -> str:
        parts: list[str] = []
        if self.data_summary:
            parts.append(f"### 数据摘要\n{self.data_summary}")
        if self.factor_summary:
            parts.append(f"### 因子截面\n{self.factor_summary}")
        for title, field in (
            ("技术面", "tech"),
            ("基本面", "fundamental"),
            ("舆情", "sentiment"),
            ("大盘研判", "market"),
            ("组合诊断", "portfolio"),
            ("看多研究员", "bull"),
            ("看空研究员", "bear"),
        ):
            report: AgentReport | None = getattr(self, field)
            if report and report.content:
                parts.append(f"### {title}（step {report.step_id}）\n{report.content}")
        if self.debate_history.strip():
            parts.append(f"### 多空辩论记录\n{self.debate_history.strip()}")
        return "\n\n".join(parts) if parts else "（尚无结构化报告）"
