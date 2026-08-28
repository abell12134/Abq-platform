from fastapi import APIRouter, HTTPException, Query

from app.models.library import AgentCreate, AgentDetail, AgentRecord, AgentUpdate
from app.persistence.library_store import LibraryValidationError, library_store
from app.prompts.loader import load_agent

router = APIRouter(prefix="/agents", tags=["agents"])


def _validation_error(exc: LibraryValidationError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("")
async def list_agents() -> dict:
    library_store.ensure()
    agents = library_store.list_agents()
    return {"agents": [a.model_dump() for a in agents]}


@router.get("/{agent_id}")
async def get_agent(
    agent_id: str,
    expand: bool = Query(False, description="Include resolved persona/instructions"),
) -> AgentDetail | AgentRecord:
    record = library_store.get_agent(agent_id)
    if record is None:
        raise HTTPException(status_code=404, detail="agent not found")
    if not expand:
        return record
    try:
        spec = load_agent(agent_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="agent not found") from exc
    return AgentDetail(
        **record.model_dump(),
        persona=spec.persona,
        instructions=spec.instructions,
    )


@router.post("")
async def create_agent(body: AgentCreate) -> AgentRecord:
    try:
        return library_store.create_agent(body)
    except LibraryValidationError as exc:
        raise _validation_error(exc) from exc


@router.put("/{agent_id}")
async def update_agent(agent_id: str, body: AgentUpdate) -> AgentRecord:
    try:
        return library_store.update_agent(agent_id, body)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="agent not found") from exc
    except LibraryValidationError as exc:
        raise _validation_error(exc) from exc


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str) -> dict:
    try:
        ok = library_store.delete_agent(agent_id)
    except LibraryValidationError as exc:
        raise _validation_error(exc) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="agent not found")
    return {"ok": True, "id": agent_id}
