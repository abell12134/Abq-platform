from __future__ import annotations

import asyncio


class AnalysisRegistry:
    """Track in-flight analyze streams so they can be cancelled by path id."""

    def __init__(self) -> None:
        self._cancel_events: dict[str, asyncio.Event] = {}

    def register(self, path_id: str) -> asyncio.Event:
        ev = asyncio.Event()
        self._cancel_events[path_id] = ev
        return ev

    def unregister(self, path_id: str) -> None:
        self._cancel_events.pop(path_id, None)

    def cancel(self, path_id: str) -> bool:
        ev = self._cancel_events.get(path_id)
        if ev is None:
            return False
        ev.set()
        return True

    def is_active(self, path_id: str) -> bool:
        return path_id in self._cancel_events

    def active_ids(self) -> list[str]:
        return list(self._cancel_events.keys())

    def cancel_all(self) -> list[str]:
        cancelled: list[str] = []
        for path_id in self.active_ids():
            if self.cancel(path_id):
                cancelled.append(path_id)
        return cancelled


analysis_registry = AnalysisRegistry()
