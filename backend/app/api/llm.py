from fastapi import APIRouter, Query

from app.llm.embedding_client import embedding_client
from app.llm.reranker_client import reranker_client
from app.llm.router import llm_router

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/health")
async def llm_health(probe: bool = Query(False, description="Run live embedding/reranker probes")) -> dict:
    health = await llm_router.health()
    health["embedding"] = await embedding_client.health(probe=probe)
    health["reranker"] = await reranker_client.health(probe=probe)
    return health


@router.get("/providers")
async def llm_providers() -> dict:
    return {"providers": llm_router.list_providers()}
