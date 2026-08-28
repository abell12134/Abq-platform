from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Rough token estimate (CJK-heavy text ~3 chars/token)."""
    if not text:
        return 0
    return max(1, len(text) // 3)


def estimate_messages_tokens(messages: list[dict]) -> int:
    total = 0
    for msg in messages:
        content = msg.get("content") or ""
        if isinstance(content, str):
            total += estimate_tokens(content)
        total += 4
    return total
