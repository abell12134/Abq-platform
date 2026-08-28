from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.data.portfolio_snapshot import build_portfolio_snapshot
from app.models.portfolio import PortfolioMember, PortfolioRecord, TrackRecordCreate
from app.persistence.portfolio_store import portfolio_store


class PortfolioSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_snapshot_equal_weight(self) -> None:
        rec = PortfolioRecord(
            id="test-pf",
            name="测试",
            members=[
                PortfolioMember(symbol="sh600519"),
                PortfolioMember(symbol="sh600363"),
            ],
        )
        quote_side_effect = [
            {"symbol": "sh600519", "name": "茅台", "price": 100.0, "pct_change": 1.0},
            {"symbol": "sh600363", "name": "联创", "price": 20.0, "pct_change": -1.0},
        ]

        with (
            patch(
                "app.data.portfolio_snapshot.fetch_quote",
                new_callable=AsyncMock,
                side_effect=quote_side_effect,
            ),
            patch(
                "app.data.portfolio_snapshot.fetch_ohlcv",
                new_callable=AsyncMock,
                side_effect=Exception("skip ohlcv"),
            ),
        ):
            snap = await build_portfolio_snapshot(rec)

        self.assertEqual(snap.member_count, 2)
        self.assertAlmostEqual(snap.equal_weight_pct_1d or 0, 0.0, places=5)


class PortfolioTrackStoreTests(unittest.TestCase):
    def test_append_track(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            store = portfolio_store.__class__(Path(tmp))
            store.ensure()
            rec = store.get("default")
            assert rec is not None
            from app.models.portfolio import PortfolioSnapshot, PortfolioMemberSnapshot

            snap = PortfolioSnapshot(
                portfolio_id="default",
                name=rec.name,
                as_of="2026-08-25T00:00:00Z",
                member_count=2,
                equal_weight_pct_1d=0.5,
                members=[
                    PortfolioMemberSnapshot(symbol="sh600519", pct_change=1.0),
                    PortfolioMemberSnapshot(symbol="sh600363", pct_change=0.0),
                ],
                best_today=PortfolioMemberSnapshot(symbol="sh600519", pct_change=1.0),
                worst_today=PortfolioMemberSnapshot(symbol="sh600363", pct_change=0.0),
            )
            row = store.append_track("default", snap, TrackRecordCreate(note="test"))
            rows = store.list_tracks("default")
            self.assertEqual(len(rows), 1)
            self.assertEqual(row.note, "test")


if __name__ == "__main__":
    unittest.main()
