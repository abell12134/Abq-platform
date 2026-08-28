from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_openai import ChatOpenAI

from app.llm.providers import OpenAICompatibleProvider
from app.llm.router import ResolvedLlm


def build_chat_model(
    provider: OpenAICompatibleProvider,
    *,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> ChatOpenAI:
    return ChatOpenAI(
        model=model or provider.spec.default_model,
        api_key=provider.spec.api_key or "not-set",
        base_url=provider.spec.base_url,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def build_chat_model_from_resolved(
    resolved: ResolvedLlm,
    *,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> ChatOpenAI:
    return build_chat_model(
        resolved.provider,
        model=resolved.model,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def dict_messages_to_lc(messages: Sequence[dict[str, Any]]) -> list[BaseMessage]:
    out: list[BaseMessage] = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content") or ""
        if role == "system":
            out.append(SystemMessage(content=content))
        elif role == "user":
            out.append(HumanMessage(content=content))
        elif role == "assistant":
            ai = AIMessage(content=content)
            if msg.get("tool_calls"):
                ai.tool_calls = [
                    {
                        "id": tc["id"],
                        "name": tc["function"]["name"],
                        "args": _parse_tool_args(tc["function"].get("arguments")),
                    }
                    for tc in msg["tool_calls"]
                ]
            out.append(ai)
        elif role == "tool":
            out.append(
                ToolMessage(
                    content=content,
                    tool_call_id=msg.get("tool_call_id") or "",
                )
            )
    return out


def _parse_tool_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    import json

    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def ai_message_to_tool_calls(message: AIMessage) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for tc in message.tool_calls or []:
        args = tc.get("args") or {}
        import json

        calls.append(
            {
                "id": tc.get("id") or "",
                "name": tc.get("name") or "",
                "arguments": json.dumps(args, ensure_ascii=False),
            }
        )
    return calls


async def astream_text(
    model: BaseChatModel,
    messages: Sequence[BaseMessage | dict[str, Any]],
    *,
    on_text: Callable[[str], Awaitable[None]] | None = None,
) -> AIMessage:
    lc_messages = (
        list(messages)
        if messages and isinstance(messages[0], BaseMessage)
        else dict_messages_to_lc(messages)  # type: ignore[arg-type]
    )
    parts: list[str] = []
    async for chunk in model.astream(lc_messages):
        if not isinstance(chunk, AIMessage):
            continue
        text = chunk.content if isinstance(chunk.content, str) else ""
        if text:
            parts.append(text)
            if on_text is not None:
                await on_text(text)
    return AIMessage(content="".join(parts))


async def ainvoke_chat(
    model: BaseChatModel,
    messages: Sequence[BaseMessage | dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
) -> AIMessage:
    lc_messages = (
        list(messages)
        if messages and isinstance(messages[0], BaseMessage)
        else dict_messages_to_lc(messages)  # type: ignore[arg-type]
    )
    bound = model.bind_tools(tools) if tools else model
    response = await bound.ainvoke(lc_messages)
    if not isinstance(response, AIMessage):
        return AIMessage(content=str(response))
    return response
