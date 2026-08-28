"""GP track A: gplearn invents market-timing formulas from precomputed primitives.

The search samples are dates (Spearman is valid). Rolling ops live inside named
primitives; gplearn only combines them with arithmetic. Programs are translated
to FactorExpr — gplearn objects are never stored.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

import numpy as np
import pandas as pd

from app.factors.compute import compute_expr
from app.factors.eval_ic import FORWARD_DAYS
from app.factors.evaluate import evaluate_request, load_qlib_eval_panel
from app.factors.ir import (
    FactorExprError,
    node_count,
    parse_formula,
    print_expr,
    substitute_vars,
)
from app.factors.mine_llm import (
    _append_jsonl,
    _lock_path,
    _patch_progress,
    _run_dir,
)
from app.factors.panel import Panel, collapse_to_series, synthetic_panel
from app.factors.store import FactorStoreError, factor_store
from app.models.factors import FactorCreate, FactorMineGpRequest

MAX_PROG_LEN = 12
CHEAT_CORR = 0.8
KEEP_EVAL = 5

# Precomputed market terminals. Keys are extra GP feature names; values are IR.
MARKET_PRIMITIVES: dict[str, str] = {
    "mkt_close": "mkt_close",
    "mkt_volume": "mkt_volume",
    "mkt_amount": "mkt_amount",
    "ret_1": "sub(div(mkt_close, delay(mkt_close, 1)), 1)",
    "ret_5": "sub(div(mkt_close, delay(mkt_close, 5)), 1)",
    "ret_20": "sub(div(mkt_close, delay(mkt_close, 20)), 1)",
    "vol_20": "ts_std(sub(div(mkt_close, delay(mkt_close, 1)), 1), 20)",
    "ma_bias": "sub(div(mkt_close, ts_mean(mkt_close, 20)), 1)",
    "amount_z": "div(sub(mkt_amount, ts_mean(mkt_amount, 20)), add(ts_std(mkt_amount, 20), 1))",
    "hl_range": "div(sub(mkt_high, mkt_low), mkt_close)",
}

_PRIMITIVE_EXPR = {k: parse_formula(v) for k, v in MARKET_PRIMITIVES.items()}
_PRIMITIVE_NAMES = tuple(MARKET_PRIMITIVES.keys())


def _spearman(a: pd.Series, b: pd.Series, *, min_n: int = 8) -> float:
    aligned = pd.concat([a, b], axis=1, keys=["a", "b"]).dropna()
    if len(aligned) < min_n:
        return float("nan")
    ra = aligned["a"].rank(method="average")
    rb = aligned["b"].rank(method="average")
    return float(ra.corr(rb, method="pearson"))


def gp_string_to_formula(raw: str, feature_names: list[str] | tuple[str, ...] = _PRIMITIVE_NAMES) -> str:
    """Translate a gplearn program string into a FactorExpr print string."""
    text = (raw or "").strip()
    if not text:
        raise FactorExprError("空程序")
    names = list(feature_names)
    for i, name in reversed(list(enumerate(names))):
        text = text.replace(f"X{i}", name)
    expr = parse_formula(text, extra_vars=frozenset(names))
    expanded = substitute_vars(expr, _PRIMITIVE_EXPR)
    return print_expr(expanded)


def market_feature_frame(panel: Panel, forward_days: int = FORWARD_DAYS) -> tuple[pd.DataFrame, pd.Series]:
    if "mkt_close" not in panel:
        raise FactorExprError("择时需要 mkt_close")
    close = collapse_to_series(panel["mkt_close"])
    fwd = close.shift(-forward_days) / close - 1.0
    cols: dict[str, pd.Series] = {}
    for name, expr in _PRIMITIVE_EXPR.items():
        try:
            values = compute_expr(expr, panel, allow_cross_section=False)
        except Exception:
            continue
        cols[name] = collapse_to_series(values)
    if not cols:
        raise FactorExprError("大盘原语全部计算失败")
    frame = pd.DataFrame(cols).replace([np.inf, -np.inf], np.nan)
    aligned = frame.join(fwd.rename("y"), how="inner").dropna()
    if len(aligned) < 40:
        raise FactorExprError(f"有效交易日不足（{len(aligned)}）")
    return aligned[list(cols.keys())], aligned["y"]


def walk_forward_scores(
    signal: pd.Series,
    fwd: pd.Series,
    *,
    folds: int = 3,
    gap: int = FORWARD_DAYS,
) -> list[float]:
    aligned = pd.concat([signal, fwd], axis=1, keys=["s", "r"]).dropna()
    n = len(aligned)
    test_len = max(8, n // (folds + 1))
    scores: list[float] = []
    for i in range(folds):
        te_end = n - (folds - 1 - i) * test_len
        te_start = te_end - test_len
        if te_start - gap < 16 or te_end - te_start < 8:
            continue
        te = aligned.iloc[te_start:te_end]
        scores.append(_spearman(te["s"], te["r"]))
    return scores


def _gp_metric(y, y_pred, w):  # noqa: ANN001
    y = np.asarray(y, dtype=float)
    pred = np.asarray(y_pred, dtype=float)
    mask = np.isfinite(y) & np.isfinite(pred)
    if int(mask.sum()) < 8:
        return 0.0
    yr = pd.Series(y[mask]).rank().to_numpy()
    pr = pd.Series(pred[mask]).rank().to_numpy()
    if float(np.std(yr)) < 1e-12 or float(np.std(pr)) < 1e-12:
        return 0.0
    rho = float(np.corrcoef(yr, pr)[0, 1])
    if rho != rho:
        return 0.0
    return abs(rho)


def _make_id(formula: str) -> str:
    digest = hashlib.sha1(formula.encode("utf-8")).hexdigest()[:6]
    return f"gp_mkt_{digest}"


def _collect_programs(est: Any, feature_names: list[str]) -> list[tuple[str, int, float]]:
    seen: set[str] = set()
    out: list[tuple[str, int, float]] = []
    gens = getattr(est, "_programs", None) or []
    last = gens[-1] if gens else []
    programs = list(last)
    best = getattr(est, "_program", None)
    if best is not None:
        programs.append(best)
    for prog in programs:
        if prog is None:
            continue
        raw = str(prog)
        if raw in seen:
            continue
        seen.add(raw)
        length = int(getattr(prog, "length_", 0) or 0)
        fit = float(getattr(prog, "raw_fitness_", 0.0) or 0.0)
        out.append((raw, length, fit))
    out.sort(key=lambda row: row[2], reverse=True)
    _ = feature_names
    return out


def _new_estimator(names: list[str], population: int, seed: int = 7):
    from gplearn.fitness import make_fitness
    from gplearn.genetic import SymbolicRegressor

    metric = make_fitness(function=_gp_metric, greater_is_better=True, wrap=False)
    return SymbolicRegressor(
        population_size=population,
        generations=1,
        tournament_size=min(20, max(5, population // 4)),
        stopping_criteria=1.0,
        const_range=(-2.0, 2.0),
        init_depth=(2, 4),
        function_set=("add", "sub", "mul", "div", "abs", "log", "sqrt"),
        metric=metric,
        parsimony_coefficient=0.008,
        max_samples=1.0,
        verbose=0,
        n_jobs=1,
        random_state=seed,
        warm_start=True,
        feature_names=names,
    )


def _fit_generation(est: Any, X: np.ndarray, y: np.ndarray, generation: int) -> Any:
    est.set_params(generations=generation)
    est.fit(X, y)
    return est


async def run_gp_market(run_id: str, body: FactorMineGpRequest) -> None:
    funnel = {"proposed": 0, "parse_fail": 0, "evaled": 0, "passed": 0, "rejected": 0}
    accepted: list[str] = []
    directory = _run_dir(run_id)
    try:
        _patch_progress(run_id, message="准备大盘面板…", rounds=body.generations, round=0)
        if body.use_synthetic:
            panel = synthetic_panel(n_stocks=8, n_days=160, seed=11)
        else:
            panel, _meta = await load_qlib_eval_panel(None, body.lookback)
        features, fwd = market_feature_frame(panel)
        names = list(features.columns)
        close = collapse_to_series(panel["mkt_close"])
        split = max(40, int(len(features) * 0.7))
        train = features.iloc[:split]
        X = train.to_numpy(dtype=float)
        y = fwd.reindex(train.index).to_numpy(dtype=float)

        est = _new_estimator(names, body.population)
        for gen in range(1, body.generations + 1):
            est = await asyncio.to_thread(_fit_generation, est, X, y, gen)
            _patch_progress(
                run_id,
                round=gen,
                rounds=body.generations,
                message=f"进化 {gen}/{body.generations} 代…",
                funnel=dict(funnel),
            )
        programs = _collect_programs(est, names)
        _patch_progress(run_id, message=f"转译 {len(programs)} 条程序…")

        ranked: list[dict[str, Any]] = []
        for raw, length, fit in programs:
            funnel["proposed"] += 1
            if length > MAX_PROG_LEN:
                funnel["parse_fail"] += 1
                _append_jsonl(
                    directory / "candidates.jsonl",
                    {"raw": raw, "outcome": "too_complex", "length": length},
                )
                continue
            try:
                formula = gp_string_to_formula(raw, names)
                expr = parse_formula(formula)
            except FactorExprError as exc:
                funnel["parse_fail"] += 1
                _append_jsonl(
                    directory / "candidates.jsonl",
                    {"raw": raw, "outcome": "parse_fail", "detail": str(exc)},
                )
                continue
            signal = collapse_to_series(compute_expr(expr, panel, allow_cross_section=False))
            cheat_ret = _spearman(signal, collapse_to_series(compute_expr(_PRIMITIVE_EXPR["ret_1"], panel)))
            cheat_px = _spearman(signal, close)
            cheat_hit = None
            if cheat_ret == cheat_ret and abs(cheat_ret) > CHEAT_CORR:
                cheat_hit = f"与昨日收益相关 {cheat_ret:.3f}"
            elif cheat_px == cheat_px and abs(cheat_px) > CHEAT_CORR:
                cheat_hit = f"与收盘价相关 {cheat_px:.3f}"
            if cheat_hit:
                funnel["rejected"] += 1
                _append_jsonl(
                    directory / "candidates.jsonl",
                    {
                        "raw": raw,
                        "formula": formula,
                        "outcome": "cheat",
                        "detail": cheat_hit,
                    },
                )
                continue
            wf = walk_forward_scores(signal, fwd)
            mean_abs = float(np.nanmean([abs(s) for s in wf])) if wf else 0.0
            ranked.append(
                {
                    "raw": raw,
                    "formula": formula,
                    "length": length,
                    "fit": fit,
                    "wf": wf,
                    "mean_abs": mean_abs,
                    "nodes": node_count(expr),
                    "cheat": cheat_ret,
                }
            )

        ranked.sort(key=lambda r: r["mean_abs"], reverse=True)
        for item in ranked[:KEEP_EVAL]:
            factor_id = _make_id(item["formula"])
            if factor_store.get(factor_id) is not None:
                funnel["parse_fail"] += 1
                _append_jsonl(directory / "candidates.jsonl", {**item, "outcome": "duplicate"})
                continue
            short = item["formula"] if len(item["formula"]) < 42 else item["formula"][:40] + "…"
            try:
                rec = factor_store.create(
                    FactorCreate(
                        id=factor_id,
                        name=f"GP择时 {short}",
                        formula=item["formula"],
                        hypothesis="",
                        theme=["market"],
                        universe="market",
                        origin="gp",
                    )
                )
            except (FactorStoreError, FactorExprError) as exc:
                funnel["parse_fail"] += 1
                _append_jsonl(
                    directory / "candidates.jsonl",
                    {**item, "outcome": "parse_fail", "detail": str(exc)},
                )
                continue

            _patch_progress(run_id, message=f"准入评测 {rec.id}…", funnel=dict(funnel))
            try:
                result = await evaluate_request(
                    factor_id=rec.id,
                    formula=None,
                    universe="market",
                    symbols=None,
                    lookback=body.lookback,
                    use_synthetic=body.use_synthetic,
                    persist=True,
                )
            except Exception as exc:  # noqa: BLE001
                funnel["evaled"] += 1
                funnel["rejected"] += 1
                _append_jsonl(
                    directory / "candidates.jsonl",
                    {**item, "id": rec.id, "outcome": "eval_error", "detail": str(exc)},
                )
                continue

            funnel["evaled"] += 1
            metrics = result.get("metrics") or {}
            status = str(metrics.get("status") or "")
            reason = str(metrics.get("reject_reason") or "")
            passed = status in {"passed_auto", "paper_tracking", "live"}
            if passed:
                funnel["passed"] += 1
                accepted.append(rec.id)
                outcome = "passed"
            else:
                funnel["rejected"] += 1
                outcome = "rejected"
            _append_jsonl(
                directory / "candidates.jsonl",
                {
                    **item,
                    "id": rec.id,
                    "outcome": outcome,
                    "detail": reason or status,
                    "status": status,
                    "ic_mean": (metrics.get("ic_stats") or {}).get("ic_mean"),
                },
            )

        report = [
            f"# GP 大盘择时 {run_id}",
            "",
            f"- 种群 {body.population} · 代数 {body.generations} · 合成={body.use_synthetic}",
            f"- 提议 {funnel['proposed']} · 解析失败 {funnel['parse_fail']}",
            f"- 评测 {funnel['evaled']} · 过关 {funnel['passed']} · 淘汰 {funnel['rejected']}",
            f"- 过关 id: {', '.join(accepted) or '无'}",
            "",
            "GP 因子没有经济逻辑，最多停在 passed_auto，不会自动 live。",
            "",
        ]
        (_run_dir(run_id) / "report.md").write_text("\n".join(report), encoding="utf-8")
        _patch_progress(
            run_id,
            status="done",
            round=body.generations,
            message=f"完成。过关 {funnel['passed']} / 发明 {funnel['proposed']}",
            funnel=funnel,
            accepted_ids=accepted,
        )
    except Exception as exc:  # noqa: BLE001
        _patch_progress(
            run_id,
            status="error",
            message="GP 挖掘失败",
            error=str(exc),
            funnel=funnel,
            accepted_ids=accepted,
        )
        raise
    finally:
        if _lock_path().exists():
            import json

            try:
                lock = json.loads(_lock_path().read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                lock = {}
            if lock.get("run_id") == run_id:
                _lock_path().unlink(missing_ok=True)
