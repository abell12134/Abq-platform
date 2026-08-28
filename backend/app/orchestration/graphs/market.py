"""Market / index analysis pipeline: data → timing factors → market views → judge."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.factors.attach import attach_market_timing_factors
from app.models.analysis import AnalyzeRequest
from app.models.context import ContextSnapshot
from app.models.pipeline import PipelineReports
from app.orchestration import pipeline_phases as phases
from app.orchestration.agent_loop import run_agent
from app.orchestration.graphs.single_ticket import _stream_phase_update
from app.orchestration.stream_types import PhaseMarker, StreamItem
from app.persistence.paths import path_store
from app.prompts.loader import load_agent

DEFAULT_INDEX = phases.DEFAULT_MARKET_INDEX


async def _market_data_phase_update(
    index_symbol: str,
    prior_snapshot: ContextSnapshot | None,
    *,
    theme_hint: str = "",
    on_step=None,
) -> dict[str, Any]:
    seed_findings, seed_refs, _seed_summary = phases.merge_prior_snapshot(prior_snapshot)
    data_steps, findings, refs, label, data_summary = await phases.run_market_data_phase(
        index_symbol,
        theme_hint=theme_hint,
        on_step=on_step,
    )

    factor_summary, factor_findings = await attach_market_timing_factors(index_symbol)
    all_findings = seed_findings + findings + factor_findings

    reports = PipelineReports(data_summary=data_summary, factor_summary=factor_summary)
    all_refs = list(seed_refs)
    for ref in refs:
        if ref not in all_refs:
            all_refs.append(ref)
    return {
        "steps": [s.model_dump(mode="json") for s in data_steps],
        "findings": all_findings,
        "refs": all_refs,
        "label": label,
        "reports": reports.model_dump(mode="json"),
    }


async def stream_market_pipeline(
    req: AnalyzeRequest,
    *,
    index_symbol: str = DEFAULT_INDEX,
    primary_override: str | None = None,
    prior_snapshot: ContextSnapshot | None = None,
    path_id: str | None = None,
) -> AsyncIterator[StreamItem]:
    yield PhaseMarker("data", "拉取指数行情、宽度与择时因子")
    data_update: dict[str, Any] | None = None
    async for item in _stream_phase_update(
        _market_data_phase_update,
        index_symbol=index_symbol,
        prior_snapshot=prior_snapshot,
        theme_hint=(req.focus or ""),
    ):
        if isinstance(item, dict):
            data_update = item
        else:
            yield item
    assert data_update is not None

    findings = list(data_update["findings"])
    refs = list(data_update["refs"])
    reports = PipelineReports.model_validate(data_update["reports"])
    label = str(data_update.get("label") or "沪深300")

    yield PhaseMarker("views", "大盘研判（宏观 / 情绪）")
    view_ids = phases.resolve_market_agent_ids(req)
    out_steps: list[Any] = []
    async for step, report, done in phases.run_view_agents_parallel(
        req,
        symbol=index_symbol,
        company_name=label,
        findings=findings,
        refs=refs,
        reports=reports,
        primary_override=primary_override,
        view_agent_ids=view_ids,
    ):
        if done and report:
            reports.set_report(report.agent_id, report.step_id, report.content)
            findings.append(
                f"[{report.step_id}] {report.agent_id}: {phases.truncate(report.content)}"
            )
            continue
        if step.id:
            out_steps.append(step)
            yield step

    yield PhaseMarker("judge", "综合研判")
    _, _, seed_summary = phases.merge_prior_snapshot(prior_snapshot)
    judge_findings, judge_summary = await phases.compact_for_judge(
        findings,
        refs,
        reports,
        seed_summary,
    )
    ctx = phases.build_prompt_ctx(
        req,
        symbol=index_symbol,
        company_name=label,
        findings=judge_findings,
        refs=refs,
        reports=reports,
        snapshot_summary=judge_summary,
    )
    judge = load_agent("judge")
    task = (
        f"请综合大盘技术面与市场情绪报告，对指数 {label}（{index_symbol}）给出研判。\n"
        f"用户原问题：{req.message}"
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
