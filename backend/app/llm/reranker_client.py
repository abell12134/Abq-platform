from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings
from app.llm.embedding_client import embedding_client

log = logging.getLogger(__name__)


class RerankerClient:
    def __init__(self) -> None:
        self.base_url = settings.embedding_base_url.rstrip("/")
        self.model = settings.reranker_model
        self.api_key = settings.embedding_api_key or settings.primary_llm_api_key
        self.timeout = settings.reranker_timeout_s

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        top_n: int = 5,
    ) -> list[tuple[int, float]]:
        """Return (original_index, score) sorted by relevance desc."""
        if not documents:
            return []
        if not settings.reranker_enabled:
            return [(i, 1.0 - i * 0.01) for i in range(min(top_n, len(documents)))]

        payload = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "top_n": min(top_n, len(documents)),
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for path in ("/rerank", "/v1/rerank"):
                try:
                    resp = await client.post(
                        f"{self.base_url}{path}",
                        headers=self._headers(),
                        json=payload,
                    )
                    if resp.status_code == 404:
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    results = data.get("results") or data.get("data") or []
                    ranked: list[tuple[int, float]] = []
                    for row in results:
                        idx = int(row.get("index", row.get("document", {}).get("index", 0)))
                        score = float(row.get("relevance_score", row.get("score", 0.0)))
                        ranked.append((idx, score))
                    if ranked:
                        return ranked[:top_n]
                except Exception as exc:  # noqa: BLE001
                    log.debug("rerank %s failed: %s", path, exc)

        try:
            import numpy as np

            q_vec = await embedding_client.embed_query(query)
            d_vecs = await embedding_client.embed_documents(documents)
            if not q_vec or not d_vecs:
                return [(i, 1.0 - i * 0.01) for i in range(min(top_n, len(documents)))]
            q = np.array(q_vec, dtype=np.float32)
            scores: list[tuple[int, float]] = []
            for i, d in enumerate(d_vecs):
                dv = np.array(d, dtype=np.float32)
                denom = np.linalg.norm(q) * np.linalg.norm(dv)
                score = float(np.dot(q, dv) / denom) if denom > 0 else 0.0
                scores.append((i, score))
            scores.sort(key=lambda x: x[1], reverse=True)
            return scores[:top_n]
        except Exception as exc:  # noqa: BLE001
            log.warning("rerank fallback failed: %s", exc)
            return [(i, 1.0 - i * 0.01) for i in range(min(top_n, len(documents)))]

    async def health(self, *, probe: bool = False) -> dict[str, Any]:
        if not settings.reranker_enabled:
            return {"ok": False, "status": "disabled", "model": self.model}
        if not probe:
            return {"ok": True, "status": "configured", "model": self.model}
        try:
            ranked = await self.rerank("test", ["doc a", "doc b"], top_n=2)
            return {
                "ok": bool(ranked),
                "status": "ok" if ranked else "empty",
                "model": self.model,
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "status": "error", "model": self.model, "message": str(exc)}


reranker_client = RerankerClient()
