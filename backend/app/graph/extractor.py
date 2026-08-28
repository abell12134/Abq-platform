from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from app.config import settings
from app.graph.models import GraphNode
from app.graph.store import graph_store, sector_node_id, stock_node_id

log = logging.getLogger(__name__)

RelationType = Literal["SUPPLIES_TO", "COMPETES_WITH"]
_MIN_CONFIDENCE = 0.7


async def extract_supply_chain_triples(
    symbol: str,
    *,
    company_name: str = "",
    sector: str = "",
    evidence_titles: list[str] | None = None,
) -> dict[str, Any]:
    """LLM 从标题证据抽取产业链关系，低置信度边不入图。"""
    if not settings.graph_extract_triples_enabled:
        return {"status": "disabled", "edges": 0}

    titles = [t.strip() for t in (evidence_titles or []) if t.strip()][:20]
    if not titles:
        return {"status": "empty", "edges": 0, "message": "无证据标题"}

    triples = await _llm_extract(company_name or symbol, sector, titles)
    if not triples:
        return {"status": "empty", "edges": 0, "message": "LLM 未返回三元组"}

    sym = symbol.lower()
    sid = stock_node_id(sym)
    if not graph_store.get_node(sid):
        graph_store.upsert_node(
            GraphNode(id=sid, type="Stock", label=company_name or sym, props={"symbol": sym})
        )

    linked = 0
    for row in triples:
        rel = str(row.get("relation") or "").upper()
        if rel not in ("SUPPLIES_TO", "COMPETES_WITH"):
            continue
        conf = float(row.get("confidence") or 0)
        if conf < _MIN_CONFIDENCE:
            continue
        target = str(row.get("target") or "").strip()
        if not target:
            continue
        dst = _resolve_target_node(target, sector_hint=sector)
        if not dst or dst == sid:
            continue
        graph_store.link_edge(
            sid,
            dst,
            rel,  # type: ignore[arg-type]
            props={
                "confidence": conf,
                "source": "llm_extract",
                "evidence": str(row.get("evidence") or "")[:200],
            },
        )
        linked += 1

    return {"status": "ok", "edges": linked, "triples_parsed": len(triples)}


def _resolve_target_node(target: str, *, sector_hint: str = "") -> str | None:
    t = target.strip()
    if re.match(r"^(sh|sz|bj)\d{6}$", t, re.I):
        return stock_node_id(t.lower())
    found = graph_store.find_stock_id_by_label(t)
    if found:
        return found
    if sector_hint and t in sector_hint:
        return sector_node_id(sector_hint)
    return sector_node_id(t)


async def _llm_extract(company: str, sector: str, titles: list[str]) -> list[dict[str, Any]]:
    try:
        from app.llm.chat import LlmChat
        from app.llm.router import LlmRouter

        router = LlmRouter()
        resolved = router.resolve(tier="local")
        chat = LlmChat(resolved.provider, model=resolved.model)
        bullets = "\n".join(f"- {t}" for t in titles)
        prompt = (
            f"公司：{company}，行业：{sector or '未知'}。\n"
            "根据以下标题，抽取产业链关系，输出 JSON 数组，每项字段："
            "relation(SUPPLIES_TO|COMPETES_WITH), target(公司或行业名), "
            "confidence(0-1), evidence(引用标题片段)。"
            "不要编造，没有则返回 []。\n\n"
            f"{bullets}\n\n只输出 JSON。"
        )
        result = await chat.complete(
            [{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=800,
        )
        text = (result.content or "").strip()
        m = re.search(r"\[[\s\S]*\]", text)
        if not m:
            return []
        data = json.loads(m.group(0))
        return data if isinstance(data, list) else []
    except Exception as exc:  # noqa: BLE001
        log.warning("triple extract failed: %s", exc)
        return []
