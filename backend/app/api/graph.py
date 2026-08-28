from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.config import settings
from app.graph.builder import bootstrap_csi300_skeleton
from app.graph.models import SubgraphResult
from app.graph.store import graph_store
from app.graph.summarizer import rollup_current_month_for_symbols, rollup_period
from app.graph.batch_sync import sync_csi300_month
from app.graph.maintenance import run_scheduled_maintenance
from app.graph.sync import sync_incremental, sync_market_layer, sync_sample_stocks
from app.knowledge.policy_sync import sync_policy_sources

router = APIRouter(prefix="/graph", tags=["graph"])


class RollupBody(BaseModel):
    period: str = Field(..., description="YYYY-MM")
    scope: str = Field("symbol", description="symbol | sector | market")
    key: str = Field(..., description="股票代码或 market")
    use_llm: bool | None = None
    force: bool = False


@router.get("/stats")
async def graph_stats() -> dict:
    graph_store.ensure()
    return graph_store.stats().model_dump()


@router.get("/subgraph")
async def graph_subgraph(
    center: str = Query(..., description="股票代码或节点 id，如 sh600519"),
    hops: int = Query(1, ge=1, le=3),
    max_nodes: int = Query(80, ge=10, le=200),
) -> dict:
    graph_store.ensure()
    result: SubgraphResult = graph_store.subgraph(center, hops=hops, max_nodes=max_nodes)
    return result.model_dump()


@router.post("/bootstrap")
async def graph_bootstrap(max_symbols: int = Query(300, ge=10, le=300)) -> dict:
    """仅建 CSI300 骨架（股—指数边），不拉舆情/基本面。"""
    if not settings.graph_enabled:
        return {"status": "disabled", "message": "GRAPH_ENABLED=false"}
    return await bootstrap_csi300_skeleton(max_symbols=max_symbols)


@router.post("/sync")
async def graph_sync(
    symbols: str = Query("", description="逗号分隔代码；留空则用配置的样本股"),
    force: bool = Query(False, description="忽略冷却期（仍遵守请求间隔）"),
    bootstrap: bool = Query(True, description="同步前是否确保 CSI300 骨架存在"),
) -> dict:
    """
    限速拉取样本股基本面 + 舆情，写入图谱与 knowledge 归档。
    默认只同步 GRAPH_SYNC_SAMPLE_SYMBOLS 中的几只，避免频繁爬取。
    """
    if not settings.graph_enabled:
        return {"status": "disabled", "message": "GRAPH_ENABLED=false"}
    parsed = [s.strip() for s in symbols.split(",") if s.strip()] if symbols else None
    result = await sync_sample_stocks(parsed, force=force, bootstrap=bootstrap)
    return result.model_dump()


@router.post("/rollup")
async def graph_rollup(body: RollupBody) -> dict:
    """按月汇总归档事件为 Digest 节点（LLM 摘要，失败则规则降级）。"""
    if not settings.graph_enabled:
        return {"status": "disabled", "message": "GRAPH_ENABLED=false"}
    scope = body.scope if body.scope in ("symbol", "market", "sector") else "symbol"
    result = await rollup_period(
        body.period,
        scope=scope,  # type: ignore[arg-type]
        key=body.key,
        use_llm=body.use_llm,
        force=body.force,
    )
    return result.model_dump()


@router.post("/rollup/month")
async def graph_rollup_current_month(
    symbols: str = Query("", description="逗号分隔；留空则用样本股"),
) -> dict:
    if not settings.graph_enabled:
        return {"status": "disabled", "message": "GRAPH_ENABLED=false"}
    from app.graph.builder import default_sample_symbols

    parsed = [s.strip() for s in symbols.split(",") if s.strip()] if symbols else default_sample_symbols()
    results = await rollup_current_month_for_symbols(parsed)
    return {
        "status": "ok",
        "period": results[0].period if results else None,
        "results": [r.model_dump() for r in results],
    }


@router.post("/sync/market")
async def graph_sync_market(force: bool = Query(False)) -> dict:
    """同步市场/宏观层（北向、两融、宽度、宏观指标）。"""
    if not settings.graph_enabled:
        return {"status": "disabled", "message": "GRAPH_ENABLED=false"}
    return await sync_market_layer(force=force)


@router.post("/sync/incremental")
async def graph_sync_incremental(
    symbol: str = Query(..., description="股票代码"),
    force: bool = Query(False, description="忽略冷却与摘要去重"),
) -> dict:
    """单股增量更新（推荐）：冷却期内跳过爬取，无新事件不重复生成摘要。"""
    if not settings.graph_enabled:
        return {"status": "disabled", "message": "GRAPH_ENABLED=false"}
    return await sync_incremental(symbol, force=force)


@router.post("/sync/csi300")
async def graph_sync_csi300(
    period: str = Query("", description="YYYY-MM，默认当月"),
    force: bool = Query(False),
    symbol_rollup_llm: bool = Query(False, description="对 300 股逐只 LLM 摘要（慢且贵）"),
) -> dict:
    """
    CSI300 全成分股限速同步 + 各板块/大盘本月 Rollup。
    预计 45–90 分钟（300 股 × 3 次请求 × 3s 间隔）。
    """
    if not settings.graph_enabled:
        return {"status": "disabled", "message": "GRAPH_ENABLED=false"}
    return await sync_csi300_month(
        period=period or None,
        force=force,
        symbol_rollup_llm=symbol_rollup_llm,
    )


@router.post("/policy/sync")
async def graph_policy_sync(
    source_id: str = Query("", description="policy_sources.yaml 中的 id"),
    max_total: int = Query(0, ge=0, le=20),
) -> dict:
    """增量同步政策列表页（白名单 + 限速）。"""
    return await sync_policy_sources(
        source_id=source_id or None,
        max_total=max_total or None,
    )


@router.post("/maintenance")
async def graph_maintenance() -> dict:
    """手动触发：jsonl 归档 + 月 Rollup + 政策同步。"""
    if not settings.graph_enabled:
        return {"status": "disabled", "message": "GRAPH_ENABLED=false"}
    return await run_scheduled_maintenance()


@router.post("/extract")
async def graph_extract_triples(
    symbol: str = Query(..., description="股票代码"),
) -> dict:
    """对单股重新运行 LLM 产业链三元组抽取。"""
    from app.graph.extractor import extract_supply_chain_triples
    from app.graph.store import stock_node_id
    from app.knowledge.archiver import list_events

    sym = symbol.strip().lower()
    node = graph_store.get_node(stock_node_id(sym))
    titles: list[str] = []
    for etype in ("sentiment", "announcement"):
        for ev in await list_events(etype, symbol=sym, limit=20):
            for row in ev.headlines:
                t = row.get("新闻标题") or row.get("公告标题") or row.get("title")
                if t:
                    titles.append(str(t))
    return await extract_supply_chain_triples(
        sym,
        company_name=(node.label if node else sym),
        evidence_titles=titles,
    )
