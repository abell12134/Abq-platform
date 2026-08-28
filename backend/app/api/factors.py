from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.factors.compute import FactorComputeError
from app.factors.evaluate import evaluate_request
from app.factors.ir import FactorExprError
from app.factors.mine_gp import run_gp_market
from app.factors.mine_gp_cs import run_gp_cs, start_gp_run
from app.factors.mine_llm import (
    active_run_id,
    init_run,
    list_runs,
    read_progress,
    run_llm_mine,
)
from app.factors.paper_revalidate import revalidate_paper_factors
from app.factors.screener import apply_screen_to_portfolio, run_factor_screen
from app.factors.store import FactorStoreError, factor_store
from app.factors.synth import synthesize_factors
from app.models.factors import (
    FactorCreate,
    FactorEvalRequest,
    FactorMineGpRequest,
    FactorMineLlmRequest,
    FactorRecord,
    FactorScreenApplyRequest,
    FactorScreenRequest,
    FactorSynthesizeRequest,
    FactorUpdate,
    PaperRevalidateRequest,
)

router = APIRouter(prefix="/factors", tags=["factors"])


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("")
async def list_factors(
    status: str | None = Query(None),
    origin: str | None = Query(None),
    theme: str | None = Query(None),
) -> dict:
    factor_store.ensure()
    items = factor_store.list_factors(status=status, origin=origin, theme=theme)
    return {"factors": [f.model_dump() for f in items]}


@router.post("/eval")
async def eval_factor(body: FactorEvalRequest) -> dict:
    try:
        return await evaluate_request(
            factor_id=body.factor_id,
            formula=body.formula,
            universe=body.universe,
            symbols=body.symbols,
            lookback=body.lookback,
            use_synthetic=body.use_synthetic,
            persist=True,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="factor not found") from exc
    except (FactorStoreError, FactorExprError, FactorComputeError, ValueError) as exc:
        raise _bad(exc) from exc


@router.post("/paper/revalidate")
async def paper_revalidate_factors(body: PaperRevalidateRequest | None = None) -> dict:
    req = body or PaperRevalidateRequest()
    try:
        return await revalidate_paper_factors(
            factor_ids=req.factor_ids,
            lookback=req.lookback,
            persist=True,
        )
    except (FactorStoreError, FactorComputeError, ValueError) as exc:
        raise _bad(exc) from exc


@router.post("/synthesize")
async def synthesize_factor(body: FactorSynthesizeRequest) -> dict:
    try:
        return await synthesize_factors(body)
    except (FactorStoreError, FactorComputeError, FactorExprError, ValueError) as exc:
        raise _bad(exc) from exc


@router.post("/screen")
async def factor_screen(body: FactorScreenRequest) -> dict:
    try:
        return await run_factor_screen(body)
    except (FactorStoreError, FactorComputeError, FactorExprError, ValueError) as exc:
        raise _bad(exc) from exc


@router.post("/screen/apply")
async def factor_screen_apply(body: FactorScreenApplyRequest) -> dict:
    try:
        return apply_screen_to_portfolio(body)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="portfolio not found") from exc
    except (FactorStoreError, ValueError) as exc:
        raise _bad(exc) from exc


@router.post("/mine/llm")
async def start_llm_mine(body: FactorMineLlmRequest, background_tasks: BackgroundTasks) -> dict:
    existing = active_run_id()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"已有挖掘任务在跑（{existing}）",
        )
    run_id = init_run(body)
    background_tasks.add_task(run_llm_mine, run_id, body)
    return {"run_id": run_id, "status": "running"}


@router.post("/mine/gp")
async def start_gp_mine(body: FactorMineGpRequest, background_tasks: BackgroundTasks) -> dict:
    existing = active_run_id()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"已有挖掘任务在跑（{existing}）",
        )
    try:
        run_id = start_gp_run(body)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if body.track == "cs":
        background_tasks.add_task(run_gp_cs, run_id, body)
    else:
        background_tasks.add_task(run_gp_market, run_id, body)
    return {"run_id": run_id, "status": "running"}


@router.get("/runs")
async def get_factor_runs() -> dict:
    return {"runs": list_runs()}


@router.get("/runs/{run_id}")
async def get_factor_run(run_id: str) -> dict:
    progress = read_progress(run_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="run not found")
    return progress


@router.get("/{factor_id}")
async def get_factor(factor_id: str) -> FactorRecord:
    rec = factor_store.get(factor_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="factor not found")
    return rec


@router.post("")
async def create_factor(body: FactorCreate) -> FactorRecord:
    try:
        return factor_store.create(body)
    except (FactorStoreError, FactorExprError) as exc:
        raise _bad(exc) from exc


@router.put("/{factor_id}")
async def update_factor(factor_id: str, body: FactorUpdate) -> FactorRecord:
    try:
        return factor_store.update(factor_id, body)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="factor not found") from exc
    except (FactorStoreError, FactorExprError) as exc:
        raise _bad(exc) from exc


@router.delete("/{factor_id}")
async def delete_factor(factor_id: str) -> dict:
    try:
        ok = factor_store.delete(factor_id)
    except FactorStoreError as exc:
        raise _bad(exc) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="factor not found")
    return {"ok": True, "id": factor_id}
