"""Batch paper-tracking revalidation for factors in paper_tracking / frozen."""

from __future__ import annotations

import logging
from typing import Any

from app.factors.evaluate import load_qlib_eval_panel, run_eval_on_panel
from app.factors.store import factor_store

log = logging.getLogger(__name__)

PAPER_STATUSES = frozenset({"paper_tracking", "frozen"})


async def revalidate_paper_factors(
    *,
    factor_ids: list[str] | None = None,
    lookback: int = 252,
    persist: bool = True,
) -> dict[str, Any]:
    factor_store.ensure()
    if factor_ids:
        targets = []
        for fid in factor_ids:
            rec = factor_store.get(fid)
            if rec and rec.status in PAPER_STATUSES:
                targets.append(rec)
    else:
        targets = [f for f in factor_store.list_factors() if f.status in PAPER_STATUSES]

    if not targets:
        return {"count": 0, "results": [], "message": "无纸面/冻结因子需要重评"}

    try:
        panel, panel_meta = await load_qlib_eval_panel(None, lookback)
    except Exception as exc:  # noqa: BLE001
        log.warning("paper revalidate panel load failed: %s", exc)
        return {"count": 0, "results": [], "error": str(exc)}

    results: list[dict[str, Any]] = []
    for rec in targets:
        try:
            out = run_eval_on_panel(
                rec=rec,
                formula=None,
                universe=rec.universe,
                panel=panel,
                persist=persist,
            )
            factor = out.get("factor") or {}
            results.append(
                {
                    "id": rec.id,
                    "status": factor.get("status"),
                    "gate5_note": (factor.get("metrics") or {}).get("gate5_note"),
                    "ic_mean": ((factor.get("metrics") or {}).get("ic_stats") or {}).get("ic_mean"),
                }
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("paper revalidate %s failed: %s", rec.id, exc)
            results.append({"id": rec.id, "error": str(exc)})

    return {
        "count": len(results),
        "panel": panel_meta,
        "results": results,
    }
