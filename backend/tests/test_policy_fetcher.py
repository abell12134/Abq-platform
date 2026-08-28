from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.knowledge.policy_fetcher import (
    html_to_text,
    is_allowed_url,
    load_allowed_hosts,
    reload_policy_hosts,
)


class PolicyFetcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        from app.config import settings

        self._orig_path = settings.policy_sources_path
        settings.policy_sources_path = Path(self.tmp.name) / "policy_sources.yaml"
        reload_policy_hosts()

    def tearDown(self) -> None:
        from app.config import settings

        settings.policy_sources_path = self._orig_path
        reload_policy_hosts()
        self.tmp.cleanup()

    def test_load_hosts_from_yaml(self) -> None:
        from app.config import settings

        settings.policy_sources_path.write_text(
            "allowed_hosts:\n  - www.csrc.gov.cn\n  - www.gov.cn\n",
            encoding="utf-8",
        )
        reload_policy_hosts()
        hosts = load_allowed_hosts()
        self.assertIn("www.csrc.gov.cn", hosts)
        self.assertIn("www.gov.cn", hosts)

    def test_is_allowed_url(self) -> None:
        from app.config import settings

        settings.policy_sources_path.write_text(
            "allowed_hosts:\n  - www.csrc.gov.cn\n",
            encoding="utf-8",
        )
        reload_policy_hosts()
        self.assertTrue(is_allowed_url("https://www.csrc.gov.cn/foo"))
        self.assertFalse(is_allowed_url("https://evil.example.com/foo"))
        self.assertFalse(is_allowed_url("file:///etc/passwd"))

    def test_html_to_text_strips_tags(self) -> None:
        html = "<html><body><h1>标题</h1><p>正文内容</p><script>x</script></body></html>"
        text = html_to_text(html)
        self.assertIn("标题", text)
        self.assertIn("正文内容", text)
        self.assertNotIn("script", text.lower())


class PolicyFetcherAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        from app.config import settings

        self._orig = {
            "data_dir": settings.data_dir,
            "graph_db_path": settings.graph_db_path,
            "graph_enabled": settings.graph_enabled,
            "policy_sources_path": settings.policy_sources_path,
            "policy_fetch_min_interval_s": settings.policy_fetch_min_interval_s,
            "embedding_enabled": settings.embedding_enabled,
        }
        settings.data_dir = Path(self.tmp.name)
        settings.graph_db_path = Path(self.tmp.name) / "graph" / "graph.db"
        settings.graph_enabled = True
        settings.policy_sources_path = Path(self.tmp.name) / "policy_sources.yaml"
        settings.policy_sources_path.write_text(
            "allowed_hosts:\n  - example.gov.cn\n",
            encoding="utf-8",
        )
        settings.policy_fetch_min_interval_s = 0.01
        settings.embedding_enabled = False
        reload_policy_hosts()
        from app.graph.store import graph_store

        graph_store.db_path = settings.graph_db_path
        graph_store.ensure()
        self.graph_store = graph_store

    async def asyncTearDown(self) -> None:
        from app.config import settings

        for k, v in self._orig.items():
            setattr(settings, k, v)
        reload_policy_hosts()
        self.tmp.cleanup()

    async def test_fetch_and_ingest_mocked(self) -> None:
        from app.knowledge.policy_fetcher import fetch_policy_content, ingest_policy_from_url

        graph_store = self.graph_store

        html_body = (
            "<html><head><title>减持规定</title></head>"
            "<body><p>" + ("监管条文内容。" * 30) + "</p></body></html>"
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.text = html_body
        mock_resp.content = html_body.encode()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.knowledge.policy_fetcher.httpx.AsyncClient", return_value=mock_client):
            page = await fetch_policy_content("https://example.gov.cn/rule.html")
            self.assertIn("减持", page.title)
            result = await ingest_policy_from_url(
                "https://example.gov.cn/rule.html",
                symbol="sh600519",
                issuer="证监会",
            )
        self.assertEqual(result["status"], "ok")
        sub = graph_store.subgraph("sh600519", hops=2)
        types = {n.type for n in sub.nodes}
        self.assertIn("Policy", types)


if __name__ == "__main__":
    unittest.main()
