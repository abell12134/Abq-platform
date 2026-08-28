"""Attach live factor snapshots to single-ticket analysis (P5g)."""

from __future__ import annotations

import logging

from app.factors.agent_tools import (
    _load_panel_for_symbol,
    compute_factor_snapshot,
    list_factors_for_agent,
)

log = logging.getLogger(__name__)

ATTACH_STATUSES = frozenset({"live", "paper_tracking", "passed_auto"})
MAX_ATTACH = 8
LOOKBACK = 120


async def attach_factors_for_symbol(
    symbol: str,
    *,
    lookback: int = LOOKBACK,
    max_factors: int = MAX_ATTACH,
    use_synthetic: bool = False,
) -> tuple[str | None, list[str]]:
    """Compute latest factor readings for one symbol; never raises."""
    catalog = await list_factors_for_agent(limit=max_factors)
    candidates = [
        f for f in catalog["factors"] if f.get("status") in ATTACH_STATUSES and f.get("universe") != "market"
    ]
    if not candidates:
        return None, []

    try:
        panel, sym = await _load_panel_for_symbol(symbol, lookback=lookback, use_synthetic=use_synthetic)
    except Exception as exc:  # noqa: BLE001
        log.warning("attach_factors panel failed: %s", exc)
        return None, [f"[factors] 面板加载失败，跳过因子挂载：{exc}"]

    lines: list[str] = []
    findings: list[str] = []
    for row in candidates[:max_factors]:
        fid = str(row["id"])
        try:
            snap = await compute_factor_snapshot(fid, symbol, panel=panel, sym=sym)
            if snap.get("status") != "ok":
                continue
            raw = snap.get("value")
            pct = snap.get("cross_section_percentile")
            name = snap.get("name") or row.get("name") or fid
            pct_text = f"{pct:.0f}%" if isinstance(pct, (int, float)) else "n/a"
            raw_text = f"{raw:.4g}" if isinstance(raw, (int, float)) else str(raw)
            lines.append(f"- **{name}** (`{fid}`): 值={raw_text}，截面分位={pct_text}")
            findings.append(f"[factors] {fid}: raw={raw_text} pct={pct_text}")
        except Exception as exc:  # noqa: BLE001
            log.debug("attach factor %s failed: %s", fid, exc)
            continue

    if not lines:
        return None, findings

    summary = "因子截面（live / passed_auto，最近交易日）\n" + "\n".join(lines)
    return summary, findings


async def attach_market_timing_factors(
    index_symbol: str = "sh000300",
    *,
    lookback: int = LOOKBACK,
    max_factors: int = MAX_ATTACH,
    use_synthetic: bool = False,
) -> tuple[str | None, list[str]]:
    """Attach live market-timing factors for index analysis."""
    catalog = await list_factors_for_agent(limit=max_factors * 2)
    candidates = [
        f
        for f in catalog["factors"]
        if f.get("status") in ATTACH_STATUSES and f.get("universe") == "market"
    ]
    if not candidates:
        return None, []

    try:
        panel, sym = await _load_panel_for_symbol(index_symbol, lookback=lookback, use_synthetic=use_synthetic)
    except Exception as exc:  # noqa: BLE001
        log.warning("attach_market_factors panel failed: %s", exc)
        return None, [f"[factors] 大盘面板加载失败：{exc}"]

    lines: list[str] = []
    findings: list[str] = []
    for row in candidates[:max_factors]:
        fid = str(row["id"])
        try:
            snap = await compute_factor_snapshot(fid, index_symbol, panel=panel, sym=sym)
            if snap.get("status") != "ok":
                continue
            raw = snap.get("value")
            name = snap.get("name") or row.get("name") or fid
            raw_text = f"{raw:.4g}" if isinstance(raw, (int, float)) else str(raw)
            as_of = snap.get("as_of") or ""
            lines.append(f"- **{name}** (`{fid}`): 最新值={raw_text}" + (f" @ {as_of}" if as_of else ""))
            findings.append(f"[factors] {fid}: timing={raw_text}")
        except Exception as exc:  # noqa: BLE001
            log.debug("attach market factor %s failed: %s", fid, exc)
            continue

    if not lines:
        return None, findings

    summary = "大盘择时因子（universe=market）\n" + "\n".join(lines)
    return summary, findings
