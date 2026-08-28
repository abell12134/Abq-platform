"""Rule-based library composition: map user text → agent / prompt hints."""

from __future__ import annotations

import re
from typing import Any

from app.agents.specs import extract_symbol, extract_symbols
from app.orchestration.nl_plan import (
    detect_simple_intent,
    is_factor_mine_intent,
    is_factor_screen_intent,
    parse_factor_mine_plan,
    parse_factor_screen_plan,
    parse_nl_plan,
)
from app.persistence.library_store import library_store

_DEFAULT_VIEW_AGENTS = ("tech", "fundamental", "sentiment")
_MARKET_VIEW_AGENTS = ("market", "sentiment")
_PORTFOLIO_VIEW_AGENTS = ("portfolio",)
_VALID_VIEW = frozenset(_DEFAULT_VIEW_AGENTS)
_VALID_MARKET = frozenset(_MARKET_VIEW_AGENTS)
_VALID_PORTFOLIO = frozenset(_PORTFOLIO_VIEW_AGENTS)

_MARKET_KIND_RE = re.compile(
    r"大盘|市场研判|指数走势|沪深\s*300|上证指数|上证综指|创业板指|全市场|宽基",
    re.IGNORECASE,
)
_PORTFOLIO_KIND_RE = re.compile(
    r"自选|组合|持仓|选组|多票|一篮子|portfolio",
    re.IGNORECASE,
)
_MEMORY_RE = re.compile(
    r"上次|之前|历史研判|近\s*\d+\s*天|对比|增量|变化|还记得|以前说过",
    re.IGNORECASE,
)

_RULES: list[tuple[re.Pattern[str], dict[str, Any]]] = [
    (
        re.compile(r"舆情|公告|新闻|情绪|热搜|减持|增持|监管"),
        {
            "agent_ids": ["sentiment", "tech"],
            "prompt_id": "sentiment-instructions",
            "rationale": "检测到舆情相关表述，优先跑舆情视角",
        },
    ),
    (
        re.compile(r"财报|估值|PE|PB|ROE|盈利|营收|基本面|业绩"),
        {
            "agent_ids": ["fundamental", "tech"],
            "prompt_id": "fundamental-instructions",
            "rationale": "检测到基本面相关表述，优先跑基本面视角",
        },
    ),
    (
        re.compile(r"量价|背离|均线|MACD|RSI|K线|突破|支撑|压力|技术"),
        {
            "agent_ids": ["tech", "fundamental"],
            "prompt_id": "tech-instructions",
            "rationale": "检测到技术面相关表述，优先跑技术视角",
        },
    ),
    (
        re.compile(r"多空|辩论|牛熊|看多|看空"),
        {
            "agent_ids": list(_DEFAULT_VIEW_AGENTS),
            "enable_debate": True,
            "rationale": "检测到多空辩论意图，保留三视角并开启辩论",
        },
    ),
]


def _active_agent_ids() -> set[str]:
    library_store.ensure()
    return {a.id for a in library_store.list_agents() if a.status == "active"}


def has_memory_intent(text: str) -> bool:
    return bool(_MEMORY_RE.search((text or "").strip()))


def route_compose(
    message: str,
    *,
    focus: str | None = None,
    kind: str = "single",
) -> dict[str, Any]:
    text = f"{message or ''} {focus or ''}".strip()
    symbol = extract_symbol(text)
    active = _active_agent_ids()

    simple = detect_simple_intent(text)
    if simple:
        intent = simple.get("intent")
        if intent == "list_portfolios":
            return {
                "kind": "single",
                "target": None,
                "agent_ids": [],
                "prompt_id": None,
                "enable_debate": False,
                "rationale": "检测到列出组合意图，编排层直接返回组合列表（无需 LLM）",
                "intent": "list_portfolios",
            }
        if intent == "list_factors":
            theme = simple.get("theme")
            return {
                "kind": "single",
                "target": None,
                "agent_ids": [],
                "prompt_id": None,
                "enable_debate": False,
                "rationale": f"检测到列出因子意图，编排层直接返回因子列表（无需 LLM）{f'· 主题 {theme}' if theme else ''}",
                "intent": "list_factors",
                "theme": theme,
            }
        if intent == "factor_mine":
            mode = simple.get("mode", "llm")
            label = "GP" if mode == "gp" else "LLM"
            return {
                "kind": "single",
                "target": None,
                "agent_ids": [],
                "prompt_id": None,
                "enable_debate": False,
                "rationale": f"检测到因子挖掘意图，编排层直接启动{label}挖掘（无需 supervisor）",
                "intent": "factor_mine",
                "plan": simple,
            }
        if intent == "ingest_policy":
            return {
                "kind": "single",
                "target": simple.get("symbol"),
                "agent_ids": [],
                "prompt_id": None,
                "enable_debate": False,
                "rationale": "检测到政策入库意图，编排层直接写入知识库（无需 supervisor）",
                "intent": "ingest_policy",
                "plan": simple,
            }
        if intent == "search_knowledge":
            return {
                "kind": "single",
                "target": simple.get("symbol"),
                "agent_ids": [],
                "prompt_id": None,
                "enable_debate": False,
                "rationale": "检测到知识库检索意图，编排层直接检索（无需 supervisor）",
                "intent": "search_knowledge",
                "plan": simple,
            }
        if intent == "cancel_analysis":
            return {
                "kind": "single",
                "target": None,
                "agent_ids": [],
                "prompt_id": None,
                "enable_debate": False,
                "rationale": "检测到取消分析意图，编排层直接中断进行中的任务",
                "intent": "cancel_analysis",
            }

    resolved_kind = kind
    symbols = extract_symbols(text)
    if kind == "single" and not symbol and _MARKET_KIND_RE.search(text) and not is_factor_screen_intent(text):
        resolved_kind = "market"
    elif kind == "single" and is_factor_screen_intent(text):
        resolved_kind = "single"
    elif kind == "single" and (len(symbols) >= 2 or (_PORTFOLIO_KIND_RE.search(text) and not symbol)):
        resolved_kind = "portfolio"

    if resolved_kind == "market":
        agent_ids = [a for a in _MARKET_VIEW_AGENTS if a in active]
        return {
            "kind": "market",
            "target": "sh000300",
            "agent_ids": agent_ids or ["market"],
            "prompt_id": "market-instructions",
            "enable_debate": False,
            "rationale": "检测到大盘研判意图，走指数链路（沪深300）",
        }

    if resolved_kind == "portfolio":
        agent_ids = [a for a in _PORTFOLIO_VIEW_AGENTS if a in active]
        return {
            "kind": "portfolio",
            "target": symbols[0] if len(symbols) == 1 else None,
            "agent_ids": agent_ids or ["portfolio"],
            "prompt_id": "portfolio-instructions",
            "enable_debate": False,
            "rationale": "检测到选组/组合意图，走组合诊断链路",
        }

    plan = parse_nl_plan(text)
    if plan:
        return {
            "kind": "single",
            "target": None,
            "agent_ids": ["supervisor"] if "supervisor" in active else [],
            "prompt_id": None,
            "enable_debate": False,
            "rationale": "检测到复合选股任务（选股→导入选组/诊断）",
            "intent": "composite_screen",
            "plan": plan,
        }

    if resolved_kind == "single" and not symbol and is_factor_screen_intent(text):
        screen_plan = parse_factor_screen_plan(text, focus=focus)
        if screen_plan:
            return {
                "kind": "single",
                "target": None,
                "agent_ids": [],
                "prompt_id": None,
                "enable_debate": False,
                "rationale": "检测到因子选股意图，编排层直接执行截面筛选（无需 LLM）",
                "intent": "factor_screen",
                "plan": screen_plan,
            }
        return {
            "kind": "single",
            "target": None,
            "agent_ids": ["supervisor"] if "supervisor" in active else [],
            "prompt_id": None,
            "enable_debate": False,
            "rationale": "检测到因子选股意图，可走编排助手执行截面筛选",
            "intent": "factor_screen",
        }

    if resolved_kind == "single" and not symbol and is_factor_mine_intent(text):
        mine_plan = parse_factor_mine_plan(text, focus=focus)
        if mine_plan:
            mode = mine_plan.get("mode", "llm")
            label = "GP" if mode == "gp" else "LLM"
            return {
                "kind": "single",
                "target": None,
                "agent_ids": [],
                "prompt_id": None,
                "enable_debate": False,
                "rationale": f"检测到因子挖掘意图，编排层直接启动{label}挖掘（无需 supervisor）",
                "intent": "factor_mine",
                "plan": mine_plan,
            }
        return {
            "kind": "single",
            "target": None,
            "agent_ids": ["supervisor"] if "supervisor" in active else [],
            "prompt_id": None,
            "enable_debate": False,
            "rationale": "检测到因子挖掘意图，可走编排助手启动挖掘任务",
            "intent": "factor_mine",
        }

    agent_ids = [a for a in _DEFAULT_VIEW_AGENTS if a in active]
    prompt_id: str | None = None
    rationale = "标准单票链路：技术 + 基本面 + 舆情并行"
    enable_debate: bool | None = None

    for pattern, cfg in _RULES:
        if pattern.search(text):
            raw_ids = cfg.get("agent_ids") or agent_ids
            agent_ids = [a for a in raw_ids if a in active and a in _VALID_VIEW] or agent_ids
            prompt_id = cfg.get("prompt_id") or prompt_id
            rationale = str(cfg.get("rationale") or rationale)
            if "enable_debate" in cfg:
                enable_debate = bool(cfg["enable_debate"])
            break

    return {
        "kind": resolved_kind,
        "target": symbol,
        "agent_ids": agent_ids,
        "prompt_id": prompt_id,
        "enable_debate": enable_debate,
        "rationale": rationale,
        "memory_intent": has_memory_intent(text),
    }
