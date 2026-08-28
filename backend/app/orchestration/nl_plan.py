"""Natural-language routing plans.

Two-tier design (see DESIGN.md §4.1):

1. **Fast path** — regex/rules in this module for NL Coverage golden phrases.
   Zero LLM latency, fully testable (`test_nl_plan.py`). Used by `detect_simple_intent()`.

2. **Fallback** — when no rule matches, `analyze_stream` continues with:
   - `parse_nl_plan` / composite screen plans
   - kind pipelines (single / market / portfolio)
   - **supervisor** ReAct agent (`run_agent`) with full tool belt

Regex miss does **not** block the user; it only means the utterance is not on the
deterministic whitelist and needs the slower, flexible agent path.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from app.agents.specs import extract_symbol

_FACTOR_SCREEN_RE = re.compile(
    r"因子选股|智能选股|选票|筛票|筛选股票|选出.{0,12}(?:股票|只|支)|股票筛选|"
    r"top\s*\d+.*股|沪深\s*300.*选|中证\s*500.*选",
    re.IGNORECASE,
)

PlanAction = Literal["screen", "apply", "diagnose"]

_APPLY_RE = re.compile(
    r"导入|放进|写入|加入|合并进|加到|放到|替换",
    re.IGNORECASE,
)
_DIAGNOSE_RE = re.compile(
    r"诊断|研判|分析组合|看看组合|组合风险|配置风险",
    re.IGNORECASE,
)
_PORTFOLIO_ID_RE = re.compile(
    r"(?:组合|自选|选组)[「\"“']?([a-zA-Z0-9_-]{2,48})[」\"”']?",
    re.IGNORECASE,
)
_TOP_N_RE = re.compile(r"(?:选|选出|top)\s*(\d{1,3})\s*(?:只|支|票)?", re.IGNORECASE)

# Deterministic (no-LLM) intents handled directly by the orchestration layer.
_LIST_PORTFOLIOS_RE = re.compile(
    r"列出.{0,8}组合|有哪些组合|所有组合|我的组合|列出.{0,8}自选|"
    r"看看.{0,4}自选列表|list\s*portfolio|show\s*portfolio",
    re.IGNORECASE,
)
_LIST_FACTORS_RE = re.compile(
    r"有哪些.{0,8}因子|列出.{0,6}因子|看看因子库|因子库有哪些|因子列表|"
    r"list\s*factor|show\s*factor",
    re.IGNORECASE,
)
_FACTOR_THEME_KEYWORDS = ("动量", "反转", "波动", "流动性", "估值", "量价", "质量", "成长", "情绪")

_FACTOR_MINE_RE = re.compile(
    r"(?:挖|挖掘|发明|生成|找)(?:.{0,16})?因子|因子(?:挖掘|发明|生成)|"
    r"factor\s*mine|mine\s*factor",
    re.IGNORECASE,
)
_MINE_K_RE = re.compile(r"挖\s*(\d{1,2})\s*个|(\d{1,2})\s*个因子", re.IGNORECASE)
_MINE_ROUNDS_RE = re.compile(r"(\d{1,2})\s*轮", re.IGNORECASE)
_INGEST_POLICY_RE = re.compile(
    r"(?:政策|监管|条文|法规|规章|研报).{0,16}入库|"
    r"入库.{0,12}(?:政策|监管|条文|法规|规章|研报)|"
    r"存进知识库|写入知识库|知识库入库|"
    r"ingest\s*policy",
    re.IGNORECASE,
)
_CANCEL_ANALYSIS_RE = re.compile(
    r"取消.{0,8}分析|停止.{0,8}分析|中断.{0,6}分析|cancel\s*analysis",
    re.IGNORECASE,
)
_SEARCH_KNOWLEDGE_RE = re.compile(
    r"检索.{0,12}(?:政策|舆情|知识|研报|记忆)|"
    r"搜索.{0,12}(?:政策|舆情|知识库|知识)|"
    r"查.{0,8}(?:政策|知识库)|"
    r"search\s*knowledge",
    re.IGNORECASE,
)
_POLICY_THEME_KEYWORDS = ("监管", "信披", "减持", "回购", "ESG", "并购")


def is_factor_mine_intent(text: str) -> bool:
    """User wants LLM/GP factor mining (no stock symbol required)."""
    return bool(_FACTOR_MINE_RE.search((text or "").strip()))


def is_ingest_policy_intent(text: str) -> bool:
    """User wants to ingest policy/research text into the knowledge base."""
    return bool(_INGEST_POLICY_RE.search((text or "").strip()))


def is_cancel_analysis_intent(text: str) -> bool:
    """User wants to cancel in-flight analysis tasks."""
    return bool(_CANCEL_ANALYSIS_RE.search((text or "").strip()))


def is_search_knowledge_intent(text: str) -> bool:
    """User wants to search the archived knowledge base."""
    return bool(_SEARCH_KNOWLEDGE_RE.search((text or "").strip()))


def _extract_search_query(text: str) -> str:
    """Pull the search query from NL patterns like「检索政策：减持新规」."""
    patterns = (
        r"检索(?:政策|舆情|知识库|知识|研报|记忆)[：:]\s*(.+)",
        r"搜索(?:政策|舆情|知识库|知识|研报)[：:]\s*(.+)",
        r"查(?:政策|知识库)[：:]\s*(.+)",
        r"检索[：:]\s*(.+)",
        r"搜索[：:]\s*(.+)",
    )
    for pat in patterns:
        m = re.search(pat, text, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1).strip()
    parts = re.split(r"[：:]", text, maxsplit=1)
    if len(parts) > 1 and _SEARCH_KNOWLEDGE_RE.search(parts[0]):
        return parts[1].strip()
    return ""


def _infer_knowledge_type(text: str) -> str:
    if re.search(r"舆情|sentiment", text, re.I):
        return "sentiment"
    if re.search(r"宽度|breadth|大盘宽度", text, re.I):
        return "breadth"
    return "policy"


def parse_search_knowledge_plan(message: str, *, focus: str | None = None) -> dict[str, Any] | None:
    """Parse deterministic knowledge-search parameters."""
    text = f"{message or ''} {focus or ''}".strip()
    if not is_search_knowledge_intent(text):
        return None
    query = _extract_search_query(text)
    symbol = extract_symbol(text)
    return {
        "intent": "search_knowledge",
        "query": query,
        "knowledge_type": _infer_knowledge_type(text),
        "symbol": symbol,
        "limit": 5,
    }


def _extract_policy_body(text: str) -> tuple[str, str]:
    """Parse (title, content) from an ingest-policy message."""
    lines = text.splitlines()
    body_lines: list[str] = []
    started = False
    for line in lines:
        if not started and _INGEST_POLICY_RE.search(line):
            parts = re.split(r"[：:]", line, maxsplit=1)
            if len(parts) > 1 and parts[1].strip():
                body_lines.append(parts[1].strip())
                started = True
            continue
        started = True
        body_lines.append(line)

    body = "\n".join(body_lines).strip()
    if not body:
        parts = re.split(r"[：:]", text, maxsplit=1)
        if len(parts) > 1:
            body = parts[1].strip()

    title = ""
    content = body

    title_m = re.match(r"标题[：:]\s*(.+?)(?:\n|$)", body)
    if title_m:
        title = title_m.group(1).strip()
        content = body[title_m.end() :].strip()

    content_m = re.match(r"内容[：:]\s*", content)
    if content_m:
        content = content[content_m.end() :].strip()

    book = re.search(r"《([^》]{2,80})》", text)
    if book and not title:
        title = book.group(1)

    if not title and content:
        first = content.splitlines()[0].strip()
        if first and len(first) <= 80:
            title = first
            rest = "\n".join(content.splitlines()[1:]).strip()
            if rest:
                content = rest

    if not title:
        title = "政策文档"
    return title, content


def parse_ingest_policy_plan(message: str, *, focus: str | None = None) -> dict[str, Any] | None:
    """Parse policy-ingest parameters from NL message (title + pasted body)."""
    text = f"{message or ''} {focus or ''}".strip()
    if not is_ingest_policy_intent(text):
        return None

    title, content = _extract_policy_body(text)
    theme: str | None = None
    for kw in _POLICY_THEME_KEYWORDS:
        if kw in text:
            theme = kw
            break
    symbol = extract_symbol(text)
    return {
        "intent": "ingest_policy",
        "title": title,
        "content": content,
        "symbol": symbol,
        "theme": theme,
    }


def _extract_factor_theme(text: str) -> str | None:
    for kw in _FACTOR_THEME_KEYWORDS:
        if kw in text:
            return kw
    return None


def is_factor_screen_intent(text: str) -> bool:
    return bool(_FACTOR_SCREEN_RE.search((text or "").strip()))


def _parse_screen_params(text: str) -> dict[str, Any]:
    """Shared screen parameters for factor_screen and composite_screen plans."""
    universe = "csi500" if re.search(r"中证\s*500|csi500", text, re.I) else "csi300"
    top_n = 20
    m = _TOP_N_RE.search(text)
    if m:
        top_n = max(1, min(100, int(m.group(1))))

    portfolio_id = "default"
    pid = _PORTFOLIO_ID_RE.search(text)
    if pid and pid.group(1).lower() not in {"组合", "自选"}:
        portfolio_id = pid.group(1)
    elif re.search(r"默认自选|默认组合", text):
        portfolio_id = "default"

    mode = "replace" if re.search(r"替换|覆盖", text) else "merge"
    use_synthetic = bool(re.search(r"合成数据|试跑|synthetic", text, re.I))
    return {
        "universe": universe,
        "top_n": top_n,
        "portfolio_id": portfolio_id,
        "mode": mode,
        "use_synthetic": use_synthetic,
    }


def parse_factor_screen_plan(message: str, *, focus: str | None = None) -> dict[str, Any] | None:
    """Return a screen-only plan when the user wants factor screening without apply/diagnose."""
    text = f"{message or ''} {focus or ''}".strip()
    if not is_factor_screen_intent(text):
        return None
    if _APPLY_RE.search(text) or _DIAGNOSE_RE.search(text):
        return None
    return {
        "intent": "factor_screen",
        "steps": ["screen"],
        **_parse_screen_params(text),
    }


def parse_factor_mine_plan(message: str, *, focus: str | None = None) -> dict[str, Any] | None:
    """Parse deterministic factor-mine parameters (LLM or GP)."""
    text = f"{message or ''} {focus or ''}".strip()
    if not is_factor_mine_intent(text):
        return None

    is_gp = bool(re.search(r"GP|遗传规划|遗传算法|gplearn", text, re.I))
    if not is_gp and re.search(r"发明", text) and not re.search(r"LLM|llm", text, re.I):
        is_gp = True

    universe: str = "csi500" if re.search(r"中证\s*500|csi500", text, re.I) else "csi300"
    theme_hint = _extract_factor_theme(text) or ""
    use_synthetic = not bool(re.search(r"真实数据|不用合成|qlib\s*实", text, re.I))

    if is_gp:
        track = "cs"
        if re.search(r"大盘|择时|market", text, re.I):
            track = "market"
        elif re.search(r"截面|选股", text, re.I):
            track = "cs"
        return {
            "intent": "factor_mine",
            "mode": "gp",
            "track": track,
            "universe": universe,
            "use_synthetic": use_synthetic,
        }

    k = 3
    m = _MINE_K_RE.search(text)
    if m:
        k = max(1, min(6, int(m.group(1) or m.group(2) or 3)))

    rounds = 2
    rm = _MINE_ROUNDS_RE.search(text)
    if rm:
        rounds = max(1, min(5, int(rm.group(1))))

    return {
        "intent": "factor_mine",
        "mode": "llm",
        "universe": universe,
        "k": k,
        "rounds": rounds,
        "theme_hint": theme_hint,
        "use_synthetic": use_synthetic,
    }


def detect_simple_intent(text: str) -> dict[str, Any] | None:
    """Return a deterministic intent (with params) that skips the LLM supervisor, or None."""
    t = (text or "").strip()
    if is_cancel_analysis_intent(t):
        return {"intent": "cancel_analysis"}
    if _LIST_PORTFOLIOS_RE.search(t):
        return {"intent": "list_portfolios"}
    if _LIST_FACTORS_RE.search(t):
        return {"intent": "list_factors", "theme": _extract_factor_theme(t)}
    mine_plan = parse_factor_mine_plan(t)
    if mine_plan:
        return mine_plan
    ingest_plan = parse_ingest_policy_plan(t)
    if ingest_plan:
        return ingest_plan
    search_plan = parse_search_knowledge_plan(t)
    if search_plan:
        return search_plan
    return None


def parse_nl_plan(message: str, *, focus: str | None = None) -> dict[str, Any] | None:
    """Return a composite plan when the user wants screen + apply and/or diagnose."""
    text = f"{message or ''} {focus or ''}".strip()
    if not is_factor_screen_intent(text):
        return None

    apply_intent = bool(_APPLY_RE.search(text))
    diagnose_intent = bool(_DIAGNOSE_RE.search(text))
    if not apply_intent and not diagnose_intent:
        return None

    params = _parse_screen_params(text)
    steps: list[PlanAction] = ["screen"]
    if apply_intent:
        steps.append("apply")
    if diagnose_intent:
        steps.append("diagnose")

    return {
        "intent": "composite_screen",
        "steps": steps,
        **params,
    }
