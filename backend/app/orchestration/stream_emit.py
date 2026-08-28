from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass

_emitter: ContextVar[Callable[[TokenDelta], Awaitable[None]] | None] = ContextVar(
    "stream_token_emitter",
    default=None,
)


@dataclass(frozen=True)
class TokenDelta:
    step_id: str
    agent: str
    delta: str


def set_token_emitter(
    emitter: Callable[[TokenDelta], Awaitable[None]] | None,
) -> None:
    _emitter.set(emitter)


async def emit_token(delta: TokenDelta) -> None:
    emitter = _emitter.get()
    if emitter is not None:
        await emitter(delta)


def token_emitter_active() -> bool:
    return _emitter.get() is not None
