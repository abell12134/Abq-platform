"""Multi-factor synthesis (equal / IC / ICIR) and synth panel compute."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any, Literal

import numpy as np
import pandas as pd

from app.factors import ops
from app.factors.compute import FactorComputeError
from app.factors.evaluate import load_qlib_eval_panel
from app.factors.gates import evaluate_cross_section
from app.factors.ir import parse_formula
from app.factors.panel import Panel, synthetic_panel
from app.factors.paper import apply_gate5_status
from app.factors.runtime import compute_factor_panel
from app.factors.store import FactorStoreError, factor_store
from app.models.factors import FactorRecord, FactorSynthesizeRequest

SynthMethod = Literal["equal", "ic", "ic_ir"]

SYNTH_INPUT_STATUSES = frozenset({"passed_auto", "paper_tracking", "live"})
INCREMENTAL_IC_MIN = 0.005
_PLACEHOLDER_FORMULA = "rank(close)"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _zscore_cs(values: pd.DataFrame) -> pd.DataFrame:
    return ops.op_zscore(values)


def _weight_for(method: SynthMethod, rec: FactorRecord) -> float:
    ic_stats = (rec.metrics or {}).get("ic_stats") or {}
    if method == "equal":
        return 1.0
    ic_mean = abs(float(ic_stats.get("ic_mean") or 0.0))
    if method == "ic":
        return max(ic_mean, 1e-6)
    icir = abs(float(ic_stats.get("icir") or 0.0))
    return max(icir, 1e-6)


def _normalize_weights(weights: list[float]) -> list[float]:
    arr = np.asarray(weights, dtype=float)
    if arr.size == 0:
        return []
    total = float(arr.sum())
    if total <= 0:
        return [1.0 / len(arr)] * len(arr)
    return [float(x / total) for x in arr]


def combine_factor_panels(
    panels: list[pd.DataFrame],
    weights: list[float],
) -> pd.DataFrame:
    if len(panels) != len(weights) or not panels:
        raise FactorComputeError("合成面板与权重数量不一致")
    normed = _normalize_weights(weights)
    out: pd.DataFrame | None = None
    for frame, weight in zip(panels, normed, strict=True):
        part = frame * weight
        out = part if out is None else out.add(part, fill_value=0.0)
    assert out is not None
    return out


def compute_synth_panel(rec: FactorRecord, panel: Panel) -> pd.DataFrame:
    meta = (rec.metrics or {}).get("synth") or {}
    component_ids = list(meta.get("components") or [])
    method = str(meta.get("method") or "equal")
    if len(component_ids) < 2:
        raise FactorComputeError("合成因子缺少 components 元数据")
    stored_weights = meta.get("weights") or {}
    frames: list[pd.DataFrame] = []
    weights: list[float] = []
    for fid in component_ids:
        comp = factor_store.get(fid)
        if comp is None:
            raise FactorComputeError(f"合成组件不存在: {fid}")
        values = compute_factor_panel(comp, panel)
        frames.append(_zscore_cs(values))
        if isinstance(stored_weights, dict) and fid in stored_weights:
            weights.append(float(stored_weights[fid]))
        else:
            weights.append(_weight_for(method, comp))  # type: ignore[arg-type]
    return combine_factor_panels(frames, weights)


def _make_synth_id(method: str, factor_ids: list[str]) -> str:
    if len(factor_ids) <= 3:
        base = f"synth_{method}_{'_'.join(factor_ids)}"
        base = re.sub(r"[^a-z0-9_]", "_", base.lower())[:60]
        if factor_store.get(base) is None:
            return base
    digest = hashlib.sha1(",".join(sorted(factor_ids)).encode()).hexdigest()[:8]
    return f"synth_{method}_{digest}"


def _formula_label(method: str, factor_ids: list[str], weights: dict[str, float]) -> str:
    parts = []
    for fid in factor_ids:
        w = weights.get(fid, 0.0)
        parts.append(f"{w:.2f}*{fid}")
    return f"synth_{method}(" + " + ".join(parts) + ")"


def _component_ic_stats(records: list[FactorRecord]) -> list[float]:
    out: list[float] = []
    for rec in records:
        ic_stats = (rec.metrics or {}).get("ic_stats") or {}
        ic_mean = ic_stats.get("ic_mean")
        if isinstance(ic_mean, (int, float)) and ic_mean == ic_mean:
            out.append(abs(float(ic_mean)))
    return out


def _gate5_incremental(synth_ic_mean: float | None, component_ics: list[float]) -> tuple[bool, str]:
    if synth_ic_mean is None or not component_ics:
        return False, "缺少 IC 统计，无法判断增量"
    best = max(component_ics)
    delta = abs(float(synth_ic_mean)) - best
    if delta >= INCREMENTAL_IC_MIN:
        return True, f"合成 |IC| {abs(float(synth_ic_mean)):.4f} 优于最佳单因子 {best:.4f}（+{delta:.4f}）"
    return False, f"合成 |IC| {abs(float(synth_ic_mean)):.4f} 未显著优于最佳单因子 {best:.4f}"


async def synthesize_factors(body: FactorSynthesizeRequest) -> dict[str, Any]:
    factor_store.ensure()
    ids = list(dict.fromkeys(body.factor_ids))
    if len(ids) < 2:
        raise FactorStoreError("至少选择 2 个因子合成")
    if len(ids) > 8:
        raise FactorStoreError("单次最多合成 8 个因子")

    records: list[FactorRecord] = []
    for fid in ids:
        rec = factor_store.get(fid)
        if rec is None:
            raise FactorStoreError(f"因子不存在: {fid}")
        if rec.status not in SYNTH_INPUT_STATUSES:
            raise FactorStoreError(f"{fid} 状态为 {rec.status}，仅 passed_auto / paper_tracking / live 可参与合成")
        if rec.universe == "market":
            raise FactorStoreError(f"{fid} 为择时因子，截面合成不支持")
        records.append(rec)

    universes = {r.universe for r in records}
    if len(universes) != 1:
        raise FactorStoreError("合成因子须属于同一 universe")
    universe = body.universe or next(iter(universes))

    if body.use_synthetic:
        panel = synthetic_panel(n_stocks=12, n_days=max(80, body.lookback // 3), seed=17)
        meta_panel: dict[str, Any] = {"source": "synthetic", "n_stocks": 12}
    else:
        panel, meta_panel = await load_qlib_eval_panel(body.symbols, body.lookback)

    frames: list[pd.DataFrame] = []
    raw_weights: list[float] = []
    for rec in records:
        values = compute_factor_panel(rec, panel)
        frames.append(_zscore_cs(values))
        raw_weights.append(_weight_for(body.method, rec))

    weight_map = {rec.id: float(w) for rec, w in zip(records, _normalize_weights(raw_weights), strict=True)}
    combined = combine_factor_panels(frames, list(weight_map.values()))

    others: dict[str, pd.DataFrame] = {}
    for rec in factor_store.list_factors():
        if rec.id in ids:
            continue
        if rec.universe == "market":
            continue
        try:
            others[rec.id] = compute_factor_panel(rec, panel)
        except Exception:
            continue
        if len(others) >= 24:
            break

    hypothesis = (body.hypothesis or "").strip()
    if len(hypothesis) < 8:
        hypothesis = f"{body.method} 加权合成 {', '.join(ids)} 截面因子组合。"

    gate = evaluate_cross_section(
        combined,
        panel["close"],
        others=others,
        hypothesis=hypothesis,
        origin="synth",
    )
    synth_ic = (gate.get("ic_stats") or {}).get("ic_mean")
    comp_ics = _component_ic_stats(records)
    gate5_ok, gate5_note = _gate5_incremental(
        float(synth_ic) if isinstance(synth_ic, (int, float)) else None,
        comp_ics,
    )

    status = gate["status"]
    reject_reason = gate.get("reject_reason") or ""
    if status == "passed_auto" and gate5_ok:
        status = "paper_tracking"
        reject_reason = gate5_note
    elif status == "passed_auto":
        reject_reason = gate5_note

    factor_id = (body.id or "").strip() or _make_synth_id(body.method, ids)
    if factor_store.get(factor_id) is not None and not body.replace:
        raise FactorStoreError(f"因子 id 已存在: {factor_id}（可设 replace=true 覆盖）")

    placeholder = parse_formula(_PLACEHOLDER_FORMULA)
    from app.factors.ir import expr_to_dict

    display_formula = _formula_label(body.method, ids, weight_map)
    themes: list[str] = []
    for rec in records:
        themes.extend(rec.theme or [])
    theme = sorted(set(themes))[:6]

    metrics: dict[str, Any] = {
        k: v for k, v in gate.items() if k != "ic_series"
    }
    metrics["synth"] = {
        "method": body.method,
        "components": ids,
        "weights": weight_map,
        "display_formula": display_formula,
        "gate5_passed": gate5_ok,
        "gate5_note": gate5_note,
        "component_ic_means": {
            rec.id: (rec.metrics or {}).get("ic_stats", {}).get("ic_mean") for rec in records
        },
    }
    if gate5_ok and status == "paper_tracking":
        metrics["paper_history"] = {
            "started_at": _now(),
            "last_improved_at": _now(),
            "best_ic_mean": abs(float(synth_ic)) if isinstance(synth_ic, (int, float)) else None,
            "checks": [],
        }

    now = _now()
    rec = FactorRecord(
        id=factor_id,
        name=body.name or f"合成·{body.method}·{len(ids)}因子",
        origin="synth",
        status=status,  # type: ignore[arg-type]
        theme=theme,
        universe=universe,
        formula=display_formula,
        expr=expr_to_dict(placeholder),
        hypothesis=hypothesis,
        metrics=metrics,
        reject_reason=str(reject_reason),
        builtin=False,
        created_at=now,
        updated_at=now,
    )
    stored = factor_store.put_discovered(rec)
    rec = stored

    return {
        "factor": rec.model_dump(),
        "metrics": metrics,
        "panel": meta_panel,
        "gate5_passed": gate5_ok,
        "gate5_note": gate5_note,
    }


def eval_synth_record(rec: FactorRecord, panel: Panel, *, persist: bool) -> dict[str, Any]:
    """Re-evaluate a synth factor and apply gate 5 paper rules on persist."""
    combined = compute_synth_panel(rec, panel)
    meta = (rec.metrics or {}).get("synth") or {}
    component_ids = list(meta.get("components") or [])
    comp_ics = []
    for fid in component_ids:
        comp = factor_store.get(fid)
        if comp:
            ic = (comp.metrics or {}).get("ic_stats", {}).get("ic_mean")
            if isinstance(ic, (int, float)):
                comp_ics.append(abs(float(ic)))

    others: dict[str, pd.DataFrame] = {}
    for other in factor_store.list_factors():
        if other.id == rec.id or other.id in component_ids or other.universe == "market":
            continue
        try:
            others[other.id] = compute_factor_panel(other, panel)
        except Exception:
            continue
        if len(others) >= 24:
            break

    gate = evaluate_cross_section(
        combined,
        panel["close"],
        others=others,
        hypothesis=rec.hypothesis,
        origin="synth",
    )
    synth_ic = (gate.get("ic_stats") or {}).get("ic_mean")
    gate5_ok, gate5_note = _gate5_incremental(
        float(synth_ic) if isinstance(synth_ic, (int, float)) else None,
        comp_ics,
    )

    metrics = dict(rec.metrics or {})
    metrics.update({k: v for k, v in gate.items() if k != "ic_series"})
    if "synth" in metrics and isinstance(metrics["synth"], dict):
        metrics["synth"] = {**metrics["synth"], "gate5_passed": gate5_ok, "gate5_note": gate5_note}

    status = gate["status"]
    reject_reason = gate.get("reject_reason") or ""
    if status == "passed_auto" and gate5_ok:
        status = "paper_tracking"
        reject_reason = gate5_note
        metrics.setdefault(
            "paper_history",
            {
                "started_at": _now(),
                "last_improved_at": _now(),
                "best_ic_mean": abs(float(synth_ic)) if isinstance(synth_ic, (int, float)) else None,
                "checks": [],
            },
        )
    elif rec.status in {"paper_tracking", "frozen"} and gate["status"] == "passed_auto":
        status, reject_reason, metrics = apply_gate5_status(
            rec,
            float(synth_ic) if isinstance(synth_ic, (int, float)) else None,
            metrics,
        )

    rec.metrics = metrics
    rec.reject_reason = reject_reason
    if not rec.builtin:
        rec.status = status  # type: ignore[assignment]

    updated = factor_store.save_eval(rec) if persist else rec
    return {
        "factor": updated.model_dump(),
        "metrics": metrics,
        "gate5_passed": gate5_ok,
        "gate5_note": gate5_note,
    }
