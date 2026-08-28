from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.graph.builder import apply_announcements_to_graph
from app.graph.models import GraphNode
from app.graph.store import graph_store, stock_node_id
from app.graph.summarizer import rollup_period
from app.knowledge.archiver import archive_announcements, list_events


class AnnouncementTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        from app.config import settings

        self._orig = {
            "data_dir": settings.data_dir,
            "graph_db_path": settings.graph_db_path,
            "graph_enabled": settings.graph_enabled,
            "knowledge_archive_enabled": settings.knowledge_archive_enabled,
            "graph_rollup_llm_enabled": settings.graph_rollup_llm_enabled,
            "embedding_enabled": settings.embedding_enabled,
        }
        settings.data_dir = Path(self.tmp.name)
        settings.graph_db_path = Path(self.tmp.name) / "graph" / "graph.db"
        settings.graph_enabled = True
        settings.knowledge_archive_enabled = True
        settings.graph_rollup_llm_enabled = False
        settings.embedding_enabled = False
        graph_store.db_path = settings.graph_db_path
        graph_store.ensure()

    async def asyncTearDown(self) -> None:
        from app.config import settings

        for k, v in self._orig.items():
            setattr(settings, k, v)
        self.tmp.cleanup()

    async def test_archive_and_graph_event(self) -> None:
        sym = "sh600519"
        graph_store.upsert_node(
            GraphNode(id=stock_node_id(sym), type="Stock", label="茅台", props={"symbol": sym})
        )
        payload = {
            "status": "ok",
            "source": "test",
            "symbol": sym,
            "announcements": [
                {
                    "公告标题": "2026半年度报告",
                    "公告类型": "财务报告",
                    "公告日期": "2026-08-27",
                    "编码": "ann001",
                    "网址": "https://example.com/a.html",
                }
            ],
        }
        ev = await archive_announcements(payload, symbol=sym)
        self.assertIsNotNone(ev)
        n = apply_announcements_to_graph(sym, payload)
        self.assertEqual(n, 1)
        sub = graph_store.subgraph(sym, hops=1)
        self.assertTrue(any(node.type == "Event" for node in sub.nodes))

    async def test_rollup_skips_unchanged(self) -> None:
        sym = "sh600519"
        period = "2026-08"
        payload = {
            "status": "ok",
            "source": "test",
            "symbol": sym,
            "announcements": [{"公告标题": "半年报", "公告日期": "2026-08-27", "编码": "x1"}],
        }
        await archive_announcements(payload, symbol=sym)
        first = await rollup_period(period, scope="symbol", key=sym, use_llm=False)
        second = await rollup_period(period, scope="symbol", key=sym, use_llm=False)
        self.assertFalse(first.skipped)
        self.assertTrue(second.skipped)


if __name__ == "__main__":
    unittest.main()
