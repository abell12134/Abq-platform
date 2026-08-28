from __future__ import annotations

import logging
from typing import Any

import httpx
import numpy as np

from app.config import settings

log = logging.getLogger(__name__)


class EmbeddingClient:
    def __init__(self) -> None:
        self.base_url = settings.embedding_base_url.rstrip("/")
        self.model = settings.embedding_model
        self.api_key = settings.embedding_api_key or settings.primary_llm_api_key
        self.dimensions = settings.embedding_dimensions
        self.batch_size = settings.embedding_batch_size
        self.timeout = settings.embedding_timeout_s

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _truncate_dims(self, vector: list[float]) -> list[float]:
        if self.dimensions <= 0 or len(vector) <= self.dimensions:
            arr = np.array(vector, dtype=np.float32)
        else:
            arr = np.array(vector[: self.dimensions], dtype=np.float32)
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm
        return arr.tolist()

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self.embed_documents([text])
        return vectors[0] if vectors else []

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for i in range(0, len(texts), self.batch_size):
                batch = texts[i : i + self.batch_size]
                payload: dict[str, Any] = {"model": self.model, "input": batch}
                if self.dimensions > 0:
                    payload["dimensions"] = self.dimensions
                resp = await client.post(
                    f"{self.base_url}/embeddings",
                    headers=self._headers(),
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                items = data.get("data") or []
                items.sort(key=lambda x: x.get("index", 0))
                for item in items:
                    emb = item.get("embedding") or []
                    out.append(self._truncate_dims(emb))
        return out

    async def health(self, *, probe: bool = False) -> dict[str, Any]:
        if not settings.embedding_enabled:
            return {"ok": False, "status": "disabled", "model": self.model}
        if not probe:
            return {
                "ok": True,
                "status": "configured",
                "model": self.model,
                "dimensions": self.dimensions,
            }
        try:
            vec = await self.embed_query("health")
            return {
                "ok": bool(vec),
                "status": "ok" if vec else "empty",
                "model": self.model,
                "dimensions": len(vec),
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("embedding health failed: %s", exc)
            return {"ok": False, "status": "error", "model": self.model, "message": str(exc)}


embedding_client = EmbeddingClient()
