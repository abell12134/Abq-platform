from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.graph.extractor import extract_supply_chain_triples
from app.graph.maintenance import rotate_jsonl_archives
from app.graph.market_builder import (
    apply_macro_indicators_to_graph,
    apply_market_snapshot_to_graph,
    apply_northbound_to_graph,
)
from app.graph.models import GraphNode
from app.graph.store import graph_store, index_node_id, sector_node_id, stock_node_id
from app.graph.summarizer import rollup_period
from app.knowledge.policy_sync import fetch_policy_list, sync_policy_sources


class MarketLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        from app.config import settings

        self._orig = {
            "data_dir": settings.data_dir,
            "graph_db_path": settings.graph_db_path,
        }
        settings.data_dir = Path(self.tmp.name)
        settings.graph_db_path = Path(self.tmp.name) / "graph" / "graph.db"
        graph_store.db_path = settings.graph_db_path
        graph_store.ensure()
        graph_store.upsert_node(
            GraphNode(id=index_node_id("csi300"), type="Index", label="沪深300")
        )

    def tearDown(self) -> None:
        from app.config import settings

        for k, v in self._orig.items():
            setattr(settings, k, v)
        self.tmp.cleanup()

    def test_northbound_and_snapshot_nodes(self) -> None:
        mid = apply_northbound_to_graph(
            {
                "status": "ok",
                "metrics": {"trade_date": "2026-08-27", "net_buy": 12.3},
            }
        )
        self.assertIsNotNone(mid)
        snap = apply_market_snapshot_to_graph(
            breadth={"advance": 2000, "decline": 1500},
            northbound={"metrics": {"trade_date": "2026-08-27", "net_buy": 12.3}},
        )
        node = graph_store.get_node(snap)
        self.assertIsNotNone(node)
        self.assertEqual(node.type, "MarketSnapshot")

    def test_macro_indicators(self) -> None:
        n = apply_macro_indicators_to_graph(
            {
                "status": "ok",
                "indicators": [{"name": "CPI", "period": "2026-07", "value": 0.2}],
            }
        )
        self.assertEqual(n, 1)
        stats = graph_store.stats()
        self.assertGreaterEqual(stats.nodes_by_type.get("Macro", 0), 1)


class SectorRollupTests(unittest.IsolatedAsyncioTestCase):
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

        sym = "sh600519"
        sec = "白酒"
        graph_store.upsert_node(
            GraphNode(id=stock_node_id(sym), type="Stock", label="茅台", props={"symbol": sym})
        )
        graph_store.upsert_node(GraphNode(id=sector_node_id(sec), type="Sector", label=sec))
        graph_store.link_edge(stock_node_id(sym), sector_node_id(sec), "IN_SECTOR")

        from app.knowledge.archiver import archive_announcements

        await archive_announcements(
            {
                "status": "ok",
                "symbol": sym,
                "announcements": [{"公告标题": "板块测试公告", "公告日期": "2026-08-27", "编码": "s1"}],
            },
            symbol=sym,
        )

    async def asyncTearDown(self) -> None:
        from app.config import settings

        for k, v in self._orig.items():
            setattr(settings, k, v)
        self.tmp.cleanup()

    async def test_sector_rollup(self) -> None:
        result = await rollup_period("2026-08", scope="sector", key="白酒", use_llm=False)
        self.assertEqual(result.scope, "sector")
        self.assertIn("板块测试公告", result.summary)
        digest = graph_store.get_node(result.digest_id)
        self.assertIsNotNone(digest)


class PolicySyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        from app.config import settings

        self._orig = {
            "data_dir": settings.data_dir,
            "policy_sources_path": settings.policy_sources_path,
            "policy_sync_max_per_run": settings.policy_sync_max_per_run,
        }
        settings.data_dir = Path(self.tmp.name)
        settings.policy_sources_path = Path(self.tmp.name) / "policy_sources.yaml"
        settings.policy_sources_path.write_text(
            "allowed_hosts:\n  - www.csrc.gov.cn\nsources:\n  - id: t\n"
            "    list_url: https://www.csrc.gov.cn/csrc/c101953/common_list.shtml\n"
            "    issuer: 证监会\n    max_per_run: 2\n",
            encoding="utf-8",
        )
        settings.policy_sync_max_per_run = 2

    async def asyncTearDown(self) -> None:
        from app.config import settings

        for k, v in self._orig.items():
            setattr(settings, k, v)
        self.tmp.cleanup()

    async def test_fetch_policy_list_parses_links(self) -> None:
        html = (
            '<a href="/csrc/c101953/content.shtml">测试政策文件</a>'
            '<a href="/csrc/c101953/t20260827_123.html">另一文件</a>'
        )
        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.knowledge.policy_sync.httpx.AsyncClient", return_value=mock_client):
            items = await fetch_policy_list(
                {"list_url": "https://www.csrc.gov.cn/csrc/c101953/common_list.shtml"}
            )
        self.assertGreaterEqual(len(items), 1)
        self.assertTrue(all(i.url.startswith("https://www.csrc.gov.cn") for i in items))

    async def test_sync_skips_seen_urls(self) -> None:
        with (
            patch(
                "app.knowledge.policy_sync.fetch_policy_list",
                new=AsyncMock(
                    return_value=[
                        type("I", (), {"title": "A", "url": "https://www.csrc.gov.cn/a.html"})(),
                    ]
                ),
            ),
            patch(
                "app.knowledge.policy_sync.ingest_policy_from_url",
                new=AsyncMock(return_value={"status": "ok", "doc_id": "d1"}),
            ),
        ):
            out = await sync_policy_sources()
        self.assertEqual(out["ingested"], 1)
        state_path = Path(self.tmp.name) / "knowledge" / "policy" / "sync_state.json"
        self.assertTrue(state_path.exists())


class MaintenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        from app.config import settings

        self._orig = {
            "data_dir": settings.data_dir,
            "graph_jsonl_rotate_enabled": settings.graph_jsonl_rotate_enabled,
        }
        settings.data_dir = Path(self.tmp.name)
        settings.graph_jsonl_rotate_enabled = True

    def tearDown(self) -> None:
        from app.config import settings

        for k, v in self._orig.items():
            setattr(settings, k, v)
        self.tmp.cleanup()

    def test_rotate_jsonl_archives(self) -> None:
        from app.config import settings

        old = settings.data_dir / "knowledge" / "sentiment" / "sh600519.jsonl"
        old.parent.mkdir(parents=True)
        old.write_text(json.dumps({"x": 1}) + "\n", encoding="utf-8")
        import os
        import time

        old_ts = time.time() - 90 * 86400
        os.utime(old, (old_ts, old_ts))

        out = rotate_jsonl_archives(before_period="2026-07")
        self.assertGreaterEqual(out["archived"], 1)
        gz_files = list((settings.data_dir / "knowledge" / "archive").rglob("*.gz"))
        self.assertTrue(gz_files)
        with gzip.open(gz_files[0], "rt", encoding="utf-8") as f:
            self.assertIn('"x"', f.read())


class ExtractorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        from app.config import settings

        self._orig = {
            "data_dir": settings.data_dir,
            "graph_db_path": settings.graph_db_path,
            "graph_extract_triples_enabled": settings.graph_extract_triples_enabled,
        }
        settings.data_dir = Path(self.tmp.name)
        settings.graph_db_path = Path(self.tmp.name) / "graph" / "graph.db"
        settings.graph_extract_triples_enabled = True
        graph_store.db_path = settings.graph_db_path
        graph_store.ensure()

    async def asyncTearDown(self) -> None:
        from app.config import settings

        for k, v in self._orig.items():
            setattr(settings, k, v)
        self.tmp.cleanup()

    async def test_extract_high_confidence_edge(self) -> None:
        triples = [
            {
                "relation": "SUPPLIES_TO",
                "target": "某车企",
                "confidence": 0.9,
                "evidence": "供应电池",
            }
        ]
        with patch(
            "app.graph.extractor._llm_extract",
            new=AsyncMock(return_value=triples),
        ):
            out = await extract_supply_chain_triples(
                "sz300750",
                company_name="宁德时代",
                evidence_titles=["宁德时代向车企供应电池"],
            )
        self.assertEqual(out["status"], "ok")
        self.assertGreaterEqual(out["edges"], 1)


if __name__ == "__main__":
    unittest.main()
