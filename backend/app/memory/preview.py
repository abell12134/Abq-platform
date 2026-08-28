from __future__ import annotations

import re
from typing import Any

from app.agents.specs import extract_symbol
from app.knowledge.delta import compute_knowledge_delta
from app.memory.episodic import search_episodes
from app.memory.search import search_knowledge, search_prior_analysis
from app.orchestration.compose_route import has_memory_intent

_POLICY_RE = re.compile(r"政策|监管|规定|办法|证监会|交易所", re.I)


async def build_memory_preview(
    *,
    message: str,
    kind: str = "single",
    symbol: str | None = None,
    focus: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """Prefetch cross-session memory for prompt injection and UI hints."""
    text = f"{message or ''} {focus or ''}".strip()
    sym = (symbol or extract_symbol(text) or "").lower() or None
    query = message.strip()[:200] if message.strip() else text[:200]
    hints: list[str] = []
    sections: dict[str, list[dict[str, Any]]] = {
        "prior_analysis": [],
        "episodes": [],
        "knowledge_delta": [],
        "policy": [],
    }

    if sym and kind in ("single", "portfolio"):
        prior = await search_prior_analysis(
            symbol=sym,
            kind=kind if kind == "single" else None,
            query=query or None,
            since_days=60,
            limit=3,
        )
        for hit in prior.get("hits") or []:
            line = hit.get("judge_one_liner") or ""
            if not line:
                continue
            stance = hit.get("judge_stance")
            prefix = f"[{stance}] " if stance else ""
            hints.append(f"[历史研判·{str(hit.get('path_id', ''))[:8]}] {prefix}{line}")
            sections["prior_analysis"].append(hit)

        if query:
            ep = await search_episodes(query, symbol=sym, limit=2)
            for hit in ep.get("hits") or []:
                lesson = (hit.get("lesson") or hit.get("text") or "")[:160]
                if lesson:
                    hints.append(f"[研判经验] {lesson}")
                    sections["episodes"].append(hit)

        delta = await compute_knowledge_delta("sentiment", symbol=sym, since_days=7)
        if delta.status == "ok" and delta.summary:
            hints.append(f"[舆情增量] {delta.summary}")
            sections["knowledge_delta"].append(delta.model_dump())

    if kind == "market" or not sym:
        breadth = await compute_knowledge_delta("breadth", since_days=7)
        if breadth.status == "ok" and breadth.summary:
            hints.append(f"[大盘宽度] {breadth.summary}")
            sections["knowledge_delta"].append(breadth.model_dump())

    if _POLICY_RE.search(text) and query:
        policy = await search_knowledge(query, knowledge_type="policy", limit=3)
        for hit in policy.get("hits") or []:
            snippet = (hit.get("text") or "")[:160]
            if snippet:
                hints.append(f"[政策条款] {snippet}")
                sections["policy"].append(hit)

    trimmed = hints[:limit]
    return {
        "status": "ok" if trimmed else "empty",
        "memory_intent": has_memory_intent(text),
        "symbol": sym,
        "hints": trimmed,
        "sections": sections,
        "summary": f"命中 {len(trimmed)} 条历史记忆" if trimmed else "暂无相关历史记忆",
    }
