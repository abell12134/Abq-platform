"""analyze_stream error-branch and cancel tests."""

from __future__ import annotations

import asyncio
import unittest

from app.models.analysis import AnalyzeRequest
from app.orchestration.analysis_registry import analysis_registry
from app.orchestration.analyze_stream import analyze_stream
from app.persistence.paths import path_store


async def _collect(req: AnalyzeRequest) -> list[dict]:
    events: list[dict] = []
    async for ev in analyze_stream(req):
        events.append(ev.model_dump(mode="json", exclude_none=True))
        if ev.type in ("error", "done"):
            break
    return events


class AnalyzeStreamErrorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._created: list[str] = []

    async def asyncTearDown(self) -> None:
        for pid in self._created:
            try:
                await path_store.update_status(pid, "error")
            except Exception:
                pass

    async def _run(self, req: AnalyzeRequest) -> list[dict]:
        events = await _collect(req)
        for ev in events:
            pid = ev.get("path_id")
            if pid:
                self._created.append(pid)
        return events

    async def test_missing_symbol_single_yields_error(self) -> None:
        req = AnalyzeRequest(message="随便看看，没有代码", kind="single", realm="a-share")
        events = await self._run(req)
        self.assertTrue(any(e["type"] == "error" for e in events), events)
        err = next(e for e in events if e["type"] == "error")
        self.assertIn("股票代码", err["message"])

    async def test_empty_portfolio_yields_error(self) -> None:
        from unittest.mock import patch

        req = AnalyzeRequest(
            message="诊断一下",
            kind="portfolio",
            realm="a-share",
            target="test_empty_pf",
        )
        with patch(
            "app.orchestration.analyze_stream.portfolio_store.symbols_for",
            return_value=[],
        ):
            events = await self._run(req)
        self.assertTrue(any(e["type"] == "error" for e in events), events)
        err = next(e for e in events if e["type"] == "error")
        self.assertIn("组合成员", err["message"])


class AnalysisRegistryCancelTests(unittest.TestCase):
    def test_cancel_inactive_returns_false(self) -> None:
        self.assertFalse(analysis_registry.cancel("not-running-id"))

    def test_cancel_active_sets_event(self) -> None:
        pid = "test-cancel-pid"
        ev = analysis_registry.register(pid)
        try:
            self.assertTrue(analysis_registry.is_active(pid))
            self.assertTrue(analysis_registry.cancel(pid))
            self.assertTrue(ev.is_set())
        finally:
            analysis_registry.unregister(pid)

    def test_cancel_all_sets_all_events(self) -> None:
        pids = ["test-cancel-all-1", "test-cancel-all-2"]
        events = {p: analysis_registry.register(p) for p in pids}
        try:
            cancelled = analysis_registry.cancel_all()
            self.assertEqual(set(cancelled), set(pids))
            for p in pids:
                self.assertTrue(events[p].is_set())
        finally:
            for p in pids:
                analysis_registry.unregister(p)


if __name__ == "__main__":
    unittest.main()
