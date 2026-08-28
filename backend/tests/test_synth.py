from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.factors.evaluate import run_eval_on_panel
from app.factors.panel import synthetic_panel
from app.factors.paper import apply_gate5_status
from app.factors.store import FactorStore
from app.factors.synth import combine_factor_panels, synthesize_factors
from app.models.factors import FactorCreate, FactorEvalRequest, FactorSynthesizeRequest


class SynthCombineTests(unittest.TestCase):
    def test_equal_combine_shape(self) -> None:
        import pandas as pd

        a = pd.DataFrame([[1.0, 2.0], [3.0, 4.0]], index=["d1", "d2"], columns=["s1", "s2"])
        b = pd.DataFrame([[5.0, 6.0], [7.0, 8.0]], index=["d1", "d2"], columns=["s1", "s2"])
        out = combine_factor_panels([a, b], [1.0, 1.0])
        self.assertEqual(out.loc["d1", "s1"], 3.0)


class SynthStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_synthesize_two_factors(self) -> None:
        with TemporaryDirectory() as tmp:
            store = FactorStore(Path(tmp))
            store.ensure()
            from app.factors import evaluate as eval_mod
            from app.factors import store as store_mod
            from app.factors import synth as synth_mod

            store_mod.factor_store = store
            synth_mod.factor_store = store
            eval_mod.factor_store = store

            a = store.create(
                FactorCreate(
                    id="synth_a_mom",
                    name="A",
                    formula="sub(div(close, delay(close, 5)), 1)",
                    hypothesis="短期动量用于合成测试。",
                )
            )
            b = store.create(
                FactorCreate(
                    id="synth_b_rev",
                    name="B",
                    formula="sub(div(delay(close, 5), close), 1)",
                    hypothesis="短期反转用于合成测试。",
                )
            )
            panel = synthetic_panel(n_stocks=10, n_days=100, seed=21)
            for fid in (a.id, b.id):
                rec = store.get(fid)
                assert rec is not None
                run_eval_on_panel(rec=rec, formula=None, universe="csi300", panel=panel, persist=True)

            from app.models.factors import FactorUpdate

            for fid in (a.id, b.id):
                store.update(fid, FactorUpdate(status="passed_auto"))

            out = await synthesize_factors(
                FactorSynthesizeRequest(
                    method="equal",
                    factor_ids=[a.id, b.id],
                    use_synthetic=True,
                )
            )
            self.assertIn("factor", out)
            fid = out["factor"]["id"]
            rec = store.get(fid)
            self.assertIsNotNone(rec)
            assert rec is not None
            self.assertEqual(rec.origin, "synth")
            self.assertIn("synth", rec.metrics)
            self.assertEqual(len(rec.metrics["synth"]["components"]), 2)

            reeval = run_eval_on_panel(rec=rec, formula=None, universe="csi300", panel=panel, persist=True)
            self.assertIn("metrics", reeval)


class PaperGateTests(unittest.TestCase):
    def test_freeze_after_no_improve(self) -> None:
        from app.models.factors import FactorRecord

        rec = FactorRecord(
            id="paper_test",
            name="t",
            origin="synth",
            status="paper_tracking",
            formula="rank(close)",
            expr={"var": "close"},
            created_at="2020-01-01T00:00:00Z",
            metrics={
                "paper_history": {
                    "started_at": "2020-01-01T00:00:00Z",
                    "last_improved_at": "2020-01-01T00:00:00Z",
                    "best_ic_mean": 0.05,
                    "checks": [],
                }
            },
        )
        status, reason, _metrics = apply_gate5_status(rec, 0.04, dict(rec.metrics))
        self.assertEqual(status, "frozen")
        self.assertIn("冻结", reason)


if __name__ == "__main__":
    unittest.main()
