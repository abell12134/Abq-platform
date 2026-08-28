from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool, tool

from app.data.announcements import fetch_announcements as fetch_announcements_data
from app.data.bar_processing import calc_indicators, clean_bars
from app.data.announcements import fetch_announcements as fetch_announcements_data
from app.data.fundamentals import fetch_fundamentals as fetch_fundamentals_data
from app.data.ohlcv import fetch_ohlcv as fetch_ohlcv_data
from app.data.quotes_realtime import fetch_quote as fetch_quote_data
from app.data.sector_pulse import fetch_market_breadth as fetch_market_breadth_data
from app.data.sector_pulse import fetch_sector_pulse as fetch_sector_pulse_data
from app.data.sentiment import fetch_sentiment as fetch_sentiment_data
from app.factors.agent_tools import (
    compute_factor_snapshot,
    factor_analysis_summary,
    list_factors_for_agent,
)
from app.factors.mine_tools import mine_status, schedule_gp_mine, schedule_llm_mine
from app.factors.screener import apply_screen_to_portfolio as apply_screen_impl
from app.factors.screener import run_factor_screen as run_factor_screen_impl
from app.knowledge.delta import compute_knowledge_delta
from app.knowledge.ingest import ingest_text_document
from app.graph.queries import query_graph_subgraph
from app.memory.episodic import search_episodes as search_episodes_impl
from app.memory.search import search_knowledge as search_knowledge_impl
from app.memory.search import search_prior_analysis as search_prior_analysis_impl
from app.models.factors import (
    FactorMineGpRequest,
    FactorMineLlmRequest,
    FactorScreenApplyRequest,
    FactorScreenRequest,
)
from app.models.portfolio import PortfolioMember, PortfolioUpdate
from app.orchestration.analysis_registry import analysis_registry
from app.persistence.portfolio_store import PortfolioStoreError, portfolio_store
from app.tools.envelope import tool_err, tool_ok


@tool
async def fetch_ohlcv(symbol: str, limit: int = 30) -> dict[str, Any]:
    """获取 A 股日 K（open/high/low/close/volume）。优先本地 qlib；若末日落后于当前日期，自动从腾讯/东财/baostock 补全缺口。"""
    return await fetch_ohlcv_data(symbol, limit=limit)


@tool
async def fetch_quote(symbol: str) -> dict[str, Any]:
    """获取 A 股实时行情（现价、涨跌幅、开高低、成交量等）。"""
    return await fetch_quote_data(symbol)


@tool
async def clean_data(bars: list[dict[str, Any]]) -> dict[str, Any]:
    """清洗 OHLCV：去重、去无效行、按日期排序。输入为 fetch_ohlcv 返回的 bars 数组。"""
    cleaned = clean_bars(bars)
    return {"source": "clean_data", **cleaned}


@tool
async def calc_indicator(bars: list[dict[str, Any]]) -> dict[str, Any]:
    """基于清洗后 K 线计算均线、涨跌幅、量比等常用技术指标。"""
    indicators = calc_indicators(bars)
    return {"source": "calc_indicator", **indicators}


@tool
async def fetch_fundamentals(symbol: str) -> dict[str, Any]:
    """获取公司财报、公告等基本面数据（报告期、同比环比等）。"""
    return await fetch_fundamentals_data(symbol)


@tool
async def fetch_sentiment(symbol: str, limit: int = 10) -> dict[str, Any]:
    """获取舆情新闻头条与情绪摘要。"""
    return await fetch_sentiment_data(symbol, limit=limit)


@tool
async def fetch_announcements(symbol: str, limit: int = 8) -> dict[str, Any]:
    """获取个股正式公告（巨潮/东财），含公告标题、类型、日期与链接。"""
    from app.config import settings

    return await fetch_announcements_data(
        symbol,
        limit=limit,
        days=settings.graph_announcement_days,
    )


@tool
async def fetch_market_breadth() -> dict[str, Any]:
    """获取市场宽度：主要指数涨跌与涨停池规模（东财）。"""
    return await fetch_market_breadth_data()


@tool
async def fetch_sector_pulse(theme_hint: str = "") -> dict[str, Any]:
    """获取板块脉冲：行业涨跌榜与主题匹配（theme_hint 可填板块关键词）。"""
    return await fetch_sector_pulse_data(theme_hint=theme_hint)


@tool
async def list_factors(status: str = "", theme: str = "", limit: int = 20) -> dict[str, Any]:
    """列出因子库因子（id、名称、状态、IC 摘要）。status 为空时默认 live/paper_tracking/passed_auto。"""
    return await list_factors_for_agent(
        status=status.strip() or None,
        theme=theme.strip() or None,
        limit=limit,
    )


@tool
async def compute_factor(factor_id: str, symbol: str) -> dict[str, Any]:
    """计算指定因子在某股票上的最新值；截面因子含截面分位，择时因子返回大盘序列最新值。"""
    return await compute_factor_snapshot(factor_id, symbol)


@tool
async def factor_analysis(factor_id: str) -> dict[str, Any]:
    """读取因子最近一次准入评测的 IC 指标与闸门结果（只读摘要，不含面板）。"""
    return factor_analysis_summary(factor_id)


@tool
async def start_factor_mine_llm(
    universe: str = "csi300",
    rounds: int = 2,
    k: int = 3,
    theme_hint: str = "",
    use_synthetic: bool = True,
) -> dict[str, Any]:
    """启动 LLM 因子挖掘（后台任务）。返回 run_id；用 get_factor_mine_status 查进度。"""
    body = FactorMineLlmRequest(
        universe=universe,  # type: ignore[arg-type]
        rounds=rounds,
        k=k,
        theme_hint=theme_hint,
        use_synthetic=use_synthetic,
    )
    return await schedule_llm_mine(body)


@tool
async def start_factor_mine_gp(
    track: str = "market",
    universe: str = "csi300",
    population: int = 80,
    generations: int = 8,
    use_synthetic: bool = True,
) -> dict[str, Any]:
    """启动 GP 因子挖掘：track=market 大盘择时 / track=cs 截面。返回 run_id。"""
    body = FactorMineGpRequest(
        track=track,  # type: ignore[arg-type]
        universe=universe,  # type: ignore[arg-type]
        population=population,
        generations=generations,
        use_synthetic=use_synthetic,
    )
    return await schedule_gp_mine(body)


@tool
async def run_factor_screen(
    universe: str = "csi300",
    factor_ids: str = "",
    method: str = "ic_ir",
    top_n: int = 20,
    use_synthetic: bool = False,
) -> dict[str, Any]:
    """对股票池做截面因子选股，返回按综合得分排序的 Top N 列表。factor_ids 逗号分隔，留空则自动选 live/passed 因子。"""
    ids = [x.strip() for x in factor_ids.split(",") if x.strip()] if factor_ids.strip() else []
    body = FactorScreenRequest(
        universe=universe,  # type: ignore[arg-type]
        factor_ids=ids,
        method=method,  # type: ignore[arg-type]
        top_n=top_n,
        use_synthetic=use_synthetic,
    )
    return await run_factor_screen_impl(body)


@tool
async def apply_screen_to_portfolio(
    symbols: str,
    portfolio_id: str = "default",
    mode: str = "merge",
) -> dict[str, Any]:
    """将选股结果导入组合。symbols 逗号分隔代码；mode=merge 去重追加，replace 替换全部成员。"""
    ids = [x.strip() for x in symbols.split(",") if x.strip()]
    body = FactorScreenApplyRequest(
        portfolio_id=portfolio_id.strip() or "default",
        symbols=ids,
        mode=mode if mode in ("merge", "replace") else "merge",  # type: ignore[arg-type]
    )
    try:
        return apply_screen_impl(body)
    except FileNotFoundError:
        return tool_err(f"组合不存在: {body.portfolio_id}", suggested_action="先调用 list_portfolios")
    except (ValueError, PortfolioStoreError) as exc:
        return tool_err(str(exc))


@tool
async def list_portfolios() -> dict[str, Any]:
    """列出全部自选组合（id、名称、成员数量与代码）。"""
    portfolio_store.ensure()
    items = []
    for rec in portfolio_store.list_portfolios():
        items.append(
            {
                "id": rec.id,
                "name": rec.name,
                "member_count": len(rec.members),
                "symbols": [m.symbol for m in rec.members],
            }
        )
    return tool_ok(
        {"portfolios": items},
        summary=f"{len(items)} 个组合",
        next_hints=["可用 apply_screen_to_portfolio 导入选股结果"],
    )


@tool
async def update_portfolio(
    portfolio_id: str,
    name: str = "",
    symbols: str = "",
) -> dict[str, Any]:
    """更新组合名称或成员。symbols 逗号分隔；留空则只改名称。"""
    rec = portfolio_store.get(portfolio_id.strip() or "default")
    if rec is None:
        return tool_err(f"组合不存在: {portfolio_id}", suggested_action="先调用 list_portfolios")
    members = None
    if symbols.strip():
        from app.data.qlib_store import normalize_symbol

        members = [PortfolioMember(symbol=normalize_symbol(s.strip())) for s in symbols.split(",") if s.strip()]
    try:
        updated = portfolio_store.update(
            rec.id,
            PortfolioUpdate(name=name.strip() or None, members=members),
        )
    except (FileNotFoundError, PortfolioStoreError) as exc:
        return tool_err(str(exc))
    return tool_ok(
        {
            "portfolio_id": updated.id,
            "name": updated.name,
            "member_count": len(updated.members),
            "symbols": [m.symbol for m in updated.members],
        },
        summary=f"已更新组合 {updated.name}",
    )


@tool
async def cancel_analysis(path_id: str = "") -> dict[str, Any]:
    """取消当前进行中的分析任务。path_id 为空则取消所有进行中的分析。"""
    pid = path_id.strip()
    if pid:
        ok = analysis_registry.cancel(pid)
        return tool_ok({"cancelled": ok, "path_id": pid}, summary="已请求取消" if ok else "任务不在运行")
    cancelled = analysis_registry.cancel_all()
    return tool_ok({"cancelled_ids": cancelled}, summary=f"已取消 {len(cancelled)} 个任务")


@tool
async def get_factor_mine_status(run_id: str = "") -> dict[str, Any]:
    """查询因子挖掘任务进度；run_id 为空则查当前活跃任务。"""
    return mine_status(run_id.strip() or None)


@tool
async def search_prior_analysis(
    symbol: str = "",
    kind: str = "",
    query: str = "",
    since_days: int = 30,
    limit: int = 5,
) -> dict[str, Any]:
    """检索历史研判摘要（跨会话）。symbol 填股票代码；query 可填语义关键词。"""
    return await search_prior_analysis_impl(
        symbol=symbol.strip() or None,
        kind=kind.strip() or None,
        query=query.strip() or None,
        since_days=since_days,
        limit=limit,
    )


@tool
async def get_knowledge_delta(
    symbol: str,
    type: str = "sentiment",
    since_days: int = 7,
) -> dict[str, Any]:
    """对比归档知识库的增量变化（舆情标题或大盘宽度）。type=sentiment|breadth。"""
    result = await compute_knowledge_delta(
        type,  # type: ignore[arg-type]
        symbol=symbol.strip() or None,
        since_days=since_days,
    )
    return result.model_dump()


@tool
async def search_knowledge(
    query: str,
    symbol: str = "",
    type: str = "sentiment",
    limit: int = 5,
) -> dict[str, Any]:
    """语义检索归档知识库（舆情摘要、大盘宽度记录、政策文档等）。"""
    return await search_knowledge_impl(
        query,
        symbol=symbol.strip() or None,
        knowledge_type=type,
        limit=limit,
    )


@tool
async def ingest_policy_text(
    title: str,
    content: str,
    symbol: str = "",
    theme: str = "",
) -> dict[str, Any]:
    """将政策/研报文本入库并向量化，供 search_knowledge(type=policy) 检索。"""
    return await ingest_text_document(
        title=title.strip(),
        content=content,
        symbol=symbol.strip() or None,
        theme=theme.strip() or None,
        source="agent_tool",
    )


@tool
async def ingest_policy_url(
    url: str,
    title: str = "",
    symbol: str = "",
    theme: str = "",
    issuer: str = "",
) -> dict[str, Any]:
    """从白名单监管官网 URL 抓取政策并入库（证监会/交易所/国务院等）。限速抓取。"""
    from app.knowledge.policy_fetcher import ingest_policy_from_url

    return await ingest_policy_from_url(
        url.strip(),
        title=title.strip() or None,
        symbol=symbol.strip() or None,
        theme=theme.strip() or None,
        issuer=issuer.strip() or None,
    )


@tool
async def query_graph(
    center: str,
    hops: int = 1,
) -> dict[str, Any]:
    """查询本地知识图谱子图：股票关联的行业、新闻、政策等。center 填股票代码如 sh600519。"""
    return query_graph_subgraph(center.strip(), hops=max(1, min(hops, 3)))


@tool
async def search_episodes(
    query: str,
    symbol: str = "",
    limit: int = 5,
) -> dict[str, Any]:
    """检索历史研判经验（episodic memory）：情境、推理与教训摘要。"""
    return await search_episodes_impl(
        query,
        symbol=symbol.strip() or None,
        limit=limit,
    )


ALL_TOOLS: list[BaseTool] = [
    fetch_ohlcv,
    fetch_quote,
    clean_data,
    calc_indicator,
    fetch_fundamentals,
    fetch_sentiment,
    fetch_announcements,
    fetch_market_breadth,
    fetch_sector_pulse,
    list_factors,
    compute_factor,
    factor_analysis,
    start_factor_mine_llm,
    start_factor_mine_gp,
    get_factor_mine_status,
    run_factor_screen,
    apply_screen_to_portfolio,
    list_portfolios,
    update_portfolio,
    cancel_analysis,
    search_prior_analysis,
    get_knowledge_delta,
    search_knowledge,
    ingest_policy_text,
    ingest_policy_url,
    query_graph,
    search_episodes,
]

TOOL_BY_NAME: dict[str, BaseTool] = {t.name: t for t in ALL_TOOLS}
