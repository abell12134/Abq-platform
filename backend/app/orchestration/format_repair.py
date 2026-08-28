from __future__ import annotations

import re

from app.llm.chat import LlmChat
from app.llm.router import llm_router
from app.prompts.assembler import assemble_system_prompt
from app.prompts.loader import load_agent


def _contract_missing(agent_id: str, content: str) -> bool:
    if agent_id == "sentiment" and not re.search(r'"sentiment"\s*:', content):
        return True
    if agent_id == "judge" and not re.search(r'"stance"\s*:', content):
        return True
    return False


async def try_repair_contract(agent_id: str, content: str) -> str | None:
    """Use local format agent to fix trailing JSON contract. Returns repaired text or None."""
    if not _contract_missing(agent_id, content):
        return content
    try:
        agent = load_agent("format")
        resolved = llm_router.resolve(tier="local", agent_id="format")
        chat = LlmChat(resolved.provider, model=resolved.model)
        system = assemble_system_prompt(
            agent.persona,
            agent.instructions,
            model=resolved.model,
            tool_names=[],
            variables={"agent_id": agent_id},
        )
        turn = await chat.complete(
            [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": (
                        f"agent_id={agent_id}\n\n"
                        "请修复以下输出末尾 JSON 合同：\n\n"
                        f"{content[:6000]}"
                    ),
                },
            ],
            max_tokens=2048,
            temperature=0.1,
        )
        repaired = (turn.content or "").strip()
        if repaired and not _contract_missing(agent_id, repaired):
            return repaired
    except Exception:  # noqa: BLE001
        return None
    return None
