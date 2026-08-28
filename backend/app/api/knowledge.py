from fastapi import APIRouter, File, Form, Query, UploadFile
from pydantic import BaseModel, Field

from app.knowledge.archiver import list_events
from app.knowledge.delta import compute_knowledge_delta
from app.knowledge.ingest import ingest_file_upload, ingest_text_document, list_policy_documents
from app.knowledge.models import KnowledgeType
from app.knowledge.policy_fetcher import ingest_policy_from_url, load_allowed_hosts

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class PolicyUrlIngestBody(BaseModel):
    url: str = Field(..., min_length=8)
    title: str = ""
    symbol: str = ""
    theme: str = ""
    issuer: str = ""


@router.get("/delta")
async def knowledge_delta(
    type: KnowledgeType = Query("sentiment"),
    symbol: str | None = None,
    theme: str | None = None,
    since_days: int = Query(7, ge=1, le=90),
) -> dict:
    result = await compute_knowledge_delta(
        type,
        symbol=symbol,
        theme=theme,
        since_days=since_days,
    )
    return result.model_dump()


@router.get("/events")
async def knowledge_events(
    type: KnowledgeType = Query("sentiment"),
    symbol: str | None = None,
    theme: str | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    events = await list_events(type, symbol=symbol, theme=theme, limit=limit)
    return {"events": [e.model_dump() for e in events]}


@router.get("/policy")
async def knowledge_policy_list() -> dict:
    docs = await list_policy_documents()
    return {"documents": docs}


@router.get("/policy/hosts")
async def knowledge_policy_hosts() -> dict:
    return {"hosts": sorted(load_allowed_hosts())}


@router.post("/ingest/url")
async def knowledge_ingest_url(body: PolicyUrlIngestBody) -> dict:
    """从白名单官网 URL 抓取政策正文并入库（限速，防 SSRF）。"""
    return await ingest_policy_from_url(
        body.url.strip(),
        title=body.title.strip() or None,
        symbol=body.symbol.strip() or None,
        theme=body.theme.strip() or None,
        issuer=body.issuer.strip() or None,
    )


@router.post("/ingest")
async def knowledge_ingest(
    file: UploadFile = File(...),
    title: str = Form(""),
    symbol: str = Form(""),
    theme: str = Form(""),
) -> dict:
    data = await file.read()
    if not data:
        return {"status": "error", "message": "空文件"}
    return await ingest_file_upload(
        filename=file.filename or "document.txt",
        data=data,
        title=title or None,
        symbol=symbol.strip() or None,
        theme=theme.strip() or None,
    )


@router.post("/ingest/text")
async def knowledge_ingest_text(
    title: str = Form(...),
    content: str = Form(...),
    symbol: str = Form(""),
    theme: str = Form(""),
) -> dict:
    return await ingest_text_document(
        title=title.strip(),
        content=content,
        symbol=symbol.strip() or None,
        theme=theme.strip() or None,
        source="api_text",
    )
