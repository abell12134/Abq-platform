from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.factors.compute import compute_expr
from app.factors.eval_ic import forward_returns, rank_ic_series
from app.factors.evaluate import run_eval_on_panel
from app.factors.ir import FactorExprError, parse_formula, print_expr
from app.factors.panel import synthetic_panel
from app.factors.seeds import seed_payloads
from app.factors.store import FactorStore, FactorStoreError
from app.models.factors import FactorCreate


class FactorIrTests(unittest.TestCase):
    def test_parse_print_roundtrip(self) -> None:
        src = "sub(div(close, delay(close, 20)), 1)"
        expr = parse_formula(src)
        self.assertEqual(parse_formula(print_expr(expr)), expr)

    def test_rejects_negative_delay(self) -> None:
        with self.assertRaises(FactorExprError):
            parse_formula("delay(close, -1)")

    def test_rejects_unknown_op_and_eval_style(self) -> None:
        with self.assertRaises(FactorExprError):
            parse_formula("__import__('os')")
        with self.assertRaises(FactorExprError):
            parse_formula("close.shift(1)")

    def test_seeds_parse(self) -> None:
        for seed in seed_payloads():
            expr = parse_formula(seed["formula"])
            self.assertTrue(print_expr(expr))


class FactorComputeTests(unittest.TestCase):
    def test_compute_mom_monotonic(self) -> None:
        panel = synthetic_panel(n_stocks=8, n_days=60, seed=3)
        expr = parse_formula("sub(div(close, delay(close, 5)), 1)")
        values = compute_expr(expr, panel)
        self.assertEqual(values.shape[1], 8)
        self.assertGreater(values.dropna(how="all").shape[0], 20)

    def test_rank_ic_on_synthetic(self) -> None:
        panel = synthetic_panel()
        expr = parse_formula("sub(div(close, delay(close, 5)), 1)")
        factor = compute_expr(expr, panel)
        ic = rank_ic_series(factor, forward_returns(panel["close"], 5))
        self.assertGreaterEqual(ic.dropna().shape[0], 5)

    def test_eval_catalog_formula_synthetic(self) -> None:
        panel = synthetic_panel()
        out = run_eval_on_panel(
            rec=None,
            formula="sub(div(close, delay(close, 5)), 1)",
            universe="csi300",
            panel=panel,
            persist=False,
        )
        self.assertEqual(out["metrics"]["mode"], "cs")
        self.assertIn("gate1_passed", out["metrics"])


class FactorStoreTests(unittest.TestCase):
    def test_store_create_and_delete(self) -> None:
        with TemporaryDirectory() as tmp:
            store = FactorStore(Path(tmp))
            store.ensure()
            listed = store.list_factors()
            self.assertTrue(any(f.id == "mom_20" for f in listed))
            rec = store.create(
                FactorCreate(
                    id="manual_test_mom",
                    name="手工测试",
                    formula="div(close, mkt_close)",
                    hypothesis="相对强弱手工因子用于单测。",
                )
            )
            self.assertEqual(rec.origin, "manual")
            self.assertEqual(rec.status, "candidate")
            self.assertTrue(store.delete("manual_test_mom"))
            with self.assertRaises(FactorStoreError):
                store.delete("mom_20")


class FactorMineParseTests(unittest.TestCase):
    def test_extract_fenced_json(self) -> None:
        from app.factors.mine_llm import extract_json_value, make_factor_id, proposals_from_payload

        payload = extract_json_value(
            '前言\n```json\n{"factors":[{"name":"动量","theme":"momentum",'
            '"hypothesis":"涨的还会涨一段时间","formula":"sub(div(close, delay(close, 10)), 1)"}]}\n```'
        )
        items = proposals_from_payload(payload)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "动量")
        self.assertTrue(make_factor_id(items[0]["formula"], "momentum").startswith("llm_momentum_"))

    def test_rejects_unknown_operator(self) -> None:
        from app.factors.ir import FactorExprError, parse_formula

        with self.assertRaises(FactorExprError):
            parse_formula("pd.eval(close)")


class FactorGpTests(unittest.TestCase):
    def test_gp_string_to_formula_expands_primitives(self) -> None:
        from app.factors.ir import parse_formula, print_expr
        from app.factors.mine_gp import gp_string_to_formula

        named = gp_string_to_formula("mul(ma_bias, vol_20)")
        expr = parse_formula(named)
        self.assertIn("mkt_close", print_expr(expr))
        self.assertNotIn("ma_bias", print_expr(expr))

        via_x = gp_string_to_formula("add(X3, 0.5)")
        self.assertTrue(via_x.startswith("add("))
        parse_formula(via_x)

    def test_extra_vars_rejected_without_flag(self) -> None:
        with self.assertRaises(FactorExprError):
            parse_formula("ret_1")

    def test_market_feature_frame_and_tiny_fit(self) -> None:
        from app.factors.mine_gp import (
            _collect_programs,
            _fit_generation,
            _new_estimator,
            gp_string_to_formula,
            market_feature_frame,
        )

        panel = synthetic_panel(n_stocks=8, n_days=160, seed=11)
        features, fwd = market_feature_frame(panel)
        self.assertGreaterEqual(len(features), 40)
        names = list(features.columns)
        split = max(40, int(len(features) * 0.7))
        train = features.iloc[:split]
        X = train.to_numpy(dtype=float)
        y = fwd.reindex(train.index).to_numpy(dtype=float)
        est = _new_estimator(names, population=20, seed=3)
        est = _fit_generation(est, X, y, 1)
        programs = _collect_programs(est, names)
        self.assertTrue(programs)
        formula = gp_string_to_formula(programs[0][0], names)
        parse_formula(formula)

    def test_price_level_is_cheat(self) -> None:
        from app.factors.compute import compute_expr
        from app.factors.mine_gp import CHEAT_CORR, _spearman
        from app.factors.panel import collapse_to_series

        panel = synthetic_panel(n_stocks=8, n_days=80, seed=4)
        signal = collapse_to_series(compute_expr(parse_formula("mkt_close"), panel, allow_cross_section=False))
        close = collapse_to_series(panel["mkt_close"])
        self.assertGreater(abs(_spearman(signal, close)), CHEAT_CORR)


if __name__ == "__main__":
    unittest.main()
