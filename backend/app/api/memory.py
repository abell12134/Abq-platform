from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.memory.indexer import reindex_all
from app.memory.preview import build_memory_preview
from app.memory.search import search_knowledge, search_prior_analysis

router = APIRouter(prefix="/memory", tags=["memory"])


class ReindexRequest(BaseModel):
    scope: str = Field(default="all", pattern="^(all|paths|knowledge)$")


class MemoryPreviewRequest(BaseModel):
    message: str
    kind: str = "single"
    symbol: str | None = None
    focus: str | None = None


@router.get("/search")
async def memory_search(
    q: str,
    namespace: str = Query("knowledge", pattern="^(knowledge|paths)$"),
    symbol: str | None = None,
    kind: str | None = None,
    type: str = "sentiment",
    limit: int = 5,
) -> dict:
    if namespace == "paths":
        return await search_prior_analysis(
            symbol=symbol,
            kind=kind,
            query=q,
            limit=limit,
        )
    return await search_knowledge(q, symbol=symbol, knowledge_type=type, limit=limit)


@router.post("/reindex")
async def memory_reindex(body: ReindexRequest) -> dict:
    return await reindex_all(scope=body.scope)


@router.post("/preview")
async def memory_preview(body: MemoryPreviewRequest) -> dict:
    return await build_memory_preview(
        message=body.message,
        kind=body.kind,
        symbol=body.symbol,
        focus=body.focus,
    )


@router.get("/preview")
async def memory_preview_get(
    message: str,
    kind: str = "single",
    symbol: str | None = None,
    focus: str | None = None,
) -> dict:
    return await build_memory_preview(
        message=message,
        kind=kind,
        symbol=symbol,
        focus=focus,
    )
