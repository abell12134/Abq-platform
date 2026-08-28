from fastapi import APIRouter, HTTPException

from app.models.library import PromptCreate, PromptRecord, PromptUpdate
from app.persistence.library_store import LibraryValidationError, library_store

router = APIRouter(prefix="/prompts", tags=["prompts"])


def _validation_error(exc: LibraryValidationError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("")
async def list_prompts() -> dict:
    library_store.ensure()
    prompts = library_store.list_prompts()
    return {"prompts": [p.model_dump() for p in prompts]}


@router.get("/{prompt_id}")
async def get_prompt(prompt_id: str) -> PromptRecord:
    record = library_store.get_prompt(prompt_id)
    if record is None:
        raise HTTPException(status_code=404, detail="prompt not found")
    return record


@router.post("")
async def create_prompt(body: PromptCreate) -> PromptRecord:
    try:
        return library_store.create_prompt(body)
    except LibraryValidationError as exc:
        raise _validation_error(exc) from exc


@router.put("/{prompt_id}")
async def update_prompt(prompt_id: str, body: PromptUpdate) -> PromptRecord:
    try:
        return library_store.update_prompt(prompt_id, body)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="prompt not found") from exc
    except LibraryValidationError as exc:
        raise _validation_error(exc) from exc


@router.delete("/{prompt_id}")
async def delete_prompt(prompt_id: str) -> dict:
    try:
        ok = library_store.delete_prompt(prompt_id)
    except LibraryValidationError as exc:
        raise _validation_error(exc) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="prompt not found")
    return {"ok": True, "id": prompt_id}
