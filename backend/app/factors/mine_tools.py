"""Start / poll factor mining runs from agent tools (no HTTP BackgroundTasks)."""

from __future__ import annotations

import asyncio
from typing import Any

from app.factors.mine_gp import run_gp_market
from app.factors.mine_gp_cs import run_gp_cs, start_gp_run
from app.factors.mine_llm import active_run_id, init_run, read_progress, run_llm_mine
from app.models.factors import FactorMineGpRequest, FactorMineLlmRequest


async def schedule_llm_mine(body: FactorMineLlmRequest) -> dict[str, Any]:
    existing = active_run_id()
    if existing:
        return {
            "status": "error",
            "error": f"已有挖掘任务在跑（{existing}）",
            "run_id": existing,
        }
    run_id = init_run(body)
    asyncio.create_task(run_llm_mine(run_id, body))
    return {
        "status": "running",
        "run_id": run_id,
        "kind": "llm",
        "message": "LLM 因子挖掘已启动。用 get_factor_mine_status 查询进度与漏斗。",
    }


async def schedule_gp_mine(body: FactorMineGpRequest) -> dict[str, Any]:
    existing = active_run_id()
    if existing:
        return {
            "status": "error",
            "error": f"已有挖掘任务在跑（{existing}）",
            "run_id": existing,
        }
    try:
        run_id = start_gp_run(body)
    except RuntimeError as exc:
        return {"status": "error", "error": str(exc)}
    if body.track == "cs":
        asyncio.create_task(run_gp_cs(run_id, body))
        kind = "gp_cs"
    else:
        asyncio.create_task(run_gp_market(run_id, body))
        kind = "gp_market"
    return {
        "status": "running",
        "run_id": run_id,
        "kind": kind,
        "track": body.track,
        "message": "GP 因子挖掘已启动。用 get_factor_mine_status 查询进度。",
    }


def mine_status(run_id: str | None = None) -> dict[str, Any]:
    rid = (run_id or "").strip() or active_run_id()
    if not rid:
        return {"status": "idle", "message": "当前无进行中的挖掘任务"}
    progress = read_progress(rid)
    if progress is None:
        return {"status": "error", "error": f"run 不存在: {rid}", "run_id": rid}
    out = dict(progress)
    out["run_id"] = rid
    return out
