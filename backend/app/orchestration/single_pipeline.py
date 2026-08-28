from __future__ import annotations

from collections.abc import AsyncIterator

from app.models.analysis import AnalyzeRequest
from app.models.context import ContextSnapshot
from app.models.pipeline import PipelineReports
from app.orchestration import pipeline_phases as phases
from app.orchestration.agent_loop import run_agent
from app.orchestration.graphs.single_ticket import stream_single_ticket_pipeline
from app.orchestration.stream_types import PhaseMarker, StreamItem
from app.persistence.paths import path_store
from app.prompts.loader import load_agent


def has_view_reports(reports: dict | PipelineReports | None) -> bool:
    if not reports:
        return False
    r = reports if isinstance(reports, PipelineReports) else PipelineReports.model_validate(reports)
    return bool(r.tech and r.fundamental and r.sentiment)


async def run_single_followup(
    req: AnalyzeRequest,
    *,
    symbol: str,
    reports_data: dict,
    primary_override: str | None = None,
    prior_snapshot: ContextSnapshot | None = None,
    path_id: str | None = None,
) -> AsyncIterator[StreamItem]:
    """续聊：复用已有三视角报告，仅重跑 judge。"""
    yield PhaseMarker("followup", "基于已有报告续答")
    seed_findings, seed_refs, seed_summary = phases.merge_prior_snapshot(prior_snapshot)
    reports = PipelineReports.model_validate(reports_data)
    findings = seed_findings + reports.to_findings()
    refs = list(seed_refs)
    debate_history = reports.debate_history or ""

    judge_findings, judge_summary = await phases.compact_for_judge(
        findings,
        refs,
        reports,
        seed_summary,
    )
    ctx = phases.build_prompt_ctx(
        req,
        symbol=symbol,
        company_name=None,
        findings=judge_findings,
        refs=refs,
        reports=reports,
        snapshot_summary=judge_summary,
        debate_history=debate_history,
    )
    yield PhaseMarker("judge", "综合研判")
    judge = load_agent("judge")
    task = (
        f"用户追问：{req.message}\n\n"
        f"请结合已有技术/基本面/舆情报告（见上下文）回答追问，并更新综合研判。"
    )
    async for step in run_agent(
        judge,
        user_message=task,
        prompt_ctx=ctx,
        primary_override=primary_override,
    ):
        yield step
        if step.role == "assistant" and step.agent == "judge":
            reports.set_report("judge", step.id, step.result or step.thought)

    if path_id:
        await path_store.save_reports(path_id, reports.model_dump(mode="json"))


async def run_single_pipeline(
    req: AnalyzeRequest,
    *,
    symbol: str,
    primary_override: str | None = None,
    prior_snapshot: ContextSnapshot | None = None,
    path_id: str | None = None,
) -> AsyncIterator[StreamItem]:
    """Single-ticket pipeline via LangGraph-aligned stream runner."""
    async for item in stream_single_ticket_pipeline(
        req,
        symbol=symbol,
        primary_override=primary_override,
        prior_snapshot=prior_snapshot,
        path_id=path_id,
    ):
        yield item
