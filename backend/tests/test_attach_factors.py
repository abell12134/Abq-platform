from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.factors import agent_tools as attach_mod
from app.factors.attach import attach_factors_for_symbol
from app.factors.store import FactorStore
from app.models.analysis import AnalysisStep
from app.models.factors import FactorCreate, FactorUpdate
from app.orchestration.graphs.single_ticket import _stream_phase_update


class StreamPhaseUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_yields_steps_then_update_dict(self) -> None:
        async def phase(*, on_step=None, symbol: str = "") -> dict:
            if on_step is not None:
                await on_step(
                    AnalysisStep(
                        id="s1",
                        agent="fetch_quote",
                        role="tool",
                        result=symbol,
                    )
                )
            return {"ok": True, "symbol": symbol}

        items: list[object] = []
        async for item in _stream_phase_update(phase, symbol="600363"):
            items.append(item)

        self.assertEqual(len(items), 2)
        self.assertIsInstance(items[0], AnalysisStep)
        self.assertEqual(items[1], {"ok": True, "symbol": "600363"})


class AttachFactorsTests(unittest.IsolatedAsyncioTestCase):
    async def test_attach_synthetic_panel(self) -> None:
        with TemporaryDirectory() as tmp:
            store = FactorStore(Path(tmp))
            store.ensure()
            store.create(
                FactorCreate(
                    id="test_mom",
                    name="测试动量",
                    formula="sub(div(close, delay(close, 5)), 1)",
                    hypothesis="",
                    theme=["momentum"],
                    universe="csi300",
                    origin="manual",
                )
            )
            store.update("test_mom", FactorUpdate(status="passed_auto"))
            old = attach_mod.factor_store
            attach_mod.factor_store = store
            try:
                summary, findings = await attach_factors_for_symbol(
                    "s00",
                    use_synthetic=True,
                    lookback=80,
                )
            finally:
                attach_mod.factor_store = old
            self.assertIsNotNone(summary)
            self.assertGreater(len(findings), 0)
            self.assertIn("因子截面", summary or "")


if __name__ == "__main__":
    unittest.main()
