from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from app.models.analysis import AnalysisPathIndexEntry, PathKind
from app.models.pipeline import PipelineReports

_STANCE_RE = re.compile(r'"stance"\s*:\s*"(observe|cautious|avoid)"', re.I)
_JSON_BLOCK_RE = re.compile(r"\{[^{}]*\"stance\"[^{}]*\}", re.S)


def _first_line(text: str, limit: int = 200) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line[:limit]
    return text.strip()[:limit]


def parse_judge_stance(content: str) -> str | None:
    if not content:
        return None
    for match in _JSON_BLOCK_RE.finditer(content):
        try:
            data = json.loads(match.group(0))
            stance = data.get("stance")
            if stance in ("observe", "cautious", "avoid"):
                return str(stance)
        except json.JSONDecodeError:
            continue
    m = _STANCE_RE.search(content)
    return m.group(1).lower() if m else None


def parse_judge_one_liner(content: str) -> str:
    if not content:
        return ""
    if "## 结论" in content:
        part = content.split("## 结论", 1)[1]
        for section in ("## 分项依据", "## 分歧", "## 失效", "## 未决"):
            if section in part:
                part = part.split(section, 1)[0]
        body = part.strip()
        if body:
            return _first_line(body, 200)
    return _first_line(content, 200)


def infer_symbols(
    *,
    kind: PathKind,
    target: str | None,
    reports: PipelineReports | None,
) -> list[str]:
    symbols: list[str] = []
    if target:
        symbols.append(target.lower())
    if kind == "market" and not symbols:
        symbols.append("sh000300")
    return symbols


def extract_path_memory_meta(
    entry: AnalysisPathIndexEntry,
    reports_data: dict[str, Any] | None,
) -> dict[str, Any]:
    reports = PipelineReports.model_validate(reports_data) if reports_data else PipelineReports()
    judge_content = reports.judge.content if reports.judge else ""
    stance = parse_judge_stance(judge_content)
    one_liner = parse_judge_one_liner(judge_content)
    symbols = infer_symbols(kind=entry.kind, target=entry.target, reports=reports)

    tags: list[str] = []
    if entry.focus:
        tags.append(entry.focus[:40])
    if stance:
        tags.append(stance)

    return {
        "symbols": symbols,
        "judge_stance": stance,
        "judge_one_liner": one_liner or None,
        "data_as_of": datetime.now(UTC).date().isoformat(),
        "tags": tags,
    }
