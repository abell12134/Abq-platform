from __future__ import annotations

from collections.abc import AsyncIterator

from app.models.analysis import AnalyzeRequest
from app.models.context import ContextSnapshot
from app.orchestration.graphs.market import DEFAULT_INDEX, stream_market_pipeline
from app.orchestration.stream_types import StreamItem


async def run_market_pipeline(
    req: AnalyzeRequest,
    *,
    index_symbol: str = DEFAULT_INDEX,
    primary_override: str | None = None,
    prior_snapshot: ContextSnapshot | None = None,
    path_id: str | None = None,
) -> AsyncIterator[StreamItem]:
    async for item in stream_market_pipeline(
        req,
        index_symbol=index_symbol,
        primary_override=primary_override,
        prior_snapshot=prior_snapshot,
        path_id=path_id,
    ):
        yield item
