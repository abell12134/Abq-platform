from __future__ import annotations

import unittest

from app.factors.mine_tools import mine_status
from app.models.factors import FactorMineLlmRequest
from app.orchestration.nl_plan import is_factor_mine_intent
from app.orchestration.compose_route import route_compose
from app.orchestration.pipeline_phases import resolve_market_agent_ids, resolve_portfolio_agent_ids
from app.models.analysis import AnalyzeRequest


class ComposeMarketRouteTests(unittest.TestCase):
    def test_market_keywords_without_symbol(self) -> None:
        out = route_compose("最近大盘怎么样，情绪如何")
        self.assertEqual(out["kind"], "market")
        self.assertIn("market", out["agent_ids"])
        self.assertEqual(out["target"], "sh000300")

    def test_single_when_symbol_present(self) -> None:
        out = route_compose("看 600519 大盘联动")
        self.assertEqual(out["kind"], "single")
        self.assertIsNotNone(out["target"])

    def test_resolve_market_agent_ids(self) -> None:
        req = AnalyzeRequest(message="x", agent_ids=["market", "nope"])
        self.assertEqual(resolve_market_agent_ids(req), ("market",))

    def test_factor_mine_intent_without_symbol(self) -> None:
        msg = "用 LLM 帮我挖 2 个动量因子"
        self.assertTrue(is_factor_mine_intent(msg))
        out = route_compose(msg)
        self.assertEqual(out.get("intent"), "factor_mine")
        self.assertEqual(out["agent_ids"], [])
        self.assertIn("plan", out)
        self.assertEqual(out["plan"]["mode"], "llm")
        self.assertEqual(out["plan"]["k"], 2)
        self.assertEqual(out["plan"]["theme_hint"], "动量")
        self.assertIsNone(out["target"])

    def test_factor_mine_not_triggered_with_symbol(self) -> None:
        msg = "600519 技术面"
        self.assertFalse(is_factor_mine_intent(msg))


class MineToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_mine_status_idle(self) -> None:
        out = mine_status()
        self.assertIn(out["status"], {"idle", "running", "done", "error"})


if __name__ == "__main__":
    unittest.main()
