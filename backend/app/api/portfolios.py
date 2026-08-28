from fastapi import APIRouter, HTTPException

from app.data.portfolio_snapshot import build_portfolio_snapshot
from app.models.portfolio import (
    PortfolioCreate,
    PortfolioRecord,
    PortfolioUpdate,
    TrackRecordCreate,
)
from app.persistence.portfolio_store import PortfolioStoreError, portfolio_store

router = APIRouter(prefix="/portfolios", tags=["portfolios"])


@router.get("")
async def list_portfolios() -> dict:
    portfolio_store.ensure()
    items = portfolio_store.list_portfolios()
    return {"portfolios": [p.model_dump() for p in items]}


@router.get("/{portfolio_id}")
async def get_portfolio(portfolio_id: str) -> PortfolioRecord:
    rec = portfolio_store.get(portfolio_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="portfolio not found")
    return rec


@router.get("/{portfolio_id}/snapshot")
async def get_portfolio_snapshot(portfolio_id: str) -> dict:
    rec = portfolio_store.get(portfolio_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="portfolio not found")
    snap = await build_portfolio_snapshot(rec)
    return snap.model_dump()


@router.get("/{portfolio_id}/tracks")
async def list_portfolio_tracks(portfolio_id: str) -> dict:
    if portfolio_store.get(portfolio_id) is None:
        raise HTTPException(status_code=404, detail="portfolio not found")
    rows = portfolio_store.list_tracks(portfolio_id)
    return {"records": [r.model_dump() for r in rows]}


@router.post("/{portfolio_id}/track")
async def record_portfolio_track(portfolio_id: str, body: TrackRecordCreate | None = None) -> dict:
    rec = portfolio_store.get(portfolio_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="portfolio not found")
    snap = await build_portfolio_snapshot(rec)
    row = portfolio_store.append_track(portfolio_id, snap, body)
    return row.model_dump()


@router.post("")
async def create_portfolio(body: PortfolioCreate) -> PortfolioRecord:
    try:
        return portfolio_store.create(body)
    except PortfolioStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{portfolio_id}")
async def update_portfolio(portfolio_id: str, body: PortfolioUpdate) -> PortfolioRecord:
    try:
        return portfolio_store.update(portfolio_id, body)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="portfolio not found") from exc
    except PortfolioStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{portfolio_id}")
async def delete_portfolio(portfolio_id: str) -> dict:
    try:
        portfolio_store.delete(portfolio_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="portfolio not found") from exc
    except PortfolioStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "id": portfolio_id}
