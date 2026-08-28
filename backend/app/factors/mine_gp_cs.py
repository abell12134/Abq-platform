"""GP track B: cross-section factor discovery with daily Rank IC fitness.

Unlike gplearn track A (timing), fitness is computed per-date Spearman on a
stock panel. Individuals are FactorExpr trees over named primitives.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import random
from typing import Any

import pandas as pd

from app.factors.compute import compute_expr
from app.factors.eval_ic import (
    FORWARD_DAYS,
    ic_summary,
    mean_cs_corr,
    rank_ic_series,
    winsorize_cross_sectional,
)
from app.factors.evaluate import evaluate_request, load_qlib_eval_panel
from app.factors.ir import (
    Const,
    Expr,
    FactorExprError,
    Op,
    Var,
    expr_from_dict,
    node_count,
    parse_formula,
    print_expr,
    substitute_vars,
)
from app.factors.mine_gp import MAX_PROG_LEN
from app.factors.mine_llm import (
    _append_jsonl,
    _lock_path,
    _patch_progress,
    _run_dir,
    active_run_id,
    init_generic_run,
)
from app.factors.panel import synthetic_panel
from app.factors.store import FactorStoreError, factor_store
from app.models.factors import FactorCreate, FactorMineGpRequest

PARSIMONY = 0.012
CHEAT_CORR = 0.7
KEEP_EVAL = 5
MAX_DEPTH = 4
BINARY_OPS = ("add", "sub", "mul", "div")
UNARY_OPS = ("abs", "neg")

# Named primitives → full FactorExpr (expanded before compute).
CS_PRIMITIVES: dict[str, str] = {
    "prim_mom5": "sub(div(close, delay(close, 5)), 1)",
    "prim_mom20": "sub(div(close, delay(close, 20)), 1)",
    "prim_rev1": "sub(div(delay(close, 1), close), 1)",
    "prim_vol20": "ts_std(sub(div(close, delay(close, 1)), 1), 20)",
    "prim_range": "div(sub(high, low), close)",
    "prim_vratio": "div(volume, ts_mean(volume, 20))",
    "prim_rel_mkt": "sub(div(close, mkt_close), 1)",
    "prim_mkt_mom": "sub(div(mkt_close, delay(mkt_close, 5)), 1)",
    "prim_amt_z": "div(sub(amount, ts_mean(amount, 20)), add(ts_std(amount, 20), 1))",
    "prim_close_ma": "sub(div(close, ts_mean(close, 20)), 1)",
}

_PRIMITIVE_EXPR = {k: parse_formula(v) for k, v in CS_PRIMITIVES.items()}
_PRIMITIVE_NAMES = tuple(CS_PRIMITIVES.keys())


def _neg(x: Expr) -> Expr:
    return Op("mul", (Const(-1.0), x))


def expand_cs_expr(expr: Expr) -> Expr:
    return substitute_vars(expr, _PRIMITIVE_EXPR)


def random_tree(rng: random.Random, *, max_depth: int = MAX_DEPTH) -> Expr:
    if max_depth <= 0 or (max_depth < 3 and rng.random() < 0.55):
        return Var(rng.choice(_PRIMITIVE_NAMES))
    if rng.random() < 0.12:
        return Const(round(rng.uniform(-1.5, 1.5), 2))
    if rng.random() < 0.18:
        op = rng.choice(UNARY_OPS)
        child = random_tree(rng, max_depth=max_depth - 1)
        if op == "abs":
            return Op("abs", (child,))
        return _neg(child)
    op = rng.choice(BINARY_OPS)
    return Op(
        op,
        (
            random_tree(rng, max_depth=max_depth - 1),
            random_tree(rng, max_depth=max_depth - 1),
        ),
    )


def _get_at(expr: Expr, path: list[int]) -> Expr:
    node = expr
    for i in path:
        if not isinstance(node, Op):
            break
        node = node.args[i]
    return node


def _replace_at(expr: Expr, path: list[int], new_sub: Expr) -> Expr:
    if not path:
        return new_sub
    if not isinstance(expr, Op):
        return new_sub
    i, *rest = path
    args = list(expr.args)
    args[i] = _replace_at(args[i], rest, new_sub)
    return Op(expr.op, tuple(args))


def _random_path(expr: Expr, rng: random.Random) -> list[int]:
    path: list[int] = []
    node: Expr = expr
    while isinstance(node, Op) and node.args and rng.random() < 0.65:
        idx = rng.randrange(len(node.args))
        path.append(idx)
        node = node.args[idx]
    return path


def mutate_tree(expr: Expr, rng: random.Random) -> Expr:
    if rng.random() < 0.2:
        return random_tree(rng)
    path = _random_path(expr, rng)
    return _replace_at(expr, path, random_tree(rng, max_depth=2))


def crossover_tree(a: Expr, b: Expr, rng: random.Random) -> Expr:
    path_a = _random_path(a, rng)
    path_b = _random_path(b, rng)
    sub = copy.deepcopy(_get_at(b, path_b))
    return _replace_at(copy.deepcopy(a), path_a, sub)


def cs_fitness(
    expr: Expr,
    panel: dict[str, pd.DataFrame],
    fwd: pd.DataFrame,
    library: dict[str, pd.DataFrame],
    *,
    train_frac: float = 0.7,
) -> tuple[float, dict[str, Any]]:
    meta: dict[str, Any] = {}
    try:
        expanded = expand_cs_expr(expr)
        if node_count(expanded) > MAX_PROG_LEN:
            return 0.0, {"outcome": "too_complex"}
        values = compute_expr(expanded, panel, allow_cross_section=True)
        values = winsorize_cross_sectional(values)
        ic = rank_ic_series(values, fwd)
        valid = ic.dropna()
        if len(valid) < 12:
            return 0.0, {"outcome": "ic_short"}
        split = max(6, int(len(valid) * train_frac))
        train = valid.iloc[:split]
        tr = ic_summary(train)
        ic_mean = tr.get("ic_mean")
        if ic_mean is None:
            return 0.0, {"outcome": "ic_nan"}
        for _fid, lib_df in library.items():
            corr = mean_cs_corr(values, lib_df)
            if corr == corr and abs(corr) > CHEAT_CORR:
                return 0.0, {"outcome": "corr_dup", "corr": corr}
        fitness = abs(float(ic_mean)) / (1.0 + PARSIMONY * node_count(expanded))
        meta.update({"ic_mean": ic_mean, "icir": tr.get("icir"), "fitness": fitness})
        return fitness, meta
    except Exception as exc:  # noqa: BLE001
        return 0.0, {"outcome": "error", "detail": str(exc)}


def _library_values(panel: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for rec in factor_store.list_factors():
        if rec.universe == "market":
            continue
        try:
            expr = expand_cs_expr(expr_from_dict(rec.expr))
            out[rec.id] = compute_expr(expr, panel, allow_cross_section=True)
        except Exception:
            continue
        if len(out) >= 24:
            break
    return out


def tournament_select(
    population: list[tuple[Expr, float]],
    rng: random.Random,
    k: int = 5,
) -> Expr:
    picks = rng.sample(population, min(k, len(population)))
    picks.sort(key=lambda row: row[1], reverse=True)
    return picks[0][0]


def evolve_generation(
    population: list[tuple[Expr, float]],
    rng: random.Random,
    size: int,
) -> list[Expr]:
    next_gen: list[Expr] = []
    ranked = sorted(population, key=lambda row: row[1], reverse=True)
    elite_n = max(2, size // 10)
    for expr, _fit in ranked[:elite_n]:
        next_gen.append(copy.deepcopy(expr))
    while len(next_gen) < size:
        if rng.random() < 0.6:
            p1 = tournament_select(population, rng)
            p2 = tournament_select(population, rng)
            child = crossover_tree(p1, p2, rng)
        else:
            child = tournament_select(population, rng)
        if rng.random() < 0.35:
            child = mutate_tree(child, rng)
        next_gen.append(child)
    return next_gen[:size]


def _make_id(formula: str) -> str:
    digest = hashlib.sha1(formula.encode("utf-8")).hexdigest()[:6]
    return f"gp_cs_{digest}"


async def run_gp_cs(run_id: str, body: FactorMineGpRequest) -> None:
    funnel = {"proposed": 0, "parse_fail": 0, "evaled": 0, "passed": 0, "rejected": 0}
    accepted: list[str] = []
    directory = _run_dir(run_id)
    rng = random.Random(17)
    try:
        _patch_progress(run_id, message="准备截面面板…", rounds=body.generations, round=0)
        if body.use_synthetic:
            panel = synthetic_panel(n_stocks=12, n_days=160, seed=13)
        else:
            panel, _meta = await load_qlib_eval_panel(None, body.lookback)
        close = panel["close"]
        fwd = close.shift(-FORWARD_DAYS) / close - 1.0
        library = await asyncio.to_thread(_library_values, panel)

        pop_size = body.population
        population_exprs = [random_tree(rng) for _ in range(pop_size)]
        hall_of_fame: list[tuple[Expr, float, dict[str, Any]]] = []

        for gen in range(1, body.generations + 1):
            scored: list[tuple[Expr, float]] = []
            for expr in population_exprs:
                fit, meta = await asyncio.to_thread(cs_fitness, expr, panel, fwd, library)
                scored.append((expr, fit))
                if fit > 0:
                    hall_of_fame.append((copy.deepcopy(expr), fit, meta))
            hall_of_fame.sort(key=lambda row: row[1], reverse=True)
            hall_of_fame = hall_of_fame[: max(KEEP_EVAL * 4, 20)]
            best_fit = max((fit for _, fit in scored), default=0.0)
            _patch_progress(
                run_id,
                round=gen,
                rounds=body.generations,
                message=f"进化 {gen}/{body.generations} 代 · 最优适应度 {best_fit:.4f}",
                funnel=dict(funnel),
            )
            population_exprs = evolve_generation(scored, rng, pop_size)

        _patch_progress(run_id, message=f"转译 {len(hall_of_fame)} 条候选…")

        ranked: list[dict[str, Any]] = []
        seen: set[str] = set()
        for expr, fit, meta in hall_of_fame:
            funnel["proposed"] += 1
            try:
                expanded = expand_cs_expr(expr)
                formula = print_expr(expanded)
            except FactorExprError as exc:
                funnel["parse_fail"] += 1
                _append_jsonl(directory / "candidates.jsonl", {"outcome": "parse_fail", "detail": str(exc)})
                continue
            if formula in seen:
                continue
            seen.add(formula)
            if node_count(expanded) > MAX_PROG_LEN:
                funnel["parse_fail"] += 1
                continue
            ranked.append({"formula": formula, "fit": fit, "meta": meta, "nodes": node_count(expanded)})

        ranked.sort(key=lambda r: r["fit"], reverse=True)
        for item in ranked[:KEEP_EVAL]:
            factor_id = _make_id(item["formula"])
            if factor_store.get(factor_id) is not None:
                funnel["parse_fail"] += 1
                continue
            short = item["formula"] if len(item["formula"]) < 42 else item["formula"][:40] + "…"
            try:
                rec = factor_store.create(
                    FactorCreate(
                        id=factor_id,
                        name=f"GP截面 {short}",
                        formula=item["formula"],
                        hypothesis="",
                        theme=["momentum"],
                        universe=body.universe,
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
                    universe=body.universe,
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
            f"# GP 截面选股 {run_id}",
            "",
            f"- 种群 {body.population} · 代数 {body.generations} · universe={body.universe}",
            f"- 合成={body.use_synthetic}",
            f"- 提议 {funnel['proposed']} · 解析失败 {funnel['parse_fail']}",
            f"- 评测 {funnel['evaled']} · 过关 {funnel['passed']} · 淘汰 {funnel['rejected']}",
            f"- 过关 id: {', '.join(accepted) or '无'}",
            "",
            "截面 GP 无经济逻辑，最多停在 passed_auto。",
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
            message="截面 GP 挖掘失败",
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


def start_gp_run(body: FactorMineGpRequest) -> str:
    existing = active_run_id()
    if existing:
        raise RuntimeError(f"已有挖掘任务在跑（{existing}）")
    kind = "gp_cs" if body.track == "cs" else "gp_market"
    return init_generic_run(
        kind,
        {
            "universe": body.universe if body.track == "cs" else "market",
            "track": body.track,
            "population": body.population,
            "generations": body.generations,
            "rounds": body.generations,
            "use_synthetic": body.use_synthetic,
            "lookback": body.lookback,
        },
    )
