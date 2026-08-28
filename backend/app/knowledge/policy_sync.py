from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import yaml

from app.config import settings
from app.knowledge.policy_fetcher import (
    _USER_AGENT,
    _get_throttle,
    ingest_policy_from_url,
    is_allowed_url,
)

log = logging.getLogger(__name__)

_LINK_RE = re.compile(
    r"""href=["']([^"']+(?:content\.shtml|/t\d{8}_\d+\.html)[^"']*)["']""",
    re.I,
)


@dataclass
class PolicyListItem:
    title: str
    url: str
    published: str = ""


def _sync_state_path() -> Path:
    return settings.data_dir / "knowledge" / "policy" / "sync_state.json"


def _load_sync_state() -> dict:
    path = _sync_state_path()
    if not path.exists():
        return {"seen_urls": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("seen_urls", [])
            return data
    except Exception:  # noqa: BLE001
        pass
    return {"seen_urls": []}


def _save_sync_state(state: dict) -> None:
    path = _sync_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    seen = state.get("seen_urls") or []
    state["seen_urls"] = list(dict.fromkeys(str(u) for u in seen))[-5000:]
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_policy_sources() -> list[dict]:
    path = settings.policy_sources_path
    sources: list[dict] = []
    if path.exists():
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            sources = list(raw.get("sources") or [])
        except Exception as exc:  # noqa: BLE001
            log.warning("policy sources yaml: %s", exc)
    if not sources:
        sources = [
            {
                "id": "csrc_default",
                "name": "证监会-法规",
                "issuer": "证监会",
                "list_url": "https://www.csrc.gov.cn/csrc/c101953/common_list.shtml",
                "max_per_run": 3,
            }
        ]
    return sources


def _normalize_link(base_url: str, href: str) -> str:
    url = urljoin(base_url, href.strip())
    if not is_allowed_url(url):
        return ""
    return url.split("#")[0]


def _title_near_link(html: str, url: str) -> str:
    frag = url.rsplit("/", 1)[-1]
    idx = html.find(frag)
    if idx < 0:
        return frag
    snippet = html[max(0, idx - 200) : idx + 200]
    m = re.search(r">([^<]{8,120})<", snippet)
    return m.group(1).strip() if m else frag


async def fetch_policy_list(source: dict) -> list[PolicyListItem]:
    list_url = str(source.get("list_url") or "").strip()
    if not list_url or not is_allowed_url(list_url):
        return []

    throttle = _get_throttle()
    await throttle.wait()

    headers = {"User-Agent": _USER_AGENT}
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(settings.policy_fetch_timeout_s),
    ) as client:
        resp = await client.get(list_url, headers=headers)
        resp.raise_for_status()
        html = resp.text

    items: list[PolicyListItem] = []
    seen: set[str] = set()
    for href in _LINK_RE.findall(html):
        url = _normalize_link(list_url, href)
        if not url or url in seen:
            continue
        seen.add(url)
        title = _title_near_link(html, url)
        items.append(PolicyListItem(title=title[:200], url=url))
    return items


async def sync_policy_sources(
    *,
    source_id: str | None = None,
    max_total: int | None = None,
) -> dict:
    """增量同步政策列表页，仅入库未见过的 URL（限速）。"""
    state = _load_sync_state()
    seen = set(state.get("seen_urls") or [])
    cap = max_total or settings.policy_sync_max_per_run
    ingested: list[dict] = []
    skipped = 0
    errors: list[str] = []

    for src in load_policy_sources():
        if source_id and str(src.get("id")) != source_id:
            continue
        per_src = int(src.get("max_per_run") or cap)
        try:
            items = await fetch_policy_list(src)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{src.get('id')}: list {exc}")
            continue

        new_items = [i for i in items if i.url not in seen]
        for item in new_items[:per_src]:
            if len(ingested) >= cap:
                break
            try:
                result = await ingest_policy_from_url(
                    item.url,
                    title=item.title,
                    issuer=str(src.get("issuer") or ""),
                    theme=str(src.get("theme") or "") or None,
                )
                if result.get("status") == "ok":
                    seen.add(item.url)
                    ingested.append(
                        {"url": item.url, "title": item.title, "doc_id": result.get("doc_id")}
                    )
                else:
                    errors.append(f"{item.url}: {result.get('message')}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{item.url}: {exc}")
        skipped += max(0, len(new_items) - per_src)

    state["seen_urls"] = sorted(seen)
    state["last_sync_at"] = datetime.now(UTC).isoformat()
    _save_sync_state(state)

    return {
        "status": "ok" if not errors else "partial",
        "ingested": len(ingested),
        "skipped": skipped,
        "items": ingested,
        "errors": errors[:20],
    }
