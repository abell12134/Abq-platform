from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.context.compaction import compaction_engine
from app.data.bar_processing import calc_indicators, clean_bars
from app.data.fundamentals import fetch_fundamentals
from app.data.ohlcv import fetch_ohlcv
from app.data.quotes_realtime import fetch_quote
from app.data.sector_pulse import fetch_market_breadth, fetch_sector_pulse
from app.memory.request_context import get_memory_hints
from app.models.analysis import AnalysisStep, AnalyzeRequest, ToolCall
from app.models.context import ContextSnapshot
from app.models.pipeline import AgentReport, PipelineReports
from app.orchestration.agent_loop import run_agent
from app.orchestration.time_window import DEFAULT_OHLCV_LIMIT
from app.orchestration.tool_output import compact_tool_output
from app.prompts.context import PromptContext
from app.prompts.loader import load_agent, prompt_id_for_agent

log = logging.getLogger(__name__)

DEFAULT_MARKET_INDEX = "sh000300"

VIEW_AGENT_IDS = ("tech", "fundamental", "sentiment")
MARKET_VIEW_AGENT_IDS = ("market", "sentiment")
PORTFOLIO_VIEW_AGENT_IDS = ("portfolio",)
DEFAULT_VIEW_AGENT_IDS = VIEW_AGENT_IDS
DEBATE_AGENT_IDS = ("bull", "bear")


def resolve_view_agent_ids(req: AnalyzeRequest) -> tuple[str, ...]:
    if not req.agent_ids:
        return VIEW_AGENT_IDS
    valid = [a for a in req.agent_ids if a in VIEW_AGENT_IDS]
    return tuple(valid) if valid else VIEW_AGENT_IDS


def resolve_market_agent_ids(req: AnalyzeRequest) -> tuple[str, ...]:
    if not req.agent_ids:
        return MARKET_VIEW_AGENT_IDS
    valid = [a for a in req.agent_ids if a in MARKET_VIEW_AGENT_IDS]
    return tuple(valid) if valid else MARKET_VIEW_AGENT_IDS


def resolve_portfolio_agent_ids(req: AnalyzeRequest) -> tuple[str, ...]:
    if not req.agent_ids:
        return PORTFOLIO_VIEW_AGENT_IDS
    valid = [a for a in req.agent_ids if a in PORTFOLIO_VIEW_AGENT_IDS]
    return tuple(valid) if valid else PORTFOLIO_VIEW_AGENT_IDS


def truncate(text: str, limit: int = 400) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def finding_from_step(step: AnalysisStep) -> str:
    body = step.result or step.thought
    return f"[{step.id}] {step.agent}: {truncate(body)}"


def report_from_step(step: AnalysisStep) -> AgentReport:
    return AgentReport(
        agent_id=step.agent,
        step_id=step.id,
        content=(step.result or step.thought or "").strip(),
    )


async def tool_step(
    tool: str,
    payload: dict,
    *,
    output_ref: str | None = None,
    compact: bool = True,
) -> AnalysisStep:
    summary = json.dumps(payload, ensure_ascii=False)
    if compact:
        summary = await compact_tool_output(tool, summary, extract=False)
    return AnalysisStep(
        id=uuid4().hex[:12],
        agent=tool,
        role="tool",
        result=summary,
        tool_calls=[
            ToolCall(
                id=uuid4().hex[:8],
                tool=tool,
                args={},
                output=summary,
                output_ref=output_ref,
                status="ok",
            )
        ],
    )


def task_for_agent(
    agent_id: str,
    *,
    symbol: str,
    company_name: str | None,
    user_message: str,
) -> str:
    label = company_name or symbol
    tasks = {
        "tech": (
            f"数据阶段已完成（见结构化报告/关键发现）。"
            f"请对 {label}（{symbol}）做技术面分析。用户问题：{user_message}"
        ),
        "fundamental": (
            f"数据阶段已完成（含基本面工具结果，见结构化报告/关键发现）。"
            f"请对 {label}（{symbol}）做基本面分析，勿重复调用 fetch_fundamentals。用户问题：{user_message}"
        ),
        "sentiment": (
            f"请分析 {label}（{symbol}）的舆情与公告。必须先调用 fetch_sentiment；"
            f"若 unavailable 须在「证据不足」说明。用户问题：{user_message}"
        ),
        "market": (
            f"数据阶段已完成（指数行情与指标见 findings）。"
            f"请对大盘指数 {label}（{symbol}）做宏观与技术面研判；"
            f"可引用择时因子与板块脉冲 findings。用户问题：{user_message}"
        ),
        "portfolio": (
            f"数据阶段已完成（组合成员行情摘要见 findings）。"
            f"请对组合「{label}」做逐票快速诊断与整体配置评估。用户问题：{user_message}"
        ),
        "bull": (
            f"作为看多研究员，基于已有三视角报告，阐述 {label}（{symbol}）的积极论证。"
            f"用户问题：{user_message}"
        ),
        "bear": (
            f"作为看空研究员，基于已有三视角报告与辩论记录，阐述 {label}（{symbol}）的风险侧论证。"
            f"用户问题：{user_message}"
        ),
        "judge": (
            f"请综合已有报告，对 {label}（{symbol}）给出研判。"
            f"用户原问题：{user_message}"
        ),
    }
    return tasks.get(agent_id, user_message)


def build_prompt_ctx(
    req: AnalyzeRequest,
    *,
    symbol: str,
    company_name: str | None,
    findings: list[str],
    refs: list[str],
    reports: PipelineReports,
    snapshot_summary: str | None = None,
    debate_history: str = "",
) -> PromptContext:
    return PromptContext(
        path_kind=req.kind,
        realm=req.realm,
        symbol=symbol,
        company_name=company_name,
        focus=req.focus,
        snapshot_summary=snapshot_summary,
        snapshot_findings=list(findings),
        carried_output_refs=list(refs),
        reports=reports,
        debate_history=debate_history,
        memory_hints=get_memory_hints(),
    )


async def run_data_phase(
    symbol: str,
    *,
    ohlcv_limit: int = DEFAULT_OHLCV_LIMIT,
    on_step: Callable[[AnalysisStep], Awaitable[None]] | None = None,
) -> tuple[list[AnalysisStep], list[str], list[str], str | None, str]:
    steps: list[AnalysisStep] = []
    findings: list[str] = []
    refs: list[str] = []
    company_name: str | None = None

    async def emit(step: AnalysisStep) -> None:
        steps.append(step)
        findings.append(finding_from_step(step))
        if on_step is not None:
            await on_step(step)

    quote = await fetch_quote(symbol)
    qlib_sym = quote.get("symbol") or symbol
    if quote.get("name"):
        company_name = str(quote["name"])
    refs.append(qlib_sym)
    await emit(await tool_step("fetch_quote", quote, output_ref=qlib_sym))

    ohlcv = await fetch_ohlcv(symbol, limit=ohlcv_limit)
    qlib_sym = ohlcv["symbol"]
    refs.append(qlib_sym)
    await emit(await tool_step("fetch_ohlcv", ohlcv, output_ref=qlib_sym))

    cleaned = clean_bars(ohlcv["bars"])
    clean_payload = {"source": "clean_data", "symbol": qlib_sym, **cleaned}
    await emit(await tool_step("clean_data", clean_payload, output_ref=qlib_sym))

    indicators = calc_indicators(cleaned["bars"])
    indicator_payload = {"source": "calc_indicator", "symbol": qlib_sym, **indicators}
    await emit(await tool_step("calc_indicator", indicator_payload, output_ref=qlib_sym))

    fundamentals = await fetch_fundamentals(symbol)
    fund_sym = fundamentals.get("symbol") or qlib_sym
    if fund_sym not in refs:
        refs.append(fund_sym)
    await emit(await tool_step("fetch_fundamentals", fundamentals, output_ref=fund_sym))

    brief = {
        "symbol": qlib_sym,
        "quote": quote if quote.get("status") == "ok" else None,
        "ohlcv_summary": ohlcv.get("summary"),
        "clean_summary": cleaned.get("summary"),
        "indicators": indicators,
        "fundamentals_status": fundamentals.get("status"),
        "recent_bars": cleaned["bars"][-5:],
    }
    data_summary = truncate(json.dumps(brief, ensure_ascii=False), 800)
    findings.append(f"[data] 数据摘要: {data_summary}")
    return steps, findings, refs, company_name, data_summary


async def run_market_data_phase(
    index_symbol: str = DEFAULT_MARKET_INDEX,
    *,
    theme_hint: str = "",
    on_step: Callable[[AnalysisStep], Awaitable[None]] | None = None,
) -> tuple[list[AnalysisStep], list[str], list[str], str | None, str]:
    """Index OHLCV + indicators for market pipeline (no single-stock fundamentals)."""
    steps: list[AnalysisStep] = []
    findings: list[str] = []
    refs: list[str] = []
    label = "沪深300"

    async def emit(step: AnalysisStep) -> None:
        steps.append(step)
        findings.append(finding_from_step(step))
        if on_step is not None:
            await on_step(step)

    quote = await fetch_quote(index_symbol)
    qlib_sym = quote.get("symbol") or index_symbol
    if quote.get("name"):
        label = str(quote["name"])
    refs.append(qlib_sym)
    await emit(await tool_step("fetch_quote", quote, output_ref=qlib_sym))

    ohlcv = await fetch_ohlcv(index_symbol, limit=120)
    qlib_sym = ohlcv["symbol"]
    refs.append(qlib_sym)
    await emit(await tool_step("fetch_ohlcv", ohlcv, output_ref=qlib_sym))

    cleaned = clean_bars(ohlcv["bars"])
    clean_payload = {"source": "clean_data", "symbol": qlib_sym, **cleaned}
    await emit(await tool_step("clean_data", clean_payload, output_ref=qlib_sym))

    indicators = calc_indicators(cleaned["bars"])
    indicator_payload = {"source": "calc_indicator", "symbol": qlib_sym, **indicators}
    await emit(await tool_step("calc_indicator", indicator_payload, output_ref=qlib_sym))

    breadth = await fetch_market_breadth()
    await emit(await tool_step("fetch_market_breadth", breadth))

    pulse = await fetch_sector_pulse(theme_hint=theme_hint)
    await emit(await tool_step("fetch_sector_pulse", pulse))

    brief = {
        "index": qlib_sym,
        "label": label,
        "quote": quote if quote.get("status") == "ok" else None,
        "ohlcv_summary": ohlcv.get("summary"),
        "indicators": indicators,
        "breadth": breadth,
        "sector_pulse": {
            "top_gainers": pulse.get("top_gainers"),
            "top_losers": pulse.get("top_losers"),
            "focus_matches": pulse.get("focus_matches"),
        },
        "recent_bars": cleaned["bars"][-5:],
    }
    data_summary = truncate(json.dumps(brief, ensure_ascii=False), 800)
    findings.append(f"[data] 大盘数据摘要: {data_summary}")
    return steps, findings, refs, label, data_summary


async def run_portfolio_data_phase(
    symbols: list[str],
    *,
    portfolio_name: str = "自选组合",
    on_step: Callable[[AnalysisStep], Awaitable[None]] | None = None,
) -> tuple[list[AnalysisStep], list[str], list[str], str, str]:
    """Batch quotes + light indicators for portfolio members."""
    steps: list[AnalysisStep] = []
    findings: list[str] = []
    refs: list[str] = []
    members: list[dict[str, Any]] = []

    async def emit(step: AnalysisStep) -> None:
        steps.append(step)
        findings.append(finding_from_step(step))
        if on_step is not None:
            await on_step(step)

    for sym in symbols[:8]:
        try:
            quote = await fetch_quote(sym)
        except Exception as exc:  # noqa: BLE001
            log.debug("portfolio quote %s failed: %s", sym, exc)
            continue
        qlib_sym = str(quote.get("symbol") or sym)
        refs.append(qlib_sym)
        await emit(await tool_step("fetch_quote", quote, output_ref=qlib_sym))
        try:
            ohlcv = await fetch_ohlcv(sym, limit=40)
            cleaned = clean_bars(ohlcv["bars"])
            indicators = calc_indicators(cleaned["bars"])
            members.append(
                {
                    "symbol": qlib_sym,
                    "name": quote.get("name"),
                    "price": quote.get("price"),
                    "pct_change": quote.get("pct_change"),
                    "ma5": indicators.get("ma5"),
                    "ma20": indicators.get("ma20"),
                    "chg_5d": indicators.get("chg_5d"),
                    "chg_20d": indicators.get("chg_20d"),
                }
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("portfolio ohlcv %s failed: %s", sym, exc)
            members.append(
                {
                    "symbol": qlib_sym,
                    "name": quote.get("name"),
                    "price": quote.get("price"),
                    "pct_change": quote.get("pct_change"),
                }
            )

    summary_payload = {
        "portfolio": portfolio_name,
        "member_count": len(members),
        "members": members,
    }
    await emit(await tool_step("fetch_portfolio_quotes", summary_payload))
    data_summary = truncate(json.dumps(summary_payload, ensure_ascii=False), 1200)
    findings.append(f"[data] 组合行情摘要: {data_summary}")
    return steps, findings, refs, portfolio_name, data_summary


async def collect_agent_steps(
    agent_id: str,
    *,
    req: AnalyzeRequest,
    symbol: str,
    company_name: str | None,
    findings: list[str],
    refs: list[str],
    reports: PipelineReports,
    primary_override: str | None,
    snapshot_summary: str | None = None,
    debate_history: str = "",
) -> tuple[list[AnalysisStep], AgentReport | None]:
    agent = load_agent(agent_id, prompt_id=prompt_id_for_agent(agent_id, req))
    task = task_for_agent(
        agent_id,
        symbol=symbol,
        company_name=company_name,
        user_message=req.message,
    )
    ctx = build_prompt_ctx(
        req,
        symbol=symbol,
        company_name=company_name,
        findings=findings,
        refs=refs,
        reports=reports,
        snapshot_summary=snapshot_summary,
        debate_history=debate_history,
    )
    steps: list[AnalysisStep] = []
    final: AnalysisStep | None = None
    async for step in run_agent(
        agent,
        user_message=task,
        prompt_ctx=ctx,
        primary_override=primary_override,
    ):
        steps.append(step)
        if step.role == "assistant" and step.agent == agent_id:
            final = step
    report = report_from_step(final) if final else None
    return steps, report


@dataclass
class _ViewDone:
    agent_id: str
    report: AgentReport | None


async def run_view_agents_parallel(
    req: AnalyzeRequest,
    *,
    symbol: str,
    company_name: str | None,
    findings: list[str],
    refs: list[str],
    reports: PipelineReports,
    primary_override: str | None,
    view_agent_ids: tuple[str, ...] | None = None,
) -> AsyncIterator[tuple[AnalysisStep, AgentReport | None, bool]]:
    """Yields (step, report_or_none, is_agent_done). report set on last step of each agent."""
    queue: asyncio.Queue[AnalysisStep | _ViewDone] = asyncio.Queue()
    agents = view_agent_ids or VIEW_AGENT_IDS

    async def worker(agent_id: str) -> None:
        agent = load_agent(agent_id, prompt_id=prompt_id_for_agent(agent_id, req))
        task = task_for_agent(
            agent_id,
            symbol=symbol,
            company_name=company_name,
            user_message=req.message,
        )
        ctx = build_prompt_ctx(
            req,
            symbol=symbol,
            company_name=company_name,
            findings=findings,
            refs=refs,
            reports=reports,
        )
        final: AnalysisStep | None = None
        try:
            async for step in run_agent(
                agent,
                user_message=task,
                prompt_ctx=ctx,
                primary_override=primary_override,
            ):
                await queue.put(step)
                if step.role == "assistant" and step.agent == agent_id:
                    final = step
            report = report_from_step(final) if final else None
            await queue.put(_ViewDone(agent_id=agent_id, report=report))
        except BaseException as exc:
            log.exception("view agent %s failed", agent_id)
            err = AnalysisStep(
                id=uuid4().hex[:12],
                agent=agent_id,
                role="assistant",
                result=f"分析失败：{exc}",
            )
            await queue.put(err)
            await queue.put(_ViewDone(agent_id=agent_id, report=report_from_step(err)))

    workers = [asyncio.create_task(worker(aid)) for aid in agents]
    pending = len(agents)
    try:
        while pending > 0:
            item = await queue.get()
            if isinstance(item, _ViewDone):
                yield AnalysisStep(id="", agent=item.agent_id, role="assistant", result=""), item.report, True
                pending -= 1
                continue
            yield item, None, False
    finally:
        await asyncio.gather(*workers, return_exceptions=True)


async def run_debate_round(
    req: AnalyzeRequest,
    *,
    symbol: str,
    company_name: str | None,
    findings: list[str],
    refs: list[str],
    reports: PipelineReports,
    debate_history: str,
    primary_override: str | None,
) -> tuple[list[AnalysisStep], str, PipelineReports]:
    history = debate_history
    all_steps: list[AnalysisStep] = []
    for agent_id in DEBATE_AGENT_IDS:
        steps, report = await collect_agent_steps(
            agent_id,
            req=req,
            symbol=symbol,
            company_name=company_name,
            findings=findings,
            refs=refs,
            reports=reports,
            primary_override=primary_override,
            debate_history=history,
        )
        all_steps.extend(steps)
        if report:
            block = f"### {agent_id}\n{report.content}"
            history = f"{history}\n\n{block}".strip() if history else block
            reports.set_report(agent_id, report.step_id, report.content)
    reports.debate_history = history
    return all_steps, history, reports


def reports_from_dict(data: dict[str, Any] | None) -> PipelineReports:
    if not data:
        return PipelineReports()
    return PipelineReports.model_validate(data)


def merge_prior_snapshot(
    prior: ContextSnapshot | None,
) -> tuple[list[str], list[str], str | None]:
    if not prior:
        return [], [], None
    return prior.finding_lines(), list(prior.carried_outputs), prior.summary


async def compact_for_judge(
    findings: list[str],
    refs: list[str],
    reports: PipelineReports,
    prior_summary: str | None,
) -> tuple[list[str], str | None]:
    report_findings = reports.to_findings()
    merged = list(findings)
    for line in report_findings:
        if line not in merged:
            merged.append(line)
    return await compaction_engine.maybe_compact_findings(
        merged,
        refs,
        prior_summary=prior_summary,
    )
