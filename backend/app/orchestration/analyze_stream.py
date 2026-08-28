from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

from app.agents.specs import build_supervisor_agent, extract_symbol, extract_symbols
from app.context.compaction import compaction_engine
from app.memory.indexer import post_analyze_archive
from app.memory.preview import build_memory_preview
from app.memory.request_context import set_memory_hints
from app.models.analysis import AnalysisStep, AnalyzeRequest, SseEvent
from app.models.context import ContextSnapshot
from app.orchestration.agent_loop import run_agent
from app.orchestration.analysis_registry import analysis_registry
from app.orchestration.compose_route import has_memory_intent
from app.orchestration.composite_pipeline import run_composite_screen_plan
from app.orchestration.market_pipeline import run_market_pipeline
from app.orchestration.nl_plan import (
    detect_simple_intent,
    is_cancel_analysis_intent,
    is_factor_mine_intent,
    is_factor_screen_intent,
    parse_factor_screen_plan,
    parse_nl_plan,
)
from app.orchestration.portfolio_pipeline import run_portfolio_pipeline
from app.orchestration.simple_action_pipeline import (
    run_cancel_analysis_pipeline,
    run_factor_mine_pipeline,
    run_ingest_policy_pipeline,
    run_list_factors_pipeline,
    run_list_portfolios_pipeline,
    run_search_knowledge_pipeline,
)
from app.orchestration.single_pipeline import (
    has_view_reports,
    run_single_followup,
    run_single_pipeline,
)
from app.orchestration.stream_mux import multiplex_step_stream
from app.persistence.paths import path_store
from app.persistence.portfolio_store import portfolio_store
from app.prompts.context import PromptContext


async def analyze_stream(req: AnalyzeRequest) -> AsyncIterator[SseEvent]:
    target = req.target or extract_symbol(req.message)
    resuming = False
    path_id: str
    seq: int
    prior_snapshot: ContextSnapshot | None = None
    cancel_intent = is_cancel_analysis_intent(req.message)

    if req.session_id:
        entry = await path_store.get_entry(req.session_id)
        if entry is None:
            yield SseEvent(type="error", message=f"会话不存在: {req.session_id}")
            return
        if await path_store.is_actively_running(req.session_id) and not cancel_intent:
            yield SseEvent(type="error", message="该会话仍在分析中，请稍后再试")
            return
        path_id = entry.id
        resuming = True
        target = target or entry.target
        prior_steps = await path_store.load_steps(path_id)
        seq = len(prior_steps)
        if compaction_engine.should_compact(prior_steps):
            prior_snapshot = await compaction_engine.compact_steps(prior_steps)
            snap_payload = prior_snapshot.model_dump(mode="json")
            await path_store.save_snapshot(path_id, snap_payload)
            yield SseEvent(type="compaction", snapshot=snap_payload, path_id=path_id)
        await path_store.update_status(path_id, "running")
        await path_store.update_session_meta(path_id, focus=req.focus, target=target)
    else:
        for orphan_id in analysis_registry.cancel_all():
            await path_store.update_status(orphan_id, "error")
        title = req.message.strip()[:40] or "新对话"
        entry = await path_store.create_entry(
            title=title,
            kind=req.kind,
            realm=req.realm,
            status="running",
            target=target,
            focus=req.focus,
        )
        path_id = entry.id
        seq = 0

    user_step = AnalysisStep(
        id=uuid4().hex[:12],
        agent="user",
        role="user",
        result=req.message,
    )
    seq += 1
    await path_store.append_step(path_id, user_step.model_dump(mode="json"), seq=seq)
    yield SseEvent(type="step", step=user_step, path_id=path_id)

    cancel_ev = analysis_registry.register(path_id)

    memory_hints: list[str] = []
    if has_memory_intent(f"{req.message} {req.focus or ''}") or resuming:
        preview = await build_memory_preview(
            message=req.message,
            kind=req.kind,
            symbol=target,
            focus=req.focus,
        )
        memory_hints = list(preview.get("hints") or [])
        set_memory_hints(memory_hints)
        if memory_hints:
            yield SseEvent(
                type="memory",
                path_id=path_id,
                message=preview.get("summary"),
                snapshot={"hints": memory_hints, "sections": preview.get("sections")},
            )

    else:
        set_memory_hints([])

    prompt_ctx = PromptContext(
        path_kind=req.kind,
        realm=req.realm,
        symbol=target,
        focus=req.focus,
        snapshot_summary=prior_snapshot.summary if prior_snapshot else None,
        snapshot_findings=prior_snapshot.finding_lines() if prior_snapshot else [],
        carried_output_refs=prior_snapshot.carried_outputs if prior_snapshot else [],
        memory_hints=memory_hints,
    )

    simple_intent = detect_simple_intent(req.message)
    if simple_intent and (not resuming or simple_intent.get("intent") == "cancel_analysis"):
        intent = simple_intent.get("intent")
        if intent == "list_portfolios":
            step_iter = run_list_portfolios_pipeline()
        elif intent == "list_factors":
            step_iter = run_list_factors_pipeline(theme=simple_intent.get("theme"))
        elif intent == "factor_mine":
            step_iter = run_factor_mine_pipeline(simple_intent)
        elif intent == "ingest_policy":
            step_iter = run_ingest_policy_pipeline(simple_intent)
        elif intent == "search_knowledge":
            step_iter = run_search_knowledge_pipeline(simple_intent)
        elif intent == "cancel_analysis":
            step_iter = run_cancel_analysis_pipeline(path_id=path_id)
        else:  # pragma: no cover - defensive
            step_iter = run_list_portfolios_pipeline()
    elif req.kind == "market":
        index = target or "sh000300"
        step_iter = run_market_pipeline(
            req,
            index_symbol=index,
            primary_override=req.primary_model,
            prior_snapshot=prior_snapshot,
            path_id=path_id,
        )
    elif req.kind == "portfolio":
        symbols = extract_symbols(req.message)
        if len(symbols) < 2:
            symbols = portfolio_store.symbols_for(req.target, fallback=symbols or None)
        if not symbols:
            yield SseEvent(
                type="error",
                message="未能解析组合成员，请在消息中列出代码或先配置默认自选",
                path_id=path_id,
            )
            await path_store.update_status(path_id, "error")
            return
        rec = portfolio_store.get((req.target or "").strip() or "default")
        portfolio_name = rec.name if rec else "自选组合"
        step_iter = run_portfolio_pipeline(
            req,
            symbols=symbols,
            portfolio_name=portfolio_name,
            primary_override=req.primary_model,
            prior_snapshot=prior_snapshot,
            path_id=path_id,
        )
    elif req.kind == "single" and target:
        reports_data = await path_store.load_reports(path_id) if resuming else None
        followup = (
            resuming
            and not req.force_full
            and reports_data is not None
            and has_view_reports(reports_data)
        )
        if followup:
            step_iter = run_single_followup(
                req,
                symbol=target,
                reports_data=reports_data,
                primary_override=req.primary_model,
                prior_snapshot=prior_snapshot,
                path_id=path_id,
            )
        else:
            step_iter = run_single_pipeline(
                req,
                symbol=target,
                primary_override=req.primary_model,
                prior_snapshot=prior_snapshot,
                path_id=path_id,
            )
    else:
        plan = parse_nl_plan(req.message, focus=req.focus) or parse_factor_screen_plan(
            req.message, focus=req.focus
        )
        mine_intent = is_factor_mine_intent(req.message)
        screen_intent = is_factor_screen_intent(req.message)
        if req.kind == "single" and not target and not resuming and not mine_intent and not screen_intent:
            yield SseEvent(
                type="error",
                message="未能从消息中识别股票代码，请包含 6 位代码（如 600519）",
                path_id=path_id,
            )
            await path_store.update_status(path_id, "error")
            return
        if plan:
            step_iter = run_composite_screen_plan(
                req,
                plan,
                primary_override=req.primary_model,
                prior_snapshot=prior_snapshot,
                path_id=path_id,
            )
        else:
            agent = build_supervisor_agent()
            step_iter = run_agent(
                agent,
                user_message=req.message,
                prompt_ctx=prompt_ctx,
                primary_override=req.primary_model,
            )

    completed = False
    cancelled = False
    try:
        async for event in multiplex_step_stream(step_iter, path_id=path_id):
            if cancel_ev.is_set():
                cancelled = True
                await path_store.update_status(path_id, "error")
                yield SseEvent(type="error", message="分析已取消", path_id=path_id)
                return
            if event.type in ("step", "phase", "token"):
                await path_store.touch_activity(path_id)
            if event.type == "step" and event.step:
                seq += 1
                await path_store.append_step(
                    path_id, event.step.model_dump(mode="json"), seq=seq
                )
            yield event
        await path_store.update_status(path_id, "done")
        completed = True
        asyncio.create_task(post_analyze_archive(path_id))
        yield SseEvent(type="done", path_id=path_id)
    except asyncio.CancelledError:
        cancelled = True
        await path_store.update_status(path_id, "error")
        raise
    except Exception as exc:
        await path_store.update_status(path_id, "error")
        yield SseEvent(type="error", message=str(exc), path_id=path_id)
    finally:
        analysis_registry.unregister(path_id)
        if not completed and not cancelled:
            entry = await path_store.get_entry_raw(path_id)
            if entry is not None and entry.status == "running":
                await path_store.update_status(path_id, "error")
