import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from app.models.analysis import AnalyzeRequest, SseEvent
from app.orchestration.analysis_registry import analysis_registry
from app.orchestration.analyze_stream import analyze_stream as run_analyze_stream
from app.persistence.paths import path_store

router = APIRouter(tags=["analyze"])


@router.post("/analyze/stream")
async def analyze_stream_endpoint(req: AnalyzeRequest) -> EventSourceResponse:
    async def event_generator() -> AsyncIterator[dict]:
        try:
            async for event in run_analyze_stream(req):
                yield {"data": json.dumps(event.model_dump(mode="json", exclude_none=True), ensure_ascii=False)}
        except Exception as exc:  # noqa: BLE001
            err = SseEvent(type="error", message=str(exc))
            yield {"data": json.dumps(err.model_dump(mode="json", exclude_none=True), ensure_ascii=False)}

    return EventSourceResponse(event_generator())


@router.post("/analyze/cancel/{path_id}")
async def cancel_analysis(path_id: str) -> dict:
    entry = await path_store.get_entry(path_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="path not found")

    cancelled = analysis_registry.cancel(path_id)
    if cancelled:
        return {"ok": True, "id": path_id, "cancelled": True}

    if entry.status == "running":
        await path_store.update_status(path_id, "error")
        return {"ok": True, "id": path_id, "cancelled": False, "cleared": True}

    return {"ok": True, "id": path_id, "cancelled": False}
