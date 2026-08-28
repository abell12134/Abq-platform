from __future__ import annotations

import json
import math
import re
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.llm.langchain_client import (
    ai_message_to_tool_calls,
    ainvoke_chat,
    astream_text,
    build_chat_model_from_resolved,
)
from app.llm.router import llm_router
from app.models.analysis import AnalysisStep, LlmRef, ToolCall
from app.orchestration.format_repair import try_repair_contract
from app.orchestration.stream_emit import TokenDelta, emit_token, token_emitter_active
from app.orchestration.tool_output import compact_tool_output
from app.prompts.assembler import assemble_system_prompt, build_user_turn
from app.prompts.context import PromptContext
from app.tools.registry import execute_tool, openai_tool_schemas


def _llm_ref(resolved) -> LlmRef:
    return LlmRef(tier=resolved.tier, provider=resolved.provider_id, model=resolved.model)


def _json_dumps(value: Any) -> str:
    def _default(obj: Any) -> Any:
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    return json.dumps(value, ensure_ascii=False, default=_default, allow_nan=False)


_EMPTY_RETRY_HINT = "请按系统输出合同用 Markdown 给出完整分析，不要返回空内容。"


def _contract_retry_hint(agent_id: str, content: str) -> str | None:
    if agent_id == "sentiment" and not re.search(r'"sentiment"\s*:', content):
        return (
            "输出合同未满足：正文 Markdown 各节后，必须单独一行附上 JSON，"
            '含 "sentiment"、"score"、"hard_risk" 等字段。'
        )
    if agent_id == "judge" and not re.search(r'"stance"\s*:', content):
        return (
            "输出合同未满足：正文 Markdown 各节后，必须单独一行附上 JSON，"
            '含 "stance"、"confidence"、"focus_covered" 字段。'
        )
    return None


def _content_text(message: AIMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    return ""


async def run_agent(
    agent,
    *,
    user_message: str,
    prompt_ctx: PromptContext | None = None,
    primary_override: str | None = None,
    max_turns: int = 6,
) -> AsyncIterator[AnalysisStep]:
    resolved = llm_router.resolve(
        tier=agent.model_tier,
        agent_id=agent.id,
        primary_override=primary_override,
    )
    chat_model = build_chat_model_from_resolved(resolved, max_tokens=4096)
    openai_tools = openai_tool_schemas(agent.tool_names)

    ctx = prompt_ctx or PromptContext()
    ctx.model = resolved.model

    system = assemble_system_prompt(
        agent.persona,
        agent.instructions,
        model=resolved.model,
        tool_names=agent.tool_names,
        variables=ctx.vars(),
    )
    user_turn = build_user_turn(ctx, task=user_message)

    messages: list[SystemMessage | HumanMessage | AIMessage | ToolMessage] = [
        SystemMessage(content=system),
        HumanMessage(content=user_turn),
    ]

    for turn_idx in range(max_turns):
        current_step_id = uuid4().hex[:12]

        async def on_text(delta: str, *, _step_id: str = current_step_id) -> None:
            await emit_token(TokenDelta(step_id=_step_id, agent=agent.id, delta=delta))

        use_stream = token_emitter_active() and not openai_tools
        if use_stream:
            response = await astream_text(chat_model, messages, on_text=on_text)
        else:
            response = await ainvoke_chat(chat_model, messages, tools=openai_tools or None)

        llm = _llm_ref(resolved)
        content = _content_text(response).strip()
        tool_calls = ai_message_to_tool_calls(response)

        if not tool_calls and not content and turn_idx < max_turns - 1:
            messages.append(HumanMessage(content=_EMPTY_RETRY_HINT))
            continue

        if tool_calls:
            messages.append(response)
            for tc in tool_calls:
                raw = await execute_tool(tc["name"], tc["arguments"])
                data = raw.get("data")
                summary = _json_dumps(data if data is not None else raw)
                summary = await compact_tool_output(tc["name"], summary)
                output_ref = None
                if raw.get("ok") and isinstance(data, dict):
                    output_ref = data.get("symbol")

                tool_msg = raw.get("summary") or (raw.get("error") if not raw.get("ok") else "") or "tool error"
                yield AnalysisStep(
                    id=uuid4().hex[:12],
                    agent=tc["name"],
                    role="tool",
                    thought="",
                    result=summary if raw.get("ok") else (raw.get("error") or "tool error"),
                    tool_calls=[
                        ToolCall(
                            id=tc["id"],
                            tool=tc["name"],
                            args=json.loads(tc["arguments"]) if tc["arguments"] else {},
                            output=summary,
                            output_ref=output_ref,
                            status="ok" if raw.get("ok") else "error",
                            suggested_action=raw.get("suggested_action"),
                        )
                    ],
                )
                messages.append(
                    ToolMessage(content=tool_msg, tool_call_id=tc["id"]),
                )
            continue

        final = content or "（模型未返回文本）"
        contract_hint = _contract_retry_hint(agent.id, final)
        if contract_hint and turn_idx < max_turns - 1:
            repaired = await try_repair_contract(agent.id, final)
            if repaired:
                final = repaired
                contract_hint = _contract_retry_hint(agent.id, final)
            if contract_hint:
                messages.append(AIMessage(content=final))
                messages.append(HumanMessage(content=contract_hint))
                continue

        yield AnalysisStep(
            id=current_step_id,
            agent=agent.id,
            role="assistant",
            thought=final,
            result=final,
            llm=llm,
        )
        return

    yield AnalysisStep(
        id=uuid4().hex[:12],
        agent=agent.id,
        role="assistant",
        thought="",
        result="达到最大推理轮次，请缩小问题范围后重试。",
        llm=_llm_ref(resolved),
    )
