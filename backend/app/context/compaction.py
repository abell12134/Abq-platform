from __future__ import annotations

import logging
import re
from typing import Any

from app.config import settings
from app.context.tokens import estimate_tokens
from app.llm.chat import LlmChat
from app.llm.router import llm_router
from app.models.context import ContextSnapshot, KeyFinding
from app.prompts.loader import load_prompt

log = logging.getLogger(__name__)

_KEEP_RECENT_ASSISTANTS = 3
_LLM_COMPACT_INPUT_CHARS = 96_000


def _step_text(step: dict[str, Any]) -> str:
    agent = step.get("agent", "?")
    role = step.get("role", "?")
    body = (step.get("result") or step.get("thought") or "").strip()
    if len(body) > 500:
        body = body[:500] + "…"
    ref = ""
    tool_calls = step.get("tool_calls") or []
    if tool_calls and tool_calls[0].get("output_ref"):
        ref = f" ref={tool_calls[0]['output_ref']}"
    return f"[{step.get('id', '?')}] {role}/{agent}{ref}: {body or '（空）'}"


def _collect_refs(steps: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for step in steps:
        for tc in step.get("tool_calls") or []:
            ref = tc.get("output_ref")
            if ref and ref not in seen:
                seen.add(ref)
                refs.append(ref)
    return refs


def _rule_compact(steps: list[dict[str, Any]]) -> ContextSnapshot:
    lines = [_step_text(s) for s in steps]
    raw_text = "\n".join(lines)
    raw_tokens = estimate_tokens(raw_text)

    findings: list[KeyFinding] = []
    for step in steps:
        if step.get("role") != "assistant":
            continue
        body = (step.get("result") or step.get("thought") or "").strip()
        if not body or body == "（模型未返回文本）":
            continue
        first = body.split("\n", 1)[0].strip()
        if len(first) > 200:
            first = first[:200] + "…"
        findings.append(
            KeyFinding(
                step_id=str(step.get("id", "")),
                agent=str(step.get("agent", "")),
                text=first,
            )
        )

    recent_assistants = [f for f in findings[-_KEEP_RECENT_ASSISTANTS:]]
    older = findings[: max(0, len(findings) - _KEEP_RECENT_ASSISTANTS)]
    summary_parts = [
        f"共 {len(steps)} 步，{len(findings)} 条 agent 结论。",
    ]
    if older:
        summary_parts.append(
            "较早结论已摘要："
            + "；".join(f"{f.agent}: {f.text[:80]}" for f in older[:6])
        )
    if recent_assistants:
        summary_parts.append(
            "最近结论："
            + "；".join(f"{f.agent}: {f.text[:120]}" for f in recent_assistants)
        )

    user_msgs = [s for s in steps if s.get("role") == "user"]
    if user_msgs:
        last_user = (user_msgs[-1].get("result") or "").strip()
        if last_user:
            summary_parts.append(f"用户最近提问：{last_user[:160]}")

    summary = "\n".join(summary_parts)
    compressed_tokens = estimate_tokens(summary) + sum(estimate_tokens(f.text) for f in recent_assistants)

    return ContextSnapshot(
        summary=summary,
        key_findings=recent_assistants if recent_assistants else findings[-5:],
        carried_outputs=_collect_refs(steps),
        total_raw_tokens=raw_tokens,
        total_compressed_tokens=compressed_tokens,
    )


def _parse_llm_snapshot(content: str, *, raw_tokens: int, refs: list[str]) -> ContextSnapshot:
    findings: list[KeyFinding] = []
    for line in content.splitlines():
        m = re.match(r"^-\s*\[([^\]]+)\]\s*([^:]+):\s*(.+)$", line.strip())
        if m:
            findings.append(KeyFinding(step_id=m.group(1), agent=m.group(2).strip(), text=m.group(3).strip()))

    summary = content.strip()
    if "## 关键发现" in content:
        before = content.split("## 关键发现", 1)[0].strip()
        if before:
            summary = before

    compressed = estimate_tokens(content)
    return ContextSnapshot(
        summary=summary[:2000],
        key_findings=findings[:20],
        carried_outputs=refs,
        total_raw_tokens=raw_tokens,
        total_compressed_tokens=compressed,
    )


class CompactionEngine:
    threshold_tokens: int = settings.context_compact_threshold_tokens

    def should_compact(self, steps: list[dict[str, Any]]) -> bool:
        if len(steps) < 4:
            return False
        text = "\n".join(_step_text(s) for s in steps)
        return estimate_tokens(text) >= self.threshold_tokens

    async def compact_steps(self, steps: list[dict[str, Any]]) -> ContextSnapshot:
        lines = [_step_text(s) for s in steps]
        raw_text = "\n".join(lines)
        raw_tokens = estimate_tokens(raw_text)
        refs = _collect_refs(steps)

        if raw_tokens < self.threshold_tokens:
            snap = _rule_compact(steps)
            snap.total_raw_tokens = raw_tokens
            return snap

        try:
            prompt = load_prompt("compaction-instructions")
            resolved = llm_router.resolve(tier="local", role="compaction")
            chat = LlmChat(resolved.provider, model=resolved.model)
            system = prompt["instructions"] or prompt["persona"]
            user_content = (
                "请压缩以下分析路径步骤，输出按模板 Markdown 结构。\n\n"
                f"步骤（共 {len(steps)} 条）：\n{raw_text[:_LLM_COMPACT_INPUT_CHARS]}"
            )
            turn = await chat.complete(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=2048,
                temperature=0.2,
            )
            if turn.content.strip():
                return _parse_llm_snapshot(turn.content, raw_tokens=raw_tokens, refs=refs)
        except Exception as exc:  # noqa: BLE001
            log.warning("LLM compaction failed, using rule-based: %s", exc)

        snap = _rule_compact(steps)
        snap.total_raw_tokens = raw_tokens
        return snap

    async def maybe_compact_findings(
        self,
        findings: list[str],
        refs: list[str],
        *,
        prior_summary: str | None = None,
    ) -> tuple[list[str], str | None]:
        text = "\n".join(findings)
        if prior_summary:
            text = prior_summary + "\n" + text
        if estimate_tokens(text) < self.threshold_tokens:
            return findings, prior_summary

        pseudo_steps = [
            {"id": f"f{i}", "role": "assistant", "agent": "finding", "result": line}
            for i, line in enumerate(findings)
        ]
        snap = await self.compact_steps(pseudo_steps)
        merged_summary = snap.summary
        if prior_summary:
            merged_summary = f"{prior_summary}\n\n{snap.summary}"
        return snap.finding_lines() or findings[-8:], merged_summary


compaction_engine = CompactionEngine()
