from __future__ import annotations

from collections.abc import AsyncIterator

from app.models.analysis import AnalyzeRequest
from app.models.context import ContextSnapshot
from app.orchestration.graphs.portfolio import stream_portfolio_pipeline
from app.orchestration.stream_types import StreamItem


async def run_portfolio_pipeline(
    req: AnalyzeRequest,
    *,
    symbols: list[str],
    portfolio_name: str = "自选组合",
    primary_override: str | None = None,
    prior_snapshot: ContextSnapshot | None = None,
    path_id: str | None = None,
) -> AsyncIterator[StreamItem]:
    async for item in stream_portfolio_pipeline(
        req,
        symbols=symbols,
        portfolio_name=portfolio_name,
        primary_override=primary_override,
        prior_snapshot=prior_snapshot,
        path_id=path_id,
    ):
        yield item
