from __future__ import annotations

from contextvars import ContextVar

_memory_hints: ContextVar[list[str] | None] = ContextVar("memory_hints", default=None)


def set_memory_hints(hints: list[str]) -> None:
    _memory_hints.set(list(hints))


def get_memory_hints() -> list[str]:
    val = _memory_hints.get()
    return list(val) if val is not None else []
