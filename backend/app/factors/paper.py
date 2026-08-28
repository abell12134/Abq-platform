"""Gate 5 paper-tracking time rules (freeze / retire on re-eval)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.models.factors import FactorRecord

PAPER_NO_IMPROVE_DAYS = 15
PAPER_RETIRE_DAYS = 30
IC_RETIRE_FLOOR = 0.01


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def apply_gate5_status(
    rec: FactorRecord,
    ic_mean: float | None,
    metrics: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    """Advance paper_tracking / frozen status based on IC history."""
    history = dict(metrics.get("paper_history") or {})
    now = _now()
    now_dt = datetime.now(UTC)
    started = _parse_ts(str(history.get("started_at") or rec.created_at))
    last_improved = _parse_ts(str(history.get("last_improved_at") or history.get("started_at") or rec.created_at))
    best = history.get("best_ic_mean")
    best_ic = abs(float(best)) if isinstance(best, (int, float)) else None
    current = abs(float(ic_mean)) if isinstance(ic_mean, (int, float)) else None

    checks = list(history.get("checks") or [])
    checks.append({"at": now, "ic_mean": current})
    history["checks"] = checks[-30:]

    if current is not None and (best_ic is None or current > best_ic + 1e-6):
        history["best_ic_mean"] = current
        history["last_improved_at"] = now
        best_ic = current
        if rec.status == "frozen":
            metrics["paper_history"] = history
            return "paper_tracking", "纸面 IC 回升，解冻回跟踪", metrics

    if started and (now_dt - started).days >= PAPER_RETIRE_DAYS:
        if current is not None and current < IC_RETIRE_FLOOR:
            metrics["paper_history"] = history
            return "retired", f"纸面满 {PAPER_RETIRE_DAYS} 日且 IC 跌破 {IC_RETIRE_FLOOR}", metrics

    if last_improved and (now_dt - last_improved).days >= PAPER_NO_IMPROVE_DAYS:
        metrics["paper_history"] = history
        return "frozen", f"纸面 {PAPER_NO_IMPROVE_DAYS} 日无 IC 改进，冻结", metrics

    metrics["paper_history"] = history
    return rec.status, "纸面跟踪中", metrics
