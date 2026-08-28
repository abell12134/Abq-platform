"""Portfolio analysis pipeline: batch quotes → factor attach → portfolio agent → judge."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.factors.attach import attach_factors_for_symbol
from app.models.analysis import AnalyzeRequest
from app.models.context import ContextSnapshot
from app.models.pipeline import PipelineReports
from app.orchestration import pipeline_phases as phases
from app.orchestration.agent_loop import run_agent
from app.orchestration.graphs.single_ticket import _stream_phase_update
from app.orchestration.stream_types import PhaseMarker, StreamItem
from app.persistence.paths import path_store
from app.prompts.loader import load_agent


async def _portfolio_data_phase_update(
    symbols: list[str],
    portfolio_name: str,
    prior_snapshot: ContextSnapshot | None,
    *,
    on_step=None,
) -> dict[str, Any]:
    seed_findings, seed_refs, _seed_summary = phases.merge_prior_snapshot(prior_snapshot)
    data_steps, findings, refs, label, data_summary = await phases.run_portfolio_data_phase(
        symbols,
        portfolio_name=portfolio_name,
        on_step=on_step,
    )
    reports = PipelineReports(data_summary=data_summary, portfolio_summary=data_summary)
    all_findings = seed_findings + findings
    all_refs = list(seed_refs)
    for ref in refs:
        if ref not in all_refs:
            all_refs.append(ref)
    return {
        "steps": [s.model_dump(mode="json") for s in data_steps],
        "findings": all_findings,
        "refs": all_refs,
        "label": label,
        "symbols": symbols,
        "reports": reports.model_dump(mode="json"),
    }


async def stream_portfolio_pipeline(
    req: AnalyzeRequest,
    *,
    symbols: list[str],
    portfolio_name: str = "自选组合",
    primary_override: str | None = None,
    prior_snapshot: ContextSnapshot | None = None,
    path_id: str | None = None,
) -> AsyncIterator[StreamItem]:
    yield PhaseMarker("data", "拉取组合行情")
    data_update: dict[str, Any] | None = None
    async for item in _stream_phase_update(
        _portfolio_data_phase_update,
        symbols=symbols,
        portfolio_name=portfolio_name,
        prior_snapshot=prior_snapshot,
    ):
        if isinstance(item, dict):
            data_update = item
        else:
            yield item
    assert data_update is not None

    findings = list(data_update["findings"])
    refs = list(data_update["refs"])
    reports = PipelineReports.model_validate(data_update["reports"])
    label = str(data_update.get("label") or portfolio_name)
    member_symbols: list[str] = list(data_update.get("symbols") or symbols)

    yield PhaseMarker("factors", "挂载成员因子截面")
    factor_lines: list[str] = []
    for sym in member_symbols[:4]:
        summary, factor_findings = await attach_factors_for_symbol(sym, max_factors=4)
        if summary:
            factor_lines.append(f"### {sym}\n{summary}")
            findings.extend(factor_findings)
    if factor_lines:
        reports.factor_summary = "\n\n".join(factor_lines)
        findings.append("[factors] 组合成员因子截面已挂载")

    yield PhaseMarker("views", "组合诊断")
    view_ids = phases.resolve_portfolio_agent_ids(req)
    portfolio_symbol = member_symbols[0] if member_symbols else "portfolio"
    async for step, report, done in phases.run_view_agents_parallel(
        req,
        symbol=portfolio_symbol,
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
            yield step

    yield PhaseMarker("judge", "综合研判")
    _, _, seed_summary = phases.merge_prior_snapshot(prior_snapshot)
    judge_findings, judge_summary = await phases.compact_for_judge(
        findings, refs, reports, seed_summary
    )
    ctx = phases.build_prompt_ctx(
        req,
        symbol=portfolio_symbol,
        company_name=label,
        findings=judge_findings,
        refs=refs,
        reports=reports,
        snapshot_summary=judge_summary,
    )
    judge = load_agent("judge")
    task = (
        f"请综合组合诊断报告，对「{label}」（{len(member_symbols)} 只成员）给出配置与风险研判。\n"
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
