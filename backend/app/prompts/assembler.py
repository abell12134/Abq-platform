from __future__ import annotations

import re

from app.prompts.context import PromptContext
from app.prompts.segments import INSTRUMENT_GUARD, PLATFORM_IDENTITY, PLATFORM_SAFETY, TOOL_GUIDANCE

_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


class PromptAssemblyError(ValueError):
    pass


def interpolate(template: str, variables: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in variables:
            raise PromptAssemblyError(f"missing prompt variable: {{{{{key}}}}}")
        return variables[key]

    return _VAR_RE.sub(repl, template)


def assemble_system_prompt(
    persona: str,
    instructions: str,
    *,
    model: str,
    tool_names: list[str],
    variables: dict[str, str] | None = None,
) -> str:
    vars_all = {"model": model, **(variables or {})}
    persona_text = interpolate(persona, vars_all) if "{{" in persona else persona.strip()
    instructions_text = (
        interpolate(instructions, vars_all) if "{{" in instructions else instructions.strip()
    )
    parts = [
        interpolate(PLATFORM_IDENTITY, vars_all),
        persona_text,
        PLATFORM_SAFETY,
        instructions_text,
    ]
    symbol = vars_all.get("symbol", "")
    if symbol and symbol != "（未指定）":
        parts.insert(3, interpolate(INSTRUMENT_GUARD, vars_all))
    for name in tool_names:
        guidance = TOOL_GUIDANCE.get(name)
        if guidance:
            parts.append(guidance.strip())
    return "\n\n".join(p for p in parts if p)


def build_user_turn(ctx: PromptContext, *, task: str) -> str:
    variables = ctx.vars()
    findings = ctx.snapshot_findings or ["（尚无，这是第一步）"]
    findings_block = "\n".join(f"- {line}" for line in findings)
    carried = ctx.carried_output_refs
    carried_block = ", ".join(carried) if carried else "（无）"
    summary = ctx.snapshot_summary or "（尚无，这是第一步）"
    reports_block = (
        ctx.reports.reports_markdown()
        if ctx.reports
        else "（尚无结构化报告）"
    )
    debate_block = (ctx.debate_history or "").strip() or "（无多空辩论）"
    memory_block = (
        "\n".join(f"- {line}" for line in ctx.memory_hints)
        if ctx.memory_hints
        else "（本轮未预取历史记忆）"
    )

    runtime = f"""## 本轮分析上下文
- 分析种类: {variables["path_kind"]}
- 市场: {variables["realm"]}
- 标的: {variables["symbol"]}
- 数据日 as_of: {variables["as_of"]}
- 用户侧重: {variables["focus"]}

## 结构化报告（各 agent 结论）
{reports_block}

## 多空辩论记录
{debate_block}

## 跨会话记忆（归档检索，非本轮工具实时数据）
{memory_block}

## 已压缩的历史（ContextSnapshot）
- 摘要: {summary}
- 关键发现:
{findings_block}
- 仍携带的原始输出: {carried_block}

## 本步任务
{task.strip()}"""
    return runtime
