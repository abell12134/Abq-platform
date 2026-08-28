from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.factors.agent_tools import (
    compute_factor_snapshot,
    factor_analysis_summary,
    list_factors_for_agent,
)
from app.factors.store import FactorStore
from app.models.factors import FactorCreate, FactorUpdate
from app.tools.langchain_tools import TOOL_BY_NAME


class FactorAgentToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_factors_synthetic_store(self) -> None:
        with TemporaryDirectory() as tmp:
            store = FactorStore(Path(tmp))
            store.ensure()
            store.create(
                FactorCreate(
                    id="tool_test_mom",
                    name="工具测试动量",
                    formula="sub(div(close, delay(close, 5)), 1)",
                    hypothesis="测试",
                    theme=["momentum"],
                    universe="csi300",
                    origin="manual",
                )
            )
            store.update("tool_test_mom", FactorUpdate(status="passed_auto"))
            from app.factors import agent_tools as mod

            old = mod.factor_store
            mod.factor_store = store
            try:
                out = await list_factors_for_agent(limit=50)
                self.assertGreaterEqual(out["count"], 1)
                ids = [f["id"] for f in out["factors"]]
                self.assertIn("tool_test_mom", ids)
            finally:
                mod.factor_store = old

    async def test_compute_factor_synthetic(self) -> None:
        with TemporaryDirectory() as tmp:
            store = FactorStore(Path(tmp))
            store.ensure()
            store.create(
                FactorCreate(
                    id="tool_test_mom",
                    name="工具测试动量",
                    formula="sub(div(close, delay(close, 5)), 1)",
                    hypothesis="",
                    theme=["momentum"],
                    universe="csi300",
                    origin="manual",
                )
            )
            from app.factors import agent_tools as mod

            old = mod.factor_store
            mod.factor_store = store
            try:
                snap = await compute_factor_snapshot("tool_test_mom", "s00", use_synthetic=True, lookback=80)
                self.assertEqual(snap["status"], "ok")
                self.assertIn("value", snap)
            finally:
                mod.factor_store = old

    def test_factor_analysis_missing(self) -> None:
        out = factor_analysis_summary("no_such_factor")
        self.assertEqual(out["status"], "error")

    def test_tools_registered(self) -> None:
        for name in ("list_factors", "compute_factor", "factor_analysis"):
            self.assertIn(name, TOOL_BY_NAME)


if __name__ == "__main__":
    unittest.main()
