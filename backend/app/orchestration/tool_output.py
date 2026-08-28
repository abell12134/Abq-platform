from __future__ import annotations

import logging

from app.llm.chat import LlmChat
from app.llm.router import llm_router
from app.prompts.assembler import assemble_system_prompt
from app.prompts.loader import load_agent

log = logging.getLogger(__name__)

TOOL_OUTPUT_EXTRACT_THRESHOLD = 1200
_TOOL_OUTPUT_MAX = 1200

# Deterministic pipeline fetch tools — truncate only; LLM extract adds minutes per step.
PIPELINE_DATA_TOOLS = frozenset(
    {
        "fetch_quote",
        "fetch_ohlcv",
        "clean_data",
        "calc_indicator",
        "fetch_fundamentals",
        "fetch_sentiment",
    }
)


def _truncate(text: str, limit: int = _TOOL_OUTPUT_MAX) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


async def compact_tool_output(
    tool_name: str,
    text: str,
    *,
    extract: bool = True,
) -> str:
    """Summarize long tool payloads with local extract agent; fall back to truncate."""
    stripped = text.strip()
    if len(stripped) <= TOOL_OUTPUT_EXTRACT_THRESHOLD:
        return stripped

    if not extract or tool_name in PIPELINE_DATA_TOOLS:
        return _truncate(stripped)

    try:
        agent = load_agent("extract")
        resolved = llm_router.resolve(tier="local", agent_id="extract")
        chat = LlmChat(resolved.provider, model=resolved.model)
        system = assemble_system_prompt(
            agent.persona,
            agent.instructions,
            model=resolved.model,
            tool_names=[],
            variables={"tool": tool_name},
        )
        turn = await chat.complete(
            [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": (
                        f"工具：{tool_name}\n\n"
                        "请从以下原始输出抽取关键字段与要点（保留 symbol、日期、数值）：\n\n"
                        f"{stripped[:8000]}"
                    ),
                },
            ],
            max_tokens=1024,
            temperature=0.1,
        )
        summary = (turn.content or "").strip()
        if summary:
            return _truncate(summary)
    except Exception as exc:  # noqa: BLE001
        log.warning("extract agent failed for %s: %s", tool_name, exc)

    return _truncate(stripped)
