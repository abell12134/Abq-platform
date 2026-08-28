import asyncio

from fastapi import APIRouter, HTTPException, Query

from app.orchestration.analysis_registry import analysis_registry
from app.persistence.paths import path_store

router = APIRouter(prefix="/paths", tags=["paths"])


@router.get("/search")
async def list_paths_search(
    symbol: str | None = None,
    kind: str | None = None,
    since: str | None = None,
    limit: int = Query(10, ge=1, le=50),
) -> dict:
    entries = await path_store.search_entries(symbol=symbol, kind=kind, since=since, limit=limit)
    return {"paths": [e.model_dump() for e in entries]}


@router.get("")
async def list_paths() -> dict:
    await path_store.ensure()
    entries = await path_store.list_entries()
    return {"paths": [e.model_dump() for e in entries]}


@router.get("/{path_id}")
async def get_path(path_id: str) -> dict:
    doc = await path_store.get_path(path_id)
    if not doc:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="path not found")
    doc["snapshots"] = await path_store.load_snapshots(path_id)
    doc["reports"] = await path_store.load_reports(path_id)
    return doc


@router.delete("/{path_id}")
async def delete_path(path_id: str, force: bool = Query(False)) -> dict:
    entry = await path_store.get_entry(path_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="path not found")
    if force:
        analysis_registry.cancel(path_id)
        for _ in range(30):
            if not analysis_registry.is_active(path_id):
                break
            await asyncio.sleep(0.1)
        if entry.status == "running":
            await path_store.update_status(path_id, "error")
    elif await path_store.is_actively_running(path_id):
        raise HTTPException(status_code=409, detail="会话仍在分析中，请稍后再删")
    ok = await path_store.delete_entry(path_id)
    if not ok:
        raise HTTPException(status_code=404, detail="path not found")
    return {"ok": True, "id": path_id}
