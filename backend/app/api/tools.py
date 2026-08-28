from fastapi import APIRouter

from app.persistence.library_store import library_store

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("")
async def list_tools() -> dict:
    tools = library_store.list_tools()
    return {"tools": [t.model_dump() for t in tools]}
