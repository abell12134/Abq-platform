from __future__ import annotations

import json
from typing import Any

from langchain_core.utils.function_calling import convert_to_openai_tool

from app.tools.envelope import wrap_tool_result
from app.tools.langchain_tools import ALL_TOOLS, TOOL_BY_NAME


def openai_tool_schemas(names: list[str] | None = None) -> list[dict[str, Any]]:
    tools = ALL_TOOLS if names is None else [TOOL_BY_NAME[n] for n in names if n in TOOL_BY_NAME]
    return [convert_to_openai_tool(t) for t in tools]


def langchain_tools(names: list[str] | None = None):
    if names is None:
        return list(ALL_TOOLS)
    return [TOOL_BY_NAME[n] for n in names if n in TOOL_BY_NAME]


async def execute_tool(name: str, arguments: str | dict[str, Any]) -> dict[str, Any]:
    tool = TOOL_BY_NAME.get(name)
    if tool is None:
        return {"ok": False, "error": f"unknown tool: {name}"}
    args = json.loads(arguments) if isinstance(arguments, str) else arguments
    try:
        result = await tool.ainvoke(args)
        return wrap_tool_result(result)
    except Exception as exc:  # noqa: BLE001
        return wrap_tool_result({"ok": False, "error": str(exc)})
