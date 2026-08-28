"""Live portfolio snapshot: batch quotes + equal-weight aggregates."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.data.bar_processing import calc_indicators, clean_bars
from app.data.ohlcv import fetch_ohlcv
from app.data.quotes_realtime import fetch_quote
from app.models.portfolio import (
    PortfolioMemberSnapshot,
    PortfolioRecord,
    PortfolioSnapshot,
)

log = logging.getLogger(__name__)


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _pick_extreme(
    members: list[PortfolioMemberSnapshot],
    *,
    best: bool,
) -> PortfolioMemberSnapshot | None:
    scored = [m for m in members if isinstance(m.pct_change, (int, float))]
    if not scored:
        return None
    return max(scored, key=lambda m: float(m.pct_change)) if best else min(
        scored, key=lambda m: float(m.pct_change)
    )


async def build_portfolio_snapshot(rec: PortfolioRecord) -> PortfolioSnapshot:
    members_out: list[PortfolioMemberSnapshot] = []
    note_by_symbol = {m.symbol: m.note for m in rec.members}

    for member in rec.members[:12]:
        sym = member.symbol
        try:
            quote = await fetch_quote(sym)
        except Exception as exc:  # noqa: BLE001
            log.debug("snapshot quote %s failed: %s", sym, exc)
            continue
        qlib_sym = str(quote.get("symbol") or sym)
        snap: dict[str, Any] = {
            "symbol": qlib_sym,
            "name": quote.get("name"),
            "note": note_by_symbol.get(sym) or member.note or None,
            "price": quote.get("price"),
            "pct_change": quote.get("pct_change"),
        }
        try:
            ohlcv = await fetch_ohlcv(sym, limit=40)
            cleaned = clean_bars(ohlcv["bars"])
            indicators = calc_indicators(cleaned["bars"])
            snap["chg_5d"] = indicators.get("chg_5d")
            snap["chg_20d"] = indicators.get("chg_20d")
        except Exception as exc:  # noqa: BLE001
            log.debug("snapshot ohlcv %s failed: %s", sym, exc)
        members_out.append(PortfolioMemberSnapshot.model_validate(snap))

    pct_1d = _avg([float(m.pct_change) for m in members_out if isinstance(m.pct_change, (int, float))])
    chg_5d = _avg([float(m.chg_5d) for m in members_out if isinstance(m.chg_5d, (int, float))])
    chg_20d = _avg([float(m.chg_20d) for m in members_out if isinstance(m.chg_20d, (int, float))])

    return PortfolioSnapshot(
        portfolio_id=rec.id,
        name=rec.name,
        realm=rec.realm,
        as_of=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        member_count=len(members_out),
        equal_weight_pct_1d=pct_1d,
        equal_weight_chg_5d=chg_5d,
        equal_weight_chg_20d=chg_20d,
        members=members_out,
        best_today=_pick_extreme(members_out, best=True),
        worst_today=_pick_extreme(members_out, best=False),
    )
