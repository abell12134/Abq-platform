from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from typing import Any

DEFAULT_TIMEOUT_S = 25.0


def to_digits(symbol: str) -> str:
    digits = re.sub(r"\D", "", symbol)
    if len(digits) != 6:
        raise ValueError(f"无法解析 A 股代码: {symbol}")
    return digits


async def run_sync[T](
    func: Callable[..., T],
    /,
    *args: Any,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    **kwargs: Any,
) -> T:
    return await asyncio.wait_for(asyncio.to_thread(func, *args, **kwargs), timeout=timeout_s)
