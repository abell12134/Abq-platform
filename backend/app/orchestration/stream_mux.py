from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from app.models.analysis import AnalysisStep, SseEvent
from app.orchestration.stream_emit import TokenDelta, set_token_emitter
from app.orchestration.stream_types import PhaseMarker, StreamItem


async def multiplex_step_stream(
    step_iter: AsyncIterator[StreamItem],
    *,
    path_id: str | None,
) -> AsyncIterator[SseEvent]:
    """Merge LLM token deltas (contextvar) with pipeline step/phase events on one queue."""
    out_queue: asyncio.Queue[tuple[str, object] | None] = asyncio.Queue()
    errors: list[BaseException] = []

    async def token_emitter(delta: TokenDelta) -> None:
        await out_queue.put(("token", delta))

    async def producer() -> None:
        set_token_emitter(token_emitter)
        try:
            async for item in step_iter:
                if isinstance(item, PhaseMarker):
                    await out_queue.put(("phase", item))
                else:
                    await out_queue.put(("step", item))
        except BaseException as exc:
            errors.append(exc)
        finally:
            set_token_emitter(None)
            await out_queue.put(None)

    task = asyncio.create_task(producer())

    try:
        while True:
            item = await out_queue.get()
            if item is None:
                break
            kind, payload = item
            if kind == "token":
                delta = payload  # type: ignore[assignment]
                assert isinstance(delta, TokenDelta)
                yield SseEvent(
                    type="token",
                    path_id=path_id,
                    step_id=delta.step_id,
                    agent=delta.agent,
                    delta=delta.delta,
                )
            elif kind == "phase":
                marker = payload  # type: ignore[assignment]
                assert isinstance(marker, PhaseMarker)
                yield SseEvent(
                    type="phase",
                    path_id=path_id,
                    phase=marker.phase,
                    label=marker.label,
                )
            elif kind == "step":
                step = payload  # type: ignore[assignment]
                assert isinstance(step, AnalysisStep)
                yield SseEvent(type="step", step=step, path_id=path_id)

        if errors:
            raise errors[0]
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
