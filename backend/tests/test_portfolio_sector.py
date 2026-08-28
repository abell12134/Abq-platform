from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.data.sector_pulse import fetch_market_breadth, fetch_sector_pulse
from app.models.analysis import AnalyzeRequest
from app.orchestration.compose_route import route_compose
from app.orchestration.pipeline_phases import resolve_portfolio_agent_ids


class ComposePortfolioRouteTests(unittest.TestCase):
    def test_portfolio_keywords(self) -> None:
        out = route_compose("帮我看下自选组合强弱")
        self.assertEqual(out["kind"], "portfolio")
        self.assertIn("portfolio", out["agent_ids"])

    def test_multi_symbol_routes_portfolio(self) -> None:
        out = route_compose("对比 600519 和 600363")
        self.assertEqual(out["kind"], "portfolio")

    def test_resolve_portfolio_agent_ids(self) -> None:
        req = AnalyzeRequest(message="x", agent_ids=["portfolio", "tech"])
        self.assertEqual(resolve_portfolio_agent_ids(req), ("portfolio",))


class SectorPulseTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_market_breadth_shape(self) -> None:
        with patch(
            "app.data.sector_pulse._http_json",
            return_value={
                "data": {
                    "diff": [
                        {"f12": "000001", "f14": "上证指数", "f2": 3000, "f3": 0.1, "f104": 1200, "f105": 800, "f106": 50},
                        {"f12": "399001", "f14": "深证成指", "f2": 10000, "f3": -0.2, "f104": 1500, "f105": 1100, "f106": 60},
                    ]
                }
            },
        ):
            out = await fetch_market_breadth()
        self.assertIn(out.get("status"), {"ok", "partial"})
        self.assertEqual(out.get("advance"), 2700)
        self.assertIn("indices", out)

    async def test_fetch_sector_pulse_shape(self) -> None:
        with patch(
            "app.data.sector_pulse._http_json",
            return_value={"data": {"diff": []}},
        ):
            out = await fetch_sector_pulse(theme_hint="新能源")
        self.assertIn(out.get("status"), {"ok", "unavailable"})
        self.assertIn("top_gainers", out)


if __name__ == "__main__":
    unittest.main()
