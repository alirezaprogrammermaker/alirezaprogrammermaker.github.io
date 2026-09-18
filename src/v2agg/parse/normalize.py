from __future__ import annotations

import re
from urllib.parse import quote, unquote, urlparse, urlunparse


_SRC_HINT = re.compile(
    r"(github|gitlab|raw\.|channel|subscribe|sub[-_ ]?link|scraped|source|mirror|aggregator)",
    re.IGNORECASE,
)


def sanitize_remark(remark: str, prefix: str = "⚡", index: int | None = None) -> str:
    """Public remark without provenance. Keep short and neutral."""
    text = unquote(remark or "").strip()
    text = re.sub(r"\s+", " ", text)
    if not text or _SRC_HINT.search(text):
        label = f"{prefix}{index}" if index is not None else f"{prefix}node"
        return label[:32]
    # Drop overly long / noisy remarks
    text = text[:40]
    if prefix and not text.startswith(prefix):
        text = f"{prefix}{text}"
    return text


def rewrite_remark(raw_link: str, remark: str) -> str:
    if "#" in raw_link:
        base = raw_link.rsplit("#", 1)[0]
    else:
        base = raw_link
    return f"{base}#{quote(remark, safe='')}"


def normalize_for_dedup(cfg_host: str, cfg_port: int, scheme: str, credential: str) -> str:
    return f"{scheme.lower()}|{cfg_host.lower()}|{cfg_port}|{credential}"


def strip_query_noise(link: str) -> str:
    """Best-effort normalize URI for comparison (does not alter published raw)."""
    try:
        p = urlparse(link)
        return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path, "", p.query, ""))
    except Exception:
        return link.strip()
