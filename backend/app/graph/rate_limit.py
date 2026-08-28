from __future__ import annotations

import asyncio
import time


class FetchThrottle:
    """Serialize outbound fetches with a minimum gap to reduce anti-scraping risk."""

    def __init__(self, min_interval_s: float = 3.0) -> None:
        self._min_interval = max(0.5, float(min_interval_s))
        self._last_at = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            gap = self._min_interval - (now - self._last_at)
            if gap > 0:
                await asyncio.sleep(gap)
            self._last_at = time.monotonic()

    @property
    def min_interval_s(self) -> float:
        return self._min_interval
