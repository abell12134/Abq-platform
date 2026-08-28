"""Execute composite NL plans (screen → apply → diagnose) as pipeline steps."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from app.factors.screener import apply_screen_to_portfolio as apply_screen_impl
from app.factors.screener import run_factor_screen as run_factor_screen_impl
from app.models.analysis import AnalysisStep, AnalyzeRequest
from app.models.context import ContextSnapshot
from app.models.factors import FactorScreenApplyRequest, FactorScreenRequest
from app.orchestration.portfolio_pipeline import run_portfolio_pipeline
from app.orchestration.stream_types import StreamItem
from app.persistence.portfolio_store import portfolio_store


def _tool_step(agent: str, payload: dict[str, Any]) -> AnalysisStep:
    return AnalysisStep(
        id=uuid4().hex[:12],
        agent=agent,
        role="tool",
        result=json.dumps(payload, ensure_ascii=False),
    )


async def run_composite_screen_plan(
    req: AnalyzeRequest,
    plan: dict[str, Any],
    *,
    primary_override: str | None,
    prior_snapshot: ContextSnapshot | None,
    path_id: str | None,
) -> AsyncIterator[StreamItem]:
    """Run screen, optionally import into a portfolio, then optionally diagnose."""
    universe = str(plan.get("universe") or "csi300")
    top_n = int(plan.get("top_n") or 20)
    portfolio_id = str(plan.get("portfolio_id") or "default")
    mode = str(plan.get("mode") or "merge")
    use_synthetic = bool(plan.get("use_synthetic"))
    steps: list[str] = list(plan.get("steps") or ["screen"])

    screen_body = FactorScreenRequest(
        universe=universe,  # type: ignore[arg-type]
        top_n=top_n,
        use_synthetic=use_synthetic,
    )
    screen = await run_factor_screen_impl(screen_body)
    yield _tool_step("run_factor_screen", screen)

    picks = screen.get("picks") or []
    symbols = [str(p.get("symbol")) for p in picks if p.get("symbol")]

    if "apply" in steps and symbols:
        apply_body = FactorScreenApplyRequest(
            portfolio_id=portfolio_id,
            symbols=symbols,
            mode=mode,  # type: ignore[arg-type]
        )
        applied = apply_screen_impl(apply_body)
        yield _tool_step("apply_screen_to_portfolio", applied)
        portfolio_id = str(applied.get("portfolio_id") or portfolio_id)

    if "diagnose" in steps:
        rec = portfolio_store.get(portfolio_id)
        member_symbols = [m.symbol for m in rec.members] if rec and rec.members else symbols
        if not member_symbols:
            yield _tool_step(
                "apply_screen_to_portfolio",
                {"ok": False, "error": "组合为空，无法诊断", "suggested_action": "先运行选股并导入"},
            )
            return
        portfolio_name = rec.name if rec else "自选组合"
        diagnose_req = req.model_copy(
            update={"kind": "portfolio", "target": portfolio_id},
        )
        async for step in run_portfolio_pipeline(
            diagnose_req,
            symbols=member_symbols,
            portfolio_name=portfolio_name,
            primary_override=primary_override,
            prior_snapshot=prior_snapshot,
            path_id=path_id,
        ):
            yield step
