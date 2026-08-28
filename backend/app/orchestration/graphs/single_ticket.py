from __future__ import annotations

import asyncio
import operator
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated, Any, TypedDict

from app.factors.attach import attach_factors_for_symbol
from app.models.analysis import AnalysisStep, AnalyzeRequest
from app.models.context import ContextSnapshot
from app.models.pipeline import PipelineReports
from app.orchestration import pipeline_phases as phases
from app.orchestration.agent_loop import run_agent
from app.orchestration.time_window import parse_ohlcv_limit
from app.orchestration.stream_types import PhaseMarker, StreamItem
from app.persistence.paths import path_store
from app.prompts.loader import load_agent

StepCallback = Callable[[AnalysisStep], Awaitable[None]]


async def _stream_phase_update(
    run_update: Callable[..., Awaitable[dict[str, Any]]],
    **kwargs: Any,
) -> AsyncIterator[AnalysisStep | dict[str, Any]]:
    """Run a phase update and yield each step before the final update dict."""
    queue: asyncio.Queue[AnalysisStep | dict[str, Any]] = asyncio.Queue()

    async def on_step(step: AnalysisStep) -> None:
        await queue.put(step)

    async def worker() -> None:
        update = await run_update(**kwargs, on_step=on_step)
        await queue.put(update)

    task = asyncio.create_task(worker())
    try:
        while True:
            item = await queue.get()
            if isinstance(item, dict):
                yield item
                break
            yield item
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        else:
            await task


def _merge_reports(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    base = PipelineReports.model_validate(left or {})
    if right:
        base = base.merge(PipelineReports.model_validate(right))
    return base.model_dump(mode="json")


class SingleTicketState(TypedDict, total=False):
    req: dict[str, Any]
    symbol: str
    company_name: str | None
    primary_override: str | None
    prior_snapshot: dict[str, Any] | None
    enable_debate: bool
    debate_rounds: int
    path_id: str | None
    findings: Annotated[list[str], operator.add]
    refs: list[str]
    reports: Annotated[dict[str, Any], _merge_reports]
    debate_history: str
    steps: Annotated[list[dict[str, Any]], operator.add]


def _req(state: SingleTicketState) -> AnalyzeRequest:
    return AnalyzeRequest.model_validate(state["req"])


def _reports(state: SingleTicketState) -> PipelineReports:
    return phases.reports_from_dict(state.get("reports"))


def _prior_snapshot(state: SingleTicketState) -> ContextSnapshot | None:
    raw = state.get("prior_snapshot")
    return ContextSnapshot.model_validate(raw) if raw else None


async def _data_phase_update(
    symbol: str,
    prior_snapshot: ContextSnapshot | None,
    req: AnalyzeRequest,
    *,
    on_step: StepCallback | None = None,
) -> dict[str, Any]:
    seed_findings, seed_refs, _seed_summary = phases.merge_prior_snapshot(prior_snapshot)
    ohlcv_limit = parse_ohlcv_limit(req.message, focus=req.focus)
    data_steps, findings, refs, company_name, data_summary = await phases.run_data_phase(
        symbol,
        ohlcv_limit=ohlcv_limit,
        on_step=on_step,
    )
    reports = PipelineReports(data_summary=data_summary)
    all_findings = seed_findings + findings
    all_refs = list(seed_refs)
    for ref in refs:
        if ref not in all_refs:
            all_refs.append(ref)
    step_dicts = [step.model_dump(mode="json") for step in data_steps]
    return {
        "steps": step_dicts,
        "findings": all_findings,
        "refs": all_refs,
        "company_name": company_name,
        "reports": reports.model_dump(mode="json"),
    }


async def _views_phase_update(
    state: SingleTicketState,
    *,
    reports: PipelineReports,
    findings: list[str],
    refs: list[str],
    on_step: StepCallback | None = None,
) -> dict[str, Any]:
    req = _req(state)
    out_steps: list[dict[str, Any]] = []
    new_findings: list[str] = []

    async for step, report, done in phases.run_view_agents_parallel(
        req,
        symbol=state["symbol"],
        company_name=state.get("company_name"),
        findings=findings,
        refs=refs,
        reports=reports,
        primary_override=state.get("primary_override"),
        view_agent_ids=phases.resolve_view_agent_ids(req),
    ):
        if done and report:
            reports.set_report(report.agent_id, report.step_id, report.content)
            new_findings.append(
                f"[{report.step_id}] {report.agent_id}: {phases.truncate(report.content)}"
            )
            continue
        if step.id:
            out_steps.append(step.model_dump(mode="json"))
            if on_step is not None:
                await on_step(step)

    return {
        "steps": out_steps,
        "findings": new_findings,
        "reports": reports.model_dump(mode="json"),
    }


async def _debate_phase_update(
    state: SingleTicketState,
    *,
    reports: PipelineReports,
    findings: list[str],
    refs: list[str],
    debate_history: str,
    on_step: StepCallback | None = None,
) -> dict[str, Any]:
    req = _req(state)
    rounds = max(1, int(state.get("debate_rounds") or 1))
    history = debate_history
    out_steps: list[dict[str, Any]] = []
    new_findings: list[str] = []

    for _ in range(rounds):
        steps, history, reports = await phases.run_debate_round(
            req,
            symbol=state["symbol"],
            company_name=state.get("company_name"),
            findings=findings,
            refs=refs,
            reports=reports,
            debate_history=history,
            primary_override=state.get("primary_override"),
        )
        for step in steps:
            out_steps.append(step.model_dump(mode="json"))
            if on_step is not None:
                await on_step(step)
            if step.role == "assistant":
                new_findings.append(phases.finding_from_step(step))

    return {
        "steps": out_steps,
        "findings": new_findings,
        "debate_history": history,
        "reports": reports.model_dump(mode="json"),
    }


async def _judge_phase_update(
    state: SingleTicketState,
    *,
    reports: PipelineReports,
    findings: list[str],
    refs: list[str],
    debate_history: str,
    on_step: StepCallback | None = None,
) -> dict[str, Any]:
    req = _req(state)
    _, _, seed_summary = phases.merge_prior_snapshot(_prior_snapshot(state))

    judge_findings, judge_summary = await phases.compact_for_judge(
        findings,
        refs,
        reports,
        seed_summary,
    )
    ctx = phases.build_prompt_ctx(
        req,
        symbol=state["symbol"],
        company_name=state.get("company_name"),
        findings=judge_findings,
        refs=refs,
        reports=reports,
        snapshot_summary=judge_summary,
        debate_history=debate_history,
    )
    judge = load_agent("judge")
    task = phases.task_for_agent(
        "judge",
        symbol=state["symbol"],
        company_name=state.get("company_name"),
        user_message=req.message,
    )
    out_steps: list[dict[str, Any]] = []
    async for step in run_agent(
        judge,
        user_message=task,
        prompt_ctx=ctx,
        primary_override=state.get("primary_override"),
    ):
        out_steps.append(step.model_dump(mode="json"))
        if on_step is not None:
            await on_step(step)
        if step.role == "assistant" and step.agent == "judge":
            reports.set_report("judge", step.id, step.result or step.thought)

    return {
        "steps": out_steps,
        "reports": reports.model_dump(mode="json"),
    }


async def stream_single_ticket_pipeline(
    req: AnalyzeRequest,
    *,
    symbol: str,
    primary_override: str | None = None,
    prior_snapshot: ContextSnapshot | None = None,
    path_id: str | None = None,
) -> AsyncIterator[StreamItem]:
    """LangGraph-aligned single-ticket pipeline with incremental SSE streaming."""
    state: SingleTicketState = {
        "req": req.model_dump(mode="json"),
        "symbol": symbol,
        "primary_override": primary_override,
        "prior_snapshot": prior_snapshot.model_dump(mode="json") if prior_snapshot else None,
        "enable_debate": req.enable_debate,
        "debate_rounds": req.debate_rounds,
        "path_id": path_id,
    }

    yield PhaseMarker("data", "拉取行情与指标")
    data_update: dict[str, Any] | None = None
    async for item in _stream_phase_update(
        _data_phase_update,
        symbol=symbol,
        prior_snapshot=prior_snapshot,
        req=req,
    ):
        if isinstance(item, dict):
            data_update = item
        else:
            yield item
    assert data_update is not None

    findings = list(data_update["findings"])
    refs = list(data_update["refs"])
    reports = PipelineReports.model_validate(data_update["reports"])
    state["company_name"] = data_update.get("company_name")

    yield PhaseMarker("factors", "挂载 live 因子截面")
    factor_summary, factor_findings = await attach_factors_for_symbol(symbol)
    if factor_summary:
        reports.factor_summary = factor_summary
        findings.extend(factor_findings)

    yield PhaseMarker("views", "三视角分析（技术 / 基本面 / 舆情）")
    views_update: dict[str, Any] | None = None
    async for item in _stream_phase_update(
        _views_phase_update,
        state=state,
        reports=reports,
        findings=findings,
        refs=refs,
    ):
        if isinstance(item, dict):
            views_update = item
        else:
            yield item
    assert views_update is not None
    findings.extend(views_update["findings"])
    reports = PipelineReports.model_validate(views_update["reports"])

    debate_history = ""
    if req.enable_debate:
        yield PhaseMarker("debate", "多空辩论")
        debate_update: dict[str, Any] | None = None
        async for item in _stream_phase_update(
            _debate_phase_update,
            state=state,
            reports=reports,
            findings=findings,
            refs=refs,
            debate_history=debate_history,
        ):
            if isinstance(item, dict):
                debate_update = item
            else:
                yield item
        assert debate_update is not None
        findings.extend(debate_update["findings"])
        debate_history = debate_update["debate_history"]
        reports = PipelineReports.model_validate(debate_update["reports"])

    yield PhaseMarker("judge", "综合研判")
    judge_update: dict[str, Any] | None = None
    async for item in _stream_phase_update(
        _judge_phase_update,
        state=state,
        reports=reports,
        findings=findings,
        refs=refs,
        debate_history=debate_history,
    ):
        if isinstance(item, dict):
            judge_update = item
        else:
            yield item
    assert judge_update is not None
    reports = PipelineReports.model_validate(judge_update["reports"])

    if path_id:
        await path_store.save_reports(path_id, reports.model_dump(mode="json"))
