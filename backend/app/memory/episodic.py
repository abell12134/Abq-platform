from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel

from app.config import settings
from app.llm.embedding_client import embedding_client
from app.llm.router import llm_router
from app.memory.store import memory_store
from app.models.analysis import AnalysisPathIndexEntry
from app.models.pipeline import PipelineReports

log = logging.getLogger(__name__)


class Episode(BaseModel):
    situation: str = ""
    reasoning: str = ""
    outcome: str = ""
    lesson: str = ""
    symbol: str | None = None
    kind: str = "single"
    path_id: str = ""


_EPISODE_JSON_RE = re.compile(r"\{[^{}]*\"situation\"[^{}]*\}", re.S)


def _rule_episode(
    entry: AnalysisPathIndexEntry,
    reports: PipelineReports,
    user_message: str,
) -> Episode:
    judge = reports.judge.content if reports.judge else ""
    one_liner = ""
    if "## 结论" in judge:
        part = judge.split("## 结论", 1)[1].split("##", 1)[0].strip()
        one_liner = part[:300]
    elif judge:
        one_liner = judge[:300]
    symbols = entry.symbols or ([entry.target] if entry.target else [])
    return Episode(
        situation=f"用户问：{user_message[:200]}",
        reasoning=one_liner or "（无 judge 正文）",
        outcome=entry.judge_stance or "observe",
        lesson=entry.judge_one_liner or one_liner[:200],
        symbol=symbols[0] if symbols else None,
        kind=entry.kind,
        path_id=entry.id,
    )


async def _llm_episode(
    entry: AnalysisPathIndexEntry,
    reports: PipelineReports,
    user_message: str,
) -> Episode | None:
    from app.llm.chat import LlmChat

    judge = reports.judge.content if reports.judge else ""
    if not judge.strip():
        return None
    resolved = llm_router.resolve(tier="local", role="extract")
    chat = LlmChat(resolved.provider, model=resolved.model)
    prompt = f"""从以下研判记录抽取一条可复用的 episodic 经验（JSON）。
用户问题：{user_message[:300]}
研判正文（节选）：
{judge[:2000]}

只输出一个 JSON 对象，字段：
situation（情境）, reasoning（推理链）, outcome（结果 stance）, lesson（可复用教训，一句话）
"""
    try:
        turn = await chat.complete(
            [{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=512,
        )
        content = turn.content.strip()
        match = _EPISODE_JSON_RE.search(content)
        if not match:
            return None
        data = json.loads(match.group(0))
        symbols = entry.symbols or ([entry.target] if entry.target else [])
        return Episode(
            situation=str(data.get("situation", ""))[:400],
            reasoning=str(data.get("reasoning", ""))[:600],
            outcome=str(data.get("outcome", entry.judge_stance or "observe"))[:40],
            lesson=str(data.get("lesson", ""))[:300],
            symbol=symbols[0] if symbols else None,
            kind=entry.kind,
            path_id=entry.id,
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("llm episode extract failed: %s", exc)
        return None


def episode_text(ep: Episode) -> str:
    return (
        f"情境：{ep.situation}\n"
        f"推理：{ep.reasoning}\n"
        f"结果：{ep.outcome}\n"
        f"教训：{ep.lesson}"
    )


async def extract_and_store_episode(
    entry: AnalysisPathIndexEntry,
    reports_data: dict[str, Any] | None,
    user_message: str,
) -> Episode | None:
    reports = PipelineReports.model_validate(reports_data) if reports_data else PipelineReports()
    if not reports.judge or not reports.judge.content.strip():
        return None

    episode = await _llm_episode(entry, reports, user_message)
    if episode is None:
        episode = _rule_episode(entry, reports, user_message)

    symbol = (episode.symbol or "general").lower()
    namespace = ("episodes", symbol)
    text = episode_text(episode)
    key = f"{entry.id}_episode"

    if settings.embedding_enabled:
        try:
            emb = await embedding_client.embed_query(text)
            memory_store.put(
                namespace,
                key,
                text=text,
                metadata={
                    "path_id": entry.id,
                    "symbol": episode.symbol,
                    "kind": entry.kind,
                    "outcome": episode.outcome,
                    "lesson": episode.lesson,
                },
                embedding=emb,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("episode index %s failed: %s", entry.id, exc)
    else:
        memory_store.put(
            namespace,
            key,
            text=text,
            metadata={
                "path_id": entry.id,
                "symbol": episode.symbol,
                "kind": entry.kind,
                "outcome": episode.outcome,
            },
            embedding=None,
        )
    return episode


async def search_episodes(
    query: str,
    *,
    symbol: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    sym = (symbol or "general").lower()
    namespace = ("episodes", sym)
    hits: list[dict[str, Any]] = []

    if settings.embedding_enabled and query.strip():
        try:
            q_emb = await embedding_client.embed_query(query)
            vec_hits = memory_store.search(namespace, q_emb, limit=limit)
            for h in vec_hits:
                meta = h.get("metadata") or {}
                hits.append(
                    {
                        "text": h.get("text"),
                        "score": h.get("score"),
                        "path_id": meta.get("path_id"),
                        "outcome": meta.get("outcome"),
                        "lesson": meta.get("lesson"),
                        "source": "episode",
                    }
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("search_episodes failed: %s", exc)

    if not hits:
        rows = memory_store.list_namespace(namespace, limit=limit)
        for row in rows:
            meta = row.get("metadata") or {}
            if query and query not in (row.get("text") or ""):
                continue
            hits.append(
                {
                    "text": row.get("text"),
                    "score": 1.0,
                    "path_id": meta.get("path_id"),
                    "outcome": meta.get("outcome"),
                    "lesson": meta.get("lesson"),
                    "source": "episode",
                }
            )

    return {
        "status": "ok" if hits else "empty",
        "hits": hits[:limit],
        "summary": f"检索到 {len(hits)} 条研判经验",
    }
