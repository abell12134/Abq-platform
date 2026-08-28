"""Resolve index universe constituents (CSI300 / CSI500)."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from app.config import settings
from app.data.qlib_store import normalize_symbol
from app.factors.panel import DEFAULT_EVAL_SYMBOLS
from app.models.factors import FactorUniverse

log = logging.getLogger(__name__)

UniverseId = Literal["csi300", "csi500"]

_INDEX_CODE: dict[UniverseId, str] = {
    "csi300": "000300",
    "csi500": "000905",
}

_CACHE_TTL = timedelta(days=7)


def _cache_path(universe: UniverseId) -> Path:
    return settings.data_dir / "cache" / "universes" / f"{universe}.json"


def _cache_valid(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = payload.get("fetched_at")
        if not fetched_at:
            return False
        ts = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
        return datetime.now(UTC) - ts < _CACHE_TTL
    except Exception:  # noqa: BLE001
        return False


def _load_cache(universe: UniverseId) -> list[str] | None:
    path = _cache_path(universe)
    if not _cache_valid(path):
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        symbols = payload.get("symbols") or []
        out = [normalize_symbol(str(s)) for s in symbols if str(s).strip()]
        return out or None
    except Exception as exc:  # noqa: BLE001
        log.warning("universe cache read failed %s: %s", universe, exc)
        return None


def _save_cache(universe: UniverseId, symbols: list[str]) -> None:
    path = _cache_path(universe)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "universe": universe,
        "index_code": _INDEX_CODE[universe],
        "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(symbols),
        "symbols": symbols,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _fetch_csindex_sync(index_code: str) -> list[str]:
    import akshare as ak

    df = ak.index_stock_cons_csindex(symbol=index_code)
    col = "成分券代码" if "成分券代码" in df.columns else df.columns[0]
    raw = [str(x).strip() for x in df[col].tolist() if str(x).strip()]
    return [normalize_symbol(code) for code in raw]


async def fetch_universe_symbols(
    universe: FactorUniverse,
    *,
    max_symbols: int = 80,
) -> tuple[list[str], dict]:
    """Return normalized symbols for a cross-section universe."""
    if universe == "market":
        raise ValueError("market 轨道不支持截面选股，请使用 csi300 或 csi500")

    uid: UniverseId = universe  # type: ignore[assignment]
    cached = _load_cache(uid)
    source = "cache"
    symbols = cached
    if not symbols:
        try:
            index_code = _INDEX_CODE[uid]
            symbols = await asyncio.to_thread(_fetch_csindex_sync, index_code)
            if symbols:
                _save_cache(uid, symbols)
                source = "akshare"
        except Exception as exc:  # noqa: BLE001
            log.warning("universe fetch failed %s: %s", universe, exc)
            symbols = None
            source = "fallback"

    if not symbols:
        symbols = [normalize_symbol(s) for s in DEFAULT_EVAL_SYMBOLS]
        source = "default_eval"

    cap = max(10, min(max_symbols, 300))
    trimmed = symbols[:cap]
    return trimmed, {
        "universe": universe,
        "source": source,
        "requested": len(symbols),
        "used": len(trimmed),
        "index_code": _INDEX_CODE.get(uid),
    }
