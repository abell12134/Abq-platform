from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage
from openai.types.chat import ChatCompletionMessage

from app.llm.langchain_client import (
    ai_message_to_tool_calls,
    ainvoke_chat,
    astream_text,
    build_chat_model,
    dict_messages_to_lc,
)
from app.llm.providers import OpenAICompatibleProvider


@dataclass
class LlmTurnResult:
    message: ChatCompletionMessage
    content: str
    tool_calls: list[dict[str, Any]]


@dataclass
class StreamContentChunk:
    text: str


class LlmChat:
    """Thin facade over LangChain ChatOpenAI (OpenAI-compatible providers)."""

    def __init__(self, provider: OpenAICompatibleProvider, *, model: str | None = None) -> None:
        self.provider = provider
        self.model = model or provider.spec.default_model
        self._chat = build_chat_model(provider, model=self.model)

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> LlmTurnResult:
        chat = build_chat_model(
            self.provider,
            model=self.model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        response = await ainvoke_chat(chat, messages, tools=tools)
        content = response.content if isinstance(response.content, str) else ""
        tool_calls = ai_message_to_tool_calls(response)
        return LlmTurnResult(
            message=ChatCompletionMessage(role="assistant", content=content),
            content=content,
            tool_calls=tool_calls,
        )

    async def stream_text(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> AsyncIterator[StreamContentChunk]:
        chat = build_chat_model(
            self.provider,
            model=self.model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        lc_messages = dict_messages_to_lc(messages)
        async for chunk in chat.astream(lc_messages):
            if isinstance(chunk, AIMessage) and chunk.content:
                text = chunk.content if isinstance(chunk.content, str) else str(chunk.content)
                yield StreamContentChunk(text=text)

    async def stream_or_complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        on_text: Callable[[str], Awaitable[None]] | None = None,
    ) -> LlmTurnResult:
        if tools:
            return await self.complete(
                messages,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        chat = build_chat_model(
            self.provider,
            model=self.model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        response = await astream_text(chat, messages, on_text=on_text)
        content = response.content if isinstance(response.content, str) else ""
        return LlmTurnResult(
            message=ChatCompletionMessage(role="assistant", content=content),
            content=content,
            tool_calls=[],
        )
