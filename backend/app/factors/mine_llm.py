"""LLM factor mining: propose printable formulas → parse IR → same gates. No eval()."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.factors.evaluate import evaluate_request
from app.factors.ir import ALL_VARS, FactorExprError, parse_formula, print_expr
from app.factors.store import FactorStoreError, factor_store
from app.llm.chat import LlmChat
from app.llm.router import llm_router
from app.models.factors import FactorCreate, FactorMineLlmRequest

_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
_SLUG = re.compile(r"[^a-z0-9]+")

OPERATOR_CARD = (
    "白名单算子（禁止 pandas、eval、负 delay）：\n"
    "算术 add sub mul div abs log sign sqrt；"
    "时序 delay delta ts_mean ts_std ts_max ts_min ts_rank ts_sum ts_corr；"
    "截面 rank zscore（择时禁止）；"
    f"终端 {' '.join(sorted(ALL_VARS))}。\n"
    "窗口 n 必须是正整数。公式示例："
    "sub(div(close, delay(close, 20)), 1)、div(close, mkt_close)。"
)

SYSTEM_PROMPT = """你是 A 股截面因子研究员。只输出一个 JSON 对象，不要解释。
{ops}

输出格式：
{{"factors":[
  {{"name":"中文名","theme":"momentum|reversal|volume|volatility|liquidity|market",
    "hypothesis":"不少于 12 字的经济逻辑","formula":"只含白名单算子的打印串"}}
]}}

规则：
- formula 必须能被算子树解析，不要写 Python。
- 每个因子要有可证伪的逻辑（谁该涨、为什么）。
- 不要复制已有公式；相对大盘用 mkt_* 终端。
- 一次恰好 {k} 条。
"""


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _runs_dir() -> Path:
    factor_store.ensure()
    return factor_store.runs_dir


def _run_dir(run_id: str) -> Path:
    return _runs_dir() / run_id


def _lock_path() -> Path:
    return _runs_dir() / "_active.json"


def extract_json_value(text: str) -> Any:
    blob = (text or "").strip()
    fenced = _JSON_FENCE.search(blob)
    if fenced:
        blob = fenced.group(1).strip()
    start_obj = blob.find("{")
    start_arr = blob.find("[")
    if start_obj < 0 and start_arr < 0:
        raise ValueError("模型输出里没有 JSON")
    if start_arr >= 0 and (start_obj < 0 or start_arr < start_obj):
        start, opener, closer = start_arr, "[", "]"
    else:
        start, opener, closer = start_obj, "{", "}"
    depth = 0
    in_str = False
    escape = False
    end = None
    for i, ch in enumerate(blob[start:], start):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise ValueError("JSON 不完整")
    return json.loads(blob[start:end])


def proposals_from_payload(payload: Any) -> list[dict[str, str]]:
    if isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, dict):
        inner = payload.get("factors") or payload.get("proposals")
        if isinstance(inner, list):
            raw_items = inner
        else:
            raw_items = [payload]
    else:
        return []
    out: list[dict[str, str]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        formula = str(item.get("formula") or "").strip()
        name = str(item.get("name") or "").strip()
        if not formula or not name:
            continue
        out.append(
            {
                "name": name[:80],
                "formula": formula,
                "hypothesis": str(item.get("hypothesis") or "").strip(),
                "theme": str(item.get("theme") or "momentum").strip().lower() or "momentum",
            }
        )
    return out


def make_factor_id(formula: str, theme: str) -> str:
    digest = hashlib.sha1(formula.encode("utf-8")).hexdigest()[:6]
    slug = _SLUG.sub("", theme.lower())[:12] or "x"
    return f"llm_{slug}_{digest}"


def active_run_id() -> str | None:
    path = _lock_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    run_id = str(data.get("run_id") or "")
    if not run_id:
        return None
    progress = read_progress(run_id)
    if progress and progress.get("status") == "running":
        return run_id
    return None


def read_progress(run_id: str) -> dict[str, Any] | None:
    path = _run_dir(run_id) / "progress.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    root = _runs_dir()
    if not root.is_dir():
        return rows
    for path in sorted(root.iterdir(), reverse=True):
        if not path.is_dir():
            continue
        prog = read_progress(path.name)
        if prog:
            rows.append(prog)
        if len(rows) >= limit:
            break
    return rows


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def init_generic_run(kind: str, extra: dict[str, Any]) -> str:
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    meta = {"run_id": run_id, "kind": kind, "created_at": _now(), **extra}
    progress = {
        **meta,
        "status": "running",
        "round": 0,
        "message": "排队中…",
        "funnel": {
            "proposed": 0,
            "parse_fail": 0,
            "evaled": 0,
            "passed": 0,
            "rejected": 0,
        },
        "accepted_ids": [],
        "error": None,
        "updated_at": _now(),
    }
    directory = _run_dir(run_id)
    directory.mkdir(parents=True, exist_ok=True)
    _write(directory / "meta.json", meta)
    _write(directory / "progress.json", progress)
    _write(_lock_path(), {"run_id": run_id, "started_at": _now()})
    return run_id


def init_run(body: FactorMineLlmRequest) -> str:
    return init_generic_run(
        "llm",
        {
            "universe": body.universe,
            "rounds": body.rounds,
            "k": body.k,
            "theme_hint": body.theme_hint,
            "use_synthetic": body.use_synthetic,
        },
    )


def _patch_progress(run_id: str, **fields: Any) -> dict[str, Any]:
    current = read_progress(run_id) or {}
    current.update(fields)
    current["updated_at"] = _now()
    _write(_run_dir(run_id) / "progress.json", current)
    return current


def _catalog_brief(limit: int = 36) -> str:
    lines: list[str] = []
    for rec in factor_store.list_factors()[:limit]:
        ic = (rec.metrics or {}).get("ic_stats") or {}
        ic_mean = ic.get("ic_mean")
        ic_txt = f"{ic_mean:.4f}" if isinstance(ic_mean, (int, float)) else "—"
        reason = rec.reject_reason or rec.status
        lines.append(f"- {rec.id} | {rec.formula} | IC {ic_txt} | {reason}")
    return "\n".join(lines) if lines else "（库空）"


def _feedback_block(events: list[dict[str, Any]], limit: int = 12) -> str:
    recent = events[-limit:]
    if not recent:
        return "尚无上一轮反馈。"
    lines = []
    for ev in recent:
        lines.append(
            f"- {ev.get('name')}: {ev.get('outcome')} · {ev.get('detail')} · {ev.get('formula')}"
        )
    return "\n".join(lines)


async def _propose(
    *,
    k: int,
    theme_hint: str,
    universe: str,
    feedback: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], str]:
    resolved = llm_router.resolve(tier="primary", role="factor_mine")
    chat = LlmChat(resolved.provider, model=resolved.model)
    system = SYSTEM_PROMPT.format(ops=OPERATOR_CARD, k=k)
    user = (
        f"股票池: {universe}\n"
        f"主题侧重: {theme_hint or '不限，优先量价/动量/波动/相对大盘'}\n\n"
        f"库内已有因子：\n{_catalog_brief()}\n\n"
        f"上一轮漏斗：\n{_feedback_block(feedback)}\n\n"
        f"请提出恰好 {k} 个新因子。"
    )
    turn = await chat.complete(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.55,
        max_tokens=1800,
    )
    raw = turn.content or ""
    try:
        payload = extract_json_value(raw)
        return proposals_from_payload(payload), raw
    except (ValueError, json.JSONDecodeError) as exc:
        return [], f"{exc}\n{raw[:800]}"


async def run_llm_mine(run_id: str, body: FactorMineLlmRequest) -> None:
    directory = _run_dir(run_id)
    funnel = {"proposed": 0, "parse_fail": 0, "evaled": 0, "passed": 0, "rejected": 0}
    accepted: list[str] = []
    feedback: list[dict[str, Any]] = []
    try:
        for round_i in range(1, body.rounds + 1):
            _patch_progress(
                run_id,
                round=round_i,
                message=f"第 {round_i}/{body.rounds} 轮：请模型提议…",
                funnel=dict(funnel),
                accepted_ids=list(accepted),
            )
            proposals, raw = await _propose(
                k=body.k,
                theme_hint=body.theme_hint,
                universe=body.universe,
                feedback=feedback,
            )
            if not proposals:
                feedback.append(
                    {
                        "name": "(parse)",
                        "formula": "",
                        "outcome": "parse_fail",
                        "detail": "本轮 JSON 解析失败",
                    }
                )
                funnel["parse_fail"] += 1
                _append_jsonl(
                    directory / "candidates.jsonl",
                    {"round": round_i, "raw": raw[:2000], "outcome": "llm_parse_fail"},
                )
                continue

            for item in proposals:
                funnel["proposed"] += 1
                try:
                    expr = parse_formula(item["formula"])
                    formula = print_expr(expr)
                except FactorExprError as exc:
                    funnel["parse_fail"] += 1
                    row = {
                        "round": round_i,
                        "name": item["name"],
                        "formula": item["formula"],
                        "outcome": "parse_fail",
                        "detail": str(exc),
                    }
                    feedback.append(row)
                    _append_jsonl(directory / "candidates.jsonl", row)
                    continue

                factor_id = make_factor_id(formula, item["theme"])
                if factor_store.get(factor_id) is not None:
                    funnel["parse_fail"] += 1
                    row = {
                        "round": round_i,
                        "id": factor_id,
                        "name": item["name"],
                        "formula": formula,
                        "outcome": "duplicate",
                        "detail": "与库内公式重复",
                    }
                    feedback.append(row)
                    _append_jsonl(directory / "candidates.jsonl", row)
                    continue

                hyp = item["hypothesis"]
                if len(hyp) < 8:
                    hyp = (hyp + "；截面排序后应与未来收益同向。")[:200]

                try:
                    rec = factor_store.create(
                        FactorCreate(
                            id=factor_id,
                            name=item["name"],
                            formula=formula,
                            hypothesis=hyp,
                            theme=[item["theme"]],
                            universe=body.universe,
                            origin="llm",
                        )
                    )
                except (FactorStoreError, FactorExprError) as exc:
                    funnel["parse_fail"] += 1
                    row = {
                        "round": round_i,
                        "id": factor_id,
                        "name": item["name"],
                        "formula": formula,
                        "outcome": "parse_fail",
                        "detail": str(exc),
                    }
                    feedback.append(row)
                    _append_jsonl(directory / "candidates.jsonl", row)
                    continue

                _patch_progress(
                    run_id,
                    message=f"第 {round_i} 轮：评测 {rec.name}…",
                    funnel=dict(funnel),
                    accepted_ids=list(accepted),
                )
                try:
                    result = await evaluate_request(
                        factor_id=rec.id,
                        formula=None,
                        universe=body.universe,
                        symbols=None,
                        lookback=250,
                        use_synthetic=body.use_synthetic,
                        persist=True,
                    )
                except Exception as exc:  # noqa: BLE001
                    funnel["evaled"] += 1
                    funnel["rejected"] += 1
                    row = {
                        "round": round_i,
                        "id": rec.id,
                        "name": rec.name,
                        "formula": formula,
                        "outcome": "eval_error",
                        "detail": str(exc),
                    }
                    feedback.append(row)
                    _append_jsonl(directory / "candidates.jsonl", row)
                    continue

                funnel["evaled"] += 1
                metrics = result.get("metrics") or {}
                status = str(metrics.get("status") or "")
                reason = str(metrics.get("reject_reason") or "")
                passed = status in {"passed_auto", "paper_tracking", "live"}
                if passed:
                    funnel["passed"] += 1
                    accepted.append(rec.id)
                    outcome = "passed"
                else:
                    funnel["rejected"] += 1
                    outcome = "rejected"
                ic = (metrics.get("ic_stats") or {}).get("ic_mean")
                row = {
                    "round": round_i,
                    "id": rec.id,
                    "name": rec.name,
                    "formula": formula,
                    "outcome": outcome,
                    "detail": reason or status,
                    "ic_mean": ic,
                    "status": status,
                }
                feedback.append(row)
                _append_jsonl(directory / "candidates.jsonl", row)

        report = [
            f"# LLM 挖掘 {run_id}",
            "",
            f"- 轮次 {body.rounds} · 每轮 {body.k} · 股票池 {body.universe}",
            f"- 提议 {funnel['proposed']} · 解析失败 {funnel['parse_fail']} · 评测 {funnel['evaled']}",
            f"- 过关 {funnel['passed']} · 淘汰 {funnel['rejected']}",
            f"- 过关 id: {', '.join(accepted) or '无'}",
            "",
        ]
        (_run_dir(run_id) / "report.md").write_text("\n".join(report), encoding="utf-8")
        _patch_progress(
            run_id,
            status="done",
            round=body.rounds,
            message=f"完成。过关 {funnel['passed']} / 提议 {funnel['proposed']}",
            funnel=funnel,
            accepted_ids=accepted,
        )
    except Exception as exc:  # noqa: BLE001
        _patch_progress(
            run_id,
            status="error",
            message="挖掘失败",
            error=str(exc),
            funnel=funnel,
            accepted_ids=accepted,
        )
        raise
    finally:
        if _lock_path().exists():
            try:
                lock = json.loads(_lock_path().read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                lock = {}
            if lock.get("run_id") == run_id:
                _lock_path().unlink(missing_ok=True)
