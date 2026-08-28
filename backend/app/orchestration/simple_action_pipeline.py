"""Deterministic (no-LLM) NL actions executed directly by the orchestration layer."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from app.factors.agent_tools import list_factors_for_agent
from app.factors.mine_tools import schedule_gp_mine, schedule_llm_mine
from app.knowledge.ingest import ingest_text_document
from app.memory.search import search_knowledge
from app.models.analysis import AnalysisStep
from app.models.factors import FactorMineGpRequest, FactorMineLlmRequest
from app.orchestration.analysis_registry import analysis_registry
from app.orchestration.stream_types import PhaseMarker, StreamItem
from app.persistence.portfolio_store import portfolio_store


def _markdown_table(rows: list[tuple[str, str, int, str]]) -> str:
    if not rows:
        return "暂无自选组合。可在选组页新建，或对话里说「从沪深300选出 20 只放进默认自选」。"
    lines = ["| ID | 名称 | 成员数 | 成员代码 |", "|---|---|---:|---|"]
    for pid, name, count, symbols in rows:
        lines.append(f"| `{pid}` | {name} | {count} | {symbols} |")
    return "\n".join(lines)


async def run_list_portfolios_pipeline() -> AsyncIterator[StreamItem]:
    """List all portfolios as a chat step — no LLM, no symbol required."""
    yield PhaseMarker("portfolios", "列出我的自选组合")
    portfolio_store.ensure()
    rows: list[tuple[str, str, int, str]] = []
    for rec in portfolio_store.list_portfolios():
        syms = ", ".join(m.symbol for m in rec.members) or "—"
        rows.append((rec.id, rec.name, len(rec.members), syms))
    body = (
        f"## 我的自选组合（{len(rows)} 个）\n\n"
        f"{_markdown_table(rows)}\n\n"
        "可继续说：「诊断默认自选」或「从沪深300选出 20 只替换进默认自选」。"
    )
    yield AnalysisStep(
        id=uuid4().hex[:12],
        agent="list_portfolios",
        role="assistant",
        result=body,
    )


def _fmt_num(v: object) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):+.3f}" if isinstance(v, (int, float)) else str(v)
    except Exception:
        return str(v)


async def run_list_factors_pipeline(*, theme: str | None = None) -> AsyncIterator[StreamItem]:
    """List factors as a chat step — no LLM, no symbol required."""
    label = f"「{theme}」因子" if theme else "因子库"
    yield PhaseMarker("factors", f"列出{label}")
    data = await list_factors_for_agent(theme=theme, limit=20)
    rows = data.get("factors") or []
    if not rows:
        body = (
            f"## {label}（0 个）\n\n"
            f"暂无匹配因子。可对话说「用 LLM 帮我挖 2 个{'动量' if not theme else theme}因子」，"
            "或在 库 → 因子 Tab 查看。"
        )
    else:
        lines = ["| ID | 名称 | 状态 | 来源 | 股票池 | IC | ICIR |", "|---|---|---|---|---|---:|---:|"]
        for r in rows:
            lines.append(
                f"| `{r.get('id','')}` | {r.get('name','')} | {r.get('status','')} | "
                f"{r.get('origin','')} | {r.get('universe','')} | "
                f"{_fmt_num(r.get('ic_mean'))} | {_fmt_num(r.get('icir'))} |"
            )
        body = f"## {label}（{len(rows)} 个）\n\n" + "\n".join(lines) + (
            "\n\n可继续说：「用因子从沪深300选出 20 只」或「用 LLM 帮我挖 2 个动量因子」。"
        )
    yield AnalysisStep(
        id=uuid4().hex[:12],
        agent="list_factors",
        role="assistant",
        result=body,
    )


async def run_factor_mine_pipeline(plan: dict[str, Any]) -> AsyncIterator[StreamItem]:
    """Start LLM or GP factor mining — no supervisor LLM."""
    mode = str(plan.get("mode") or "llm")
    use_synthetic = bool(plan.get("use_synthetic", True))
    universe = str(plan.get("universe") or "csi300")

    if mode == "gp":
        track = str(plan.get("track") or "market")
        label = "GP 截面选股" if track == "cs" else "GP 大盘择时"
        yield PhaseMarker("mine", f"启动{label}挖掘")
        body = FactorMineGpRequest(
            track=track,  # type: ignore[arg-type]
            universe=universe,  # type: ignore[arg-type]
            use_synthetic=use_synthetic,
        )
        result = await schedule_gp_mine(body)
        agent = "start_factor_mine_gp"
    else:
        k = int(plan.get("k") or 3)
        rounds = int(plan.get("rounds") or 2)
        theme_hint = str(plan.get("theme_hint") or "")
        yield PhaseMarker("mine", "启动 LLM 因子挖掘")
        body = FactorMineLlmRequest(
            universe=universe,  # type: ignore[arg-type]
            k=k,
            rounds=rounds,
            theme_hint=theme_hint,
            use_synthetic=use_synthetic,
        )
        result = await schedule_llm_mine(body)
        agent = "start_factor_mine_llm"

    yield AnalysisStep(
        id=uuid4().hex[:12],
        agent=agent,
        role="tool",
        result=json.dumps(result, ensure_ascii=False),
    )

    if result.get("status") == "error":
        summary = f"挖掘未能启动：{result.get('error', '未知错误')}"
    else:
        run_id = result.get("run_id", "")
        kind = result.get("kind", mode)
        summary = (
            f"## 因子挖掘已启动\n\n"
            f"- **run_id**: `{run_id}`\n"
            f"- **类型**: {kind}\n"
            f"- {result.get('message', '顶部进度条可查看漏斗状态')}\n\n"
            "完成后新因子出现在 **库 → 因子**；可说「有哪些动量因子」查看列表。"
        )

    yield AnalysisStep(
        id=uuid4().hex[:12],
        agent=agent,
        role="assistant",
        result=summary,
    )


async def run_ingest_policy_pipeline(plan: dict[str, Any]) -> AsyncIterator[StreamItem]:
    """Ingest pasted policy/research text — no supervisor LLM."""
    title = str(plan.get("title") or "政策文档")
    content = str(plan.get("content") or "")
    symbol = plan.get("symbol")
    theme = plan.get("theme")

    yield PhaseMarker("knowledge", "政策文本入库")

    if len(content.strip()) < 10:
        body = (
            "## 需要粘贴正文\n\n"
            "已识别入库意图，但消息里缺少足够长的政策/监管正文。\n\n"
            "请按以下格式发送：\n"
            "```\n"
            "把这段监管条文入库：\n"
            "标题：关于信息披露的监管要求\n"
            "内容：\n"
            "第一条 …\n"
            "第二条 …\n"
            "```\n\n"
            "也可用《文件标题》包裹标题，正文换行粘贴。"
        )
        yield AnalysisStep(
            id=uuid4().hex[:12],
            agent="ingest_policy_text",
            role="assistant",
            result=body,
        )
        return

    result = await ingest_text_document(
        title=title,
        content=content,
        symbol=symbol if isinstance(symbol, str) and symbol else None,
        theme=theme if isinstance(theme, str) and theme else None,
        source="nl_ingest",
    )

    yield AnalysisStep(
        id=uuid4().hex[:12],
        agent="ingest_policy_text",
        role="tool",
        result=json.dumps(result, ensure_ascii=False),
    )

    if result.get("status") != "ok":
        summary = f"入库失败：{result.get('message', '未知错误')}"
    else:
        summary = (
            f"## 政策文档已入库\n\n"
            f"- **doc_id**: `{result.get('doc_id')}`\n"
            f"- **标题**: {result.get('title', title)}\n"
            f"- **切块**: {result.get('chunk_count', 0)}（向量化 {result.get('indexed_chunks', 0)}）\n\n"
            "可说「检索政策：减持新规」或到 **库 → 知识** 查看。"
        )

    yield AnalysisStep(
        id=uuid4().hex[:12],
        agent="ingest_policy_text",
        role="assistant",
        result=summary,
    )


async def run_cancel_analysis_pipeline(*, path_id: str) -> AsyncIterator[StreamItem]:
    """Cancel in-flight analysis tasks — no supervisor LLM."""
    yield PhaseMarker("cancel", "取消分析任务")

    cancelled: list[str] = []
    for pid in analysis_registry.active_ids():
        if pid == path_id:
            continue
        if analysis_registry.cancel(pid):
            cancelled.append(pid)

    if cancelled:
        ids = "、".join(f"`{p}`" for p in cancelled[:5])
        body = (
            f"## 已请求取消 {len(cancelled)} 个任务\n\n"
            f"{ids}\n\n"
            "进行中的流会在下一步检查点结束。当前会话也可点 **停止** 按钮。"
        )
    else:
        body = (
            "## 当前无进行中的分析\n\n"
            "没有发现其他正在运行的分析任务。"
            "分析进行时也可直接点对话区的 **停止** 按钮。"
        )

    yield AnalysisStep(
        id=uuid4().hex[:12],
        agent="cancel_analysis",
        role="assistant",
        result=body,
    )


_KNOWLEDGE_TYPE_LABEL = {
    "policy": "政策/研报",
    "sentiment": "舆情",
    "breadth": "大盘宽度",
}


async def run_search_knowledge_pipeline(plan: dict[str, Any]) -> AsyncIterator[StreamItem]:
    """Semantic search over archived knowledge — no supervisor LLM."""
    query = str(plan.get("query") or "").strip()
    knowledge_type = str(plan.get("knowledge_type") or "policy")
    symbol = plan.get("symbol")
    limit = int(plan.get("limit") or 5)
    type_label = _KNOWLEDGE_TYPE_LABEL.get(knowledge_type, knowledge_type)

    yield PhaseMarker("knowledge", f"检索{type_label}知识库")

    if not query:
        body = (
            "## 需要检索关键词\n\n"
            "已识别知识库检索意图，但缺少查询词。请按以下格式发送：\n"
            "```\n"
            "检索政策：减持新规\n"
            "搜索舆情：茅台中报\n"
            "检索知识：信披监管要求\n"
            "```"
        )
        yield AnalysisStep(
            id=uuid4().hex[:12],
            agent="search_knowledge",
            role="assistant",
            result=body,
        )
        return

    result = await search_knowledge(
        query,
        symbol=symbol if isinstance(symbol, str) and symbol else None,
        knowledge_type=knowledge_type,
        limit=limit,
    )

    yield AnalysisStep(
        id=uuid4().hex[:12],
        agent="search_knowledge",
        role="tool",
        result=json.dumps(result, ensure_ascii=False),
    )

    hits = result.get("hits") or []
    if not hits:
        summary = (
            f"## 知识库检索（0 条）\n\n"
            f"- **查询**: {query}\n"
            f"- **类型**: {type_label}\n\n"
            "未命中记录。可先「把这段监管条文入库」写入政策，或等待舆情归档。"
        )
    else:
        lines = ["| 相关度 | 摘要 | 来源 | 时间 |", "|---:|---|---|---|"]
        for h in hits:
            text = str(h.get("text") or "")[:120].replace("|", " ")
            score = h.get("score")
            score_s = f"{float(score):.2f}" if score is not None else "—"
            src = h.get("source") or h.get("event_id") or "—"
            ts = h.get("ts") or "—"
            if isinstance(ts, str) and len(ts) > 10:
                ts = ts[:10]
            lines.append(f"| {score_s} | {text} | {src} | {ts} |")
        summary = (
            f"## 知识库检索（{len(hits)} 条）\n\n"
            f"- **查询**: {query}\n"
            f"- **类型**: {type_label}\n\n"
            + "\n".join(lines)
        )

    yield AnalysisStep(
        id=uuid4().hex[:12],
        agent="search_knowledge",
        role="assistant",
        result=summary,
    )
