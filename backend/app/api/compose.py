from fastapi import APIRouter

from app.models.analysis import AnalyzeRequest
from app.orchestration.compose_route import route_compose

router = APIRouter(prefix="/compose", tags=["compose"])


@router.post("/route")
async def compose_route(body: AnalyzeRequest) -> dict:
    return route_compose(body.message, focus=body.focus, kind=body.kind)
