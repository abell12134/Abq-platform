from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import yaml

from app.config import settings
from app.graph.rate_limit import FetchThrottle

log = logging.getLogger(__name__)

_throttle: FetchThrottle | None = None
_allowed_hosts: set[str] | None = None

_USER_AGENT = "ABQ-Lab/0.1 (local research; +https://github.com)"


@dataclass
class PolicyPageContent:
    url: str
    title: str
    text: str
    content_type: str


def _policy_sources_path() -> Path:
    return settings.policy_sources_path


def _get_throttle() -> FetchThrottle:
    global _throttle
    interval = settings.policy_fetch_min_interval_s
    if _throttle is None or _throttle.min_interval_s != interval:
        _throttle = FetchThrottle(interval)
    return _throttle


def load_allowed_hosts() -> set[str]:
    global _allowed_hosts
    if _allowed_hosts is not None:
        return _allowed_hosts

    path = _policy_sources_path()
    hosts: set[str] = set()
    if path.exists():
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for h in raw.get("allowed_hosts") or []:
                hosts.add(str(h).strip().lower())
        except Exception as exc:  # noqa: BLE001
            log.warning("policy_sources.yaml parse failed: %s", exc)

    for extra in settings.policy_allowed_hosts_extra.split(","):
        extra = extra.strip().lower()
        if extra:
            hosts.add(extra)

    _allowed_hosts = hosts
    return hosts


def reload_policy_hosts() -> set[str]:
    global _allowed_hosts
    _allowed_hosts = None
    return load_allowed_hosts()


def is_allowed_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    allowed = load_allowed_hosts()
    if host in allowed:
        return True
    # allow subdomain of whitelisted root, e.g. zhengce.www.gov.cn
    return any(host == h or host.endswith(f".{h}") for h in allowed)


def _validate_redirect_url(url: str) -> None:
    if not is_allowed_url(url):
        raise ValueError(f"跳转目标不在白名单: {url}")


def _extract_title(html_text: str) -> str:
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html_text)
    if not m:
        return ""
    return re.sub(r"\s+", " ", html.unescape(m.group(1))).strip()


def html_to_text(html_text: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html_text)
    text = re.sub(r"(?is)<!--.*?-->", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def fetch_policy_content(url: str) -> PolicyPageContent:
    """Fetch policy page from whitelisted host. Rate-limited."""
    url = url.strip()
    if not is_allowed_url(url):
        raise ValueError("URL 不在政策白名单内，请检查 data/policy_sources.yaml")

    throttle = _get_throttle()
    await throttle.wait()

    headers = {"User-Agent": _USER_AGENT, "Accept": "text/html,application/pdf,*/*"}
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(settings.policy_fetch_timeout_s),
    ) as client:
        current = url
        for _ in range(5):
            resp = await client.get(current, headers=headers)
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("location")
                if not loc:
                    break
                current = urljoin(current, loc)
                _validate_redirect_url(current)
                continue
            resp.raise_for_status()
            content_type = (resp.headers.get("content-type") or "").split(";")[0].lower()
            data = resp.content

            if "pdf" in content_type or current.lower().endswith(".pdf"):
                from app.knowledge.ingest import extract_pdf_text
                from io import BytesIO
                from pathlib import Path as P

                tmp = P(settings.data_dir / "knowledge" / "policy" / "uploads" / "_tmp_fetch.pdf")
                tmp.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_bytes(data)
                try:
                    text = extract_pdf_text(tmp)
                finally:
                    tmp.unlink(missing_ok=True)
                title = P(urlparse(current).path).stem or "政策 PDF"
                return PolicyPageContent(
                    url=current,
                    title=title,
                    text=text,
                    content_type=content_type or "application/pdf",
                )

            html_text = resp.text
            title = _extract_title(html_text) or urlparse(current).path.rsplit("/", 1)[-1]
            text = html_to_text(html_text)
            if len(text) < 80:
                raise ValueError("页面正文过短，可能需手工粘贴入库")
            return PolicyPageContent(
                url=current,
                title=title[:200],
                text=text,
                content_type=content_type or "text/html",
            )

    raise ValueError("重定向次数过多")


async def ingest_policy_from_url(
    url: str,
    *,
    title: str | None = None,
    symbol: str | None = None,
    theme: str | None = None,
    issuer: str | None = None,
) -> dict:
    from app.knowledge.ingest import ingest_text_document

    page = await fetch_policy_content(url)
    doc_title = (title or "").strip() or page.title
    result = await ingest_text_document(
        title=doc_title,
        content=page.text,
        symbol=symbol,
        theme=theme,
        source="url",
        filename=page.url,
        url=page.url,
        issuer=issuer,
    )
    return {
        **result,
        "url": page.url,
        "fetched_title": page.title,
        "content_type": page.content_type,
    }
