"""Factor screener tests."""

from __future__ import annotations

import unittest

from app.factors.screener import apply_screen_to_portfolio, run_factor_screen
from app.factors.store import factor_store
from app.models.factors import FactorScreenApplyRequest, FactorScreenRequest
from app.models.portfolio import PortfolioUpdate
from app.persistence.portfolio_store import portfolio_store


class FactorScreenTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        factor_store.ensure()
        portfolio_store.ensure()
        rec = portfolio_store.get("default")
        assert rec is not None
        self._default_members = list(rec.members)

    async def asyncTearDown(self) -> None:
        portfolio_store.update("default", PortfolioUpdate(members=self._default_members))

    async def test_synthetic_screen_returns_ranked_picks(self) -> None:
        factors = [f for f in factor_store.list_factors() if f.universe == "csi300"][:2]
        if len(factors) < 2:
            self.skipTest("need at least 2 csi300 factors")
        body = FactorScreenRequest(
            universe="csi300",
            factor_ids=[f.id for f in factors],
            top_n=5,
            use_synthetic=True,
        )
        result = await run_factor_screen(body)
        self.assertEqual(result["status"], "ok")
        self.assertGreaterEqual(len(result["picks"]), 1)
        self.assertLessEqual(len(result["picks"]), 5)
        self.assertIn("score", result["picks"][0])

    def test_apply_screen_merge(self) -> None:
        rec = portfolio_store.get("default")
        assert rec is not None
        before = len(rec.members)
        out = apply_screen_to_portfolio(
            FactorScreenApplyRequest(
                portfolio_id="default",
                symbols=["sh601318"],
                mode="merge",
            )
        )
        self.assertEqual(out["status"], "ok")
        updated = portfolio_store.get("default")
        assert updated is not None
        self.assertGreaterEqual(len(updated.members), before)

    def test_apply_screen_replace(self) -> None:
        symbols = ["sh600519", "sz000001"]
        out = apply_screen_to_portfolio(
            FactorScreenApplyRequest(
                portfolio_id="default",
                symbols=symbols,
                mode="replace",
            )
        )
        self.assertEqual(out["member_count"], 2)
        updated = portfolio_store.get("default")
        assert updated is not None
        self.assertEqual([m.symbol for m in updated.members], symbols)


class ComposeScreenIntentTests(unittest.TestCase):
    def test_screen_intent(self) -> None:
        from app.orchestration.compose_route import is_factor_screen_intent, route_compose

        msg = "用因子从沪深300选出20只股票"
        self.assertTrue(is_factor_screen_intent(msg))
        out = route_compose(msg, kind="single")
        self.assertEqual(out.get("intent"), "factor_screen")


if __name__ == "__main__":
    unittest.main()
