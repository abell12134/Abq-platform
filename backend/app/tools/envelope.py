"""Normalize agent tool results into a stable envelope."""

from __future__ import annotations

from typing import Any


def tool_ok(
    data: Any = None,
    *,
    summary: str = "",
    next_hints: list[str] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": True, "summary": summary, "data": data}
    if next_hints:
        out["next_hints"] = next_hints
    return out


def tool_err(
    message: str,
    *,
    suggested_action: str | None = None,
    data: Any = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": False, "error": message, "summary": message}
    if suggested_action:
        out["suggested_action"] = suggested_action
    if data is not None:
        out["data"] = data
    return out


def wrap_tool_result(result: Any) -> dict[str, Any]:
    """Normalize a tool return value into {ok, summary, data?, error?}."""
    if isinstance(result, dict) and "ok" in result:
        out = dict(result)
        if not out.get("summary"):
            if out.get("ok"):
                out["summary"] = str(out.get("message") or "完成")
            else:
                out["summary"] = str(out.get("error") or "失败")
        if "data" not in out:
            data = {k: v for k, v in out.items() if k not in ("ok", "error", "summary", "suggested_action", "next_hints")}
            if data:
                out["data"] = data
        return out
    if isinstance(result, dict) and result.get("status") == "error":
        return tool_err(str(result.get("error") or result.get("message") or "失败"), data=result)
    summary = ""
    if isinstance(result, dict):
        summary = str(result.get("message") or result.get("status") or "")[:200]
    return tool_ok(result, summary=summary or "完成")
