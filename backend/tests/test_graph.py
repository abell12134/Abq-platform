from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.graph.builder import (
    apply_fundamentals_to_graph,
    apply_sentiment_to_graph,
    bootstrap_csi300_skeleton,
)
from app.graph.models import GraphNode
from app.graph.rate_limit import FetchThrottle
from app.graph.store import graph_store, stock_node_id
from app.graph.sync import sync_one_stock, sync_sample_stocks


class GraphStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        from app.config import settings

        self._orig_db = settings.graph_db_path
        self._orig_data = settings.data_dir
        settings.data_dir = Path(self.tmp.name)
        settings.graph_db_path = Path(self.tmp.name) / "graph" / "graph.db"
        graph_store.db_path = settings.graph_db_path
        graph_store.ensure()

    def tearDown(self) -> None:
        from app.config import settings

        settings.graph_db_path = self._orig_db
        settings.data_dir = self._orig_data
        self.tmp.cleanup()

    def test_upsert_and_subgraph(self) -> None:
        a = stock_node_id("sh600519")
        b = GraphNode(id="sector:liquor", type="Sector", label="白酒")
        graph_store.upsert_node(GraphNode(id=a, type="Stock", label="贵州茅台", props={"symbol": "sh600519"}))
        graph_store.upsert_node(b)
        graph_store.link_edge(a, b.id, "IN_SECTOR")

        sub = graph_store.subgraph("sh600519", hops=1)
        self.assertEqual(sub.center, a)
        self.assertEqual(len(sub.nodes), 2)
        self.assertEqual(len(sub.edges), 1)

    def test_apply_sentiment_links_news(self) -> None:
        sym = "sh600519"
        graph_store.upsert_node(
            GraphNode(id=stock_node_id(sym), type="Stock", label="茅台", props={"symbol": sym})
        )
        n = apply_sentiment_to_graph(
            sym,
            {
                "status": "ok",
                "source": "test",
                "headlines": [{"新闻标题": "茅台业绩超预期", "发布时间": "2026-08-27"}],
            },
        )
        self.assertEqual(n, 1)
        sub = graph_store.subgraph(sym, hops=1)
        types = {node.type for node in sub.nodes}
        self.assertIn("News", types)

    def test_link_edge_dedup(self) -> None:
        a = stock_node_id("sh600519")
        b = GraphNode(id="sector:test", type="Sector", label="测试")
        graph_store.upsert_node(
            GraphNode(id=a, type="Stock", label="茅台", props={"symbol": "sh600519"})
        )
        graph_store.upsert_node(b)
        graph_store.link_edge(a, b.id, "IN_SECTOR")
        graph_store.link_edge(a, b.id, "IN_SECTOR")
        self.assertEqual(graph_store.stats().edge_count, 1)


class GraphSyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        from app.config import settings

        self._orig = {
            "data_dir": settings.data_dir,
            "graph_db_path": settings.graph_db_path,
            "graph_enabled": settings.graph_enabled,
            "graph_fetch_min_interval_s": settings.graph_fetch_min_interval_s,
            "graph_sync_cooldown_hours": settings.graph_sync_cooldown_hours,
            "knowledge_archive_enabled": settings.knowledge_archive_enabled,
        }
        settings.data_dir = Path(self.tmp.name)
        settings.graph_db_path = Path(self.tmp.name) / "graph" / "graph.db"
        settings.graph_enabled = True
        settings.graph_fetch_min_interval_s = 0.01
        settings.graph_sync_cooldown_hours = 24.0
        settings.knowledge_archive_enabled = True
        settings.graph_extract_triples_enabled = False
        graph_store.db_path = settings.graph_db_path
        graph_store.ensure()

    async def asyncTearDown(self) -> None:
        from app.config import settings

        for k, v in self._orig.items():
            setattr(settings, k, v)
        self.tmp.cleanup()

    async def test_sync_one_stock_mocked(self) -> None:
        fund = {
            "status": "ok",
            "company_info": {"A股简称": "贵州茅台", "所属行业": "白酒"},
        }
        sent = {
            "status": "ok",
            "source": "test",
            "symbol": "sh600519",
            "headlines": [{"新闻标题": "测试新闻", "发布时间": "2026-08-27"}],
        }
        ann = {
            "status": "ok",
            "source": "test",
            "symbol": "sh600519",
            "announcements": [{"公告标题": "测试公告", "公告日期": "2026-08-27", "编码": "a1"}],
        }
        with (
            patch("app.graph.sync.fetch_fundamentals", new=AsyncMock(return_value=fund)),
            patch("app.graph.sync.fetch_sentiment", new=AsyncMock(return_value=sent)),
            patch("app.graph.sync.fetch_announcements", new=AsyncMock(return_value=ann)),
        ):
            r1 = await sync_one_stock("sh600519", force=True)
            self.assertEqual(r1.status, "ok")
            self.assertEqual(r1.news_linked, 1)
            r2 = await sync_one_stock("sh600519", force=False)
            self.assertTrue(r2.skipped)

    async def test_bootstrap_uses_universe_cache(self) -> None:
        symbols = [f"sh60051{i}" for i in range(3)]
        with patch(
            "app.graph.builder.fetch_universe_symbols",
            new=AsyncMock(return_value=(symbols, {"source": "test", "index_code": "000300"})),
        ):
            out = await bootstrap_csi300_skeleton(max_symbols=3)
        self.assertEqual(out["stocks"], 3)
        stats = graph_store.stats()
        self.assertGreaterEqual(stats.node_count, 4)


class FetchThrottleTests(unittest.IsolatedAsyncioTestCase):
    async def test_throttle_serializes(self) -> None:
        import time

        t = FetchThrottle(min_interval_s=0.05)
        t0 = time.monotonic()
        await t.wait()
        await t.wait()
        self.assertGreaterEqual(time.monotonic() - t0, 0.04)


if __name__ == "__main__":
    unittest.main()
