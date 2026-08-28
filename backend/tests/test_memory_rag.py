from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.knowledge.archiver import append_event, archive_breadth, archive_sentiment, list_events
from app.knowledge.delta import compute_knowledge_delta
from app.knowledge.models import KnowledgeEvent
from app.memory.extractors import parse_judge_one_liner, parse_judge_stance
from app.memory.store import MemoryStore
from app.models.analysis import AnalysisPathIndexEntry
from app.persistence.paths import PathStore


class KnowledgeArchiverTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        from app.config import settings

        self._orig = settings.data_dir
        self._orig_archive = settings.knowledge_archive_enabled
        settings.data_dir = Path(self.tmp.name)
        settings.knowledge_archive_enabled = True

    async def asyncTearDown(self) -> None:
        from app.config import settings

        settings.data_dir = self._orig
        settings.knowledge_archive_enabled = self._orig_archive
        self.tmp.cleanup()

    async def test_archive_sentiment_dedup(self) -> None:
        payload = {
            "status": "ok",
            "symbol": "sh600519",
            "source": "akshare",
            "headlines": [{"新闻标题": "测试标题", "发布时间": "2026-08-26"}],
        }
        e1 = await archive_sentiment(payload, symbol="sh600519", path_id="p1")
        e2 = await archive_sentiment(payload, symbol="sh600519", path_id="p1")
        self.assertIsNotNone(e1)
        self.assertIsNone(e2)
        events = await list_events("sentiment", symbol="sh600519")
        self.assertEqual(len(events), 1)

    async def test_archive_breadth(self) -> None:
        payload = {
            "status": "ok",
            "source": "akshare",
            "advance": 3200,
            "decline": 1800,
            "advance_ratio": 0.62,
            "limit_up_count": 45,
        }
        event = await archive_breadth(payload, path_id="m1")
        self.assertIsNotNone(event)
        events = await list_events("breadth")
        self.assertEqual(len(events), 1)
        self.assertIn("3200", events[0].summary)


class KnowledgeDeltaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        from app.config import settings

        self._orig = settings.data_dir
        settings.data_dir = Path(self.tmp.name)

    async def asyncTearDown(self) -> None:
        from app.config import settings

        settings.data_dir = self._orig
        self.tmp.cleanup()

    async def test_sentiment_delta(self) -> None:
        from app.knowledge.archiver import _event_path

        path = _event_path("sentiment", symbol="sh600519")
        path.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).isoformat()
        e1 = KnowledgeEvent(
            id="e1",
            ts=now,
            type="sentiment",
            symbol="sh600519",
            headlines=[{"新闻标题": "旧标题"}],
            summary="旧",
        )
        e2 = KnowledgeEvent(
            id="e2",
            ts=now,
            type="sentiment",
            symbol="sh600519",
            headlines=[{"新闻标题": "新标题"}],
            summary="新",
        )
        with path.open("w", encoding="utf-8") as f:
            f.write(e1.model_dump_json() + "\n")
            f.write(e2.model_dump_json() + "\n")

        delta = await compute_knowledge_delta("sentiment", symbol="sh600519", since_days=7)
        self.assertEqual(delta.status, "ok")
        self.assertIn("新标题", delta.new_items)


class ExtractorTests(unittest.TestCase):
    def test_parse_judge_stance(self) -> None:
        text = "## 结论\n观望\n\n{\"stance\":\"cautious\",\"confidence\":0.5,\"focus_covered\":true}"
        self.assertEqual(parse_judge_stance(text), "cautious")
        self.assertTrue(parse_judge_one_liner(text))

    def test_memory_store_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "mem.db")
            store.ensure()
            v1 = [1.0, 0.0, 0.0]
            v2 = [0.9, 0.1, 0.0]
            store.put(("test",), "a", text="alpha", embedding=v1)
            store.put(("test",), "b", text="beta", embedding=v2)
            hits = store.search(("test",), v1, limit=2)
            self.assertEqual(hits[0]["key"], "a")
            self.assertGreater(hits[0]["score"], hits[1]["score"])


class IngestTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        from app.config import settings

        self._orig = settings.data_dir
        settings.data_dir = Path(self.tmp.name)
        settings.embedding_enabled = False

    async def asyncTearDown(self) -> None:
        from app.config import settings

        settings.data_dir = self._orig
        settings.embedding_enabled = True
        self.tmp.cleanup()

    async def test_ingest_text_document(self) -> None:
        from app.knowledge.ingest import ingest_text_document, list_policy_documents, split_text

        chunks = split_text("a" * 600)
        self.assertGreater(len(chunks), 1)
        result = await ingest_text_document(
            title="测试政策",
            content="第一条 监管要求\n第二条 信息披露",
            symbol="sh600519",
        )
        self.assertEqual(result["status"], "ok")
        docs = await list_policy_documents()
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["chunk_count"], result["chunk_count"])


class PathSearchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        from app.config import settings

        self._orig = settings.data_dir
        settings.data_dir = Path(self.tmp.name)
        self.store = PathStore(settings.data_dir)
        await self.store.ensure()

    async def asyncTearDown(self) -> None:
        from app.config import settings

        settings.data_dir = self._orig
        self.tmp.cleanup()

    async def test_search_entries(self) -> None:
        entry = await self.store.create_entry(
            title="t",
            kind="single",
            realm="a-share",
            status="done",
            target="sh600519",
        )
        await self.store.update_memory_meta(
            entry.id,
            symbols=["sh600519"],
            judge_stance="observe",
            judge_one_liner="缩量回调",
        )
        hits = await self.store.search_entries(symbol="sh600519", limit=5)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].judge_one_liner, "缩量回调")


class MemoryPreviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_has_memory_intent(self) -> None:
        from app.orchestration.compose_route import has_memory_intent

        self.assertTrue(has_memory_intent("上次对茅台的判断是什么"))
        self.assertFalse(has_memory_intent("看600519量价"))

    async def test_build_memory_preview_empty(self) -> None:
        from app.memory.preview import build_memory_preview

        result = await build_memory_preview(message="随便看看", kind="single")
        self.assertIn(result["status"], ("ok", "empty"))


if __name__ == "__main__":
    unittest.main()
