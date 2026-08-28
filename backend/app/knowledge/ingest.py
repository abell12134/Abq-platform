from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiofiles

from app.config import settings
from app.llm.embedding_client import embedding_client
from app.memory.store import memory_store

log = logging.getLogger(__name__)

_CHUNK_SIZE = 512
_CHUNK_OVERLAP = 64


def _policy_root() -> Path:
    return settings.data_dir / "knowledge" / "policy"


def _manifest_path() -> Path:
    return _policy_root() / "manifest.json"


def _chunks_path() -> Path:
    return _policy_root() / "chunks.jsonl"


def split_text(text: str, *, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks


def extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf 未安装，请 pip install pypdf") from exc
    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts).strip()


def read_document_bytes(filename: str, data: bytes) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        tmp = _policy_root() / "uploads" / f"_tmp_{uuid4().hex[:8]}.pdf"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(data)
        try:
            return extract_pdf_text(tmp)
        finally:
            tmp.unlink(missing_ok=True)
    if lower.endswith((".md", ".markdown", ".txt")):
        return data.decode("utf-8", errors="replace").strip()
    raise ValueError("仅支持 .pdf / .md / .txt 文件")


async def _load_manifest() -> dict[str, Any]:
    path = _manifest_path()
    if not path.exists():
        return {"documents": []}
    async with aiofiles.open(path, encoding="utf-8") as f:
        data = json.loads(await f.read() or "{}")
    if not isinstance(data, dict):
        return {"documents": []}
    data.setdefault("documents", [])
    return data


async def _save_manifest(manifest: dict[str, Any]) -> None:
    path = _manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
        await f.write(json.dumps(manifest, ensure_ascii=False, indent=2))
    tmp.replace(path)


async def list_policy_documents() -> list[dict[str, Any]]:
    manifest = await _load_manifest()
    return list(manifest.get("documents") or [])


async def ingest_text_document(
    *,
    title: str,
    content: str,
    symbol: str | None = None,
    theme: str | None = None,
    source: str = "upload",
    filename: str | None = None,
    url: str | None = None,
    issuer: str | None = None,
) -> dict[str, Any]:
    if not content.strip():
        return {"status": "error", "message": "文档内容为空"}

    doc_id = f"doc_{uuid4().hex[:10]}"
    chunks = split_text(content)
    if not chunks:
        return {"status": "error", "message": "未能切分出有效文本块"}

    now = datetime.now(UTC).isoformat()
    indexed = 0
    chunk_rows: list[dict[str, Any]] = []

    for i, chunk in enumerate(chunks):
        chunk_id = f"{doc_id}_c{i:04d}"
        chunk_rows.append(
            {
                "id": chunk_id,
                "doc_id": doc_id,
                "index": i,
                "title": title,
                "symbol": symbol,
                "theme": theme,
                "ts": now,
                "text_preview": chunk[:120],
            }
        )
        if settings.embedding_enabled:
            try:
                emb = await embedding_client.embed_query(chunk)
                memory_store.put(
                    ("knowledge", "policy"),
                    chunk_id,
                    text=chunk,
                    metadata={
                        "doc_id": doc_id,
                        "title": title,
                        "symbol": symbol,
                        "theme": theme,
                        "chunk_index": i,
                        "source": source,
                        "type": "policy",
                    },
                    embedding=emb,
                )
                indexed += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("policy chunk embed %s failed: %s", chunk_id, exc)

    chunks_path = _chunks_path()
    chunks_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(chunks_path, "a", encoding="utf-8") as f:
        for row in chunk_rows:
            await f.write(json.dumps(row, ensure_ascii=False) + "\n")

    manifest = await _load_manifest()
    manifest["documents"].append(
        {
            "id": doc_id,
            "title": title,
            "filename": filename,
            "url": url,
            "issuer": issuer,
            "symbol": symbol,
            "theme": theme,
            "source": source,
            "uploaded_at": now,
            "chunk_count": len(chunks),
            "indexed_chunks": indexed,
        }
    )
    await _save_manifest(manifest)

    if settings.graph_enabled:
        try:
            from app.graph.policy_link import link_policy_document

            link_policy_document(
                doc_id=doc_id,
                title=title,
                url=url,
                symbol=symbol,
                theme=theme,
                issuer=issuer,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("policy graph link failed %s: %s", doc_id, exc)

    return {
        "status": "ok",
        "doc_id": doc_id,
        "title": title,
        "chunk_count": len(chunks),
        "indexed_chunks": indexed,
    }


async def ingest_file_upload(
    *,
    filename: str,
    data: bytes,
    title: str | None = None,
    symbol: str | None = None,
    theme: str | None = None,
) -> dict[str, Any]:
    text = read_document_bytes(filename, data)
    doc_title = (title or "").strip() or Path(filename).stem
    uploads_dir = _policy_root() / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    doc_id_preview = uuid4().hex[:10]
    safe_name = re.sub(r"[^\w.\-]+", "_", filename)[:80]
    dest = uploads_dir / f"pending_{doc_id_preview}_{safe_name}"
    dest.write_bytes(data)
    try:
        result = await ingest_text_document(
            title=doc_title,
            content=text,
            symbol=symbol,
            theme=theme,
            source="api",
            filename=filename,
        )
        final = uploads_dir / f"{result['doc_id']}_{safe_name}"
        dest.replace(final)
        return result
    except Exception:
        dest.unlink(missing_ok=True)
        raise
