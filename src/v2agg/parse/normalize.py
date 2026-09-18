from __future__ import annotations

import base64
import json
import re
from urllib.parse import quote, unquote, urlparse, urlunparse


_SRC_HINT = re.compile(
    r"(github|gitlab|raw\.|channel|subscribe|sub[-_ ]?link|scraped|source|mirror|aggregator)",
    re.IGNORECASE,
)

# Regional indicator symbols → flag emoji (kept so clients still show country)
_FLAG_RE = re.compile(r"[\U0001F1E0-\U0001F1FF]{2}")


def extract_flag(text: str) -> str:
    """Return the first flag emoji in text, if any."""
    m = _FLAG_RE.search(text or "")
    return m.group(0) if m else ""


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
    """
    Apply display name without breaking share-link parsing.

    - vmess: update JSON `ps` (what most clients show) then optional #fragment
    - other URI schemes: replace #fragment only
    """
    link = (raw_link or "").strip()
    if not link:
        return link
    if link.lower().startswith("vmess://"):
        return _rewrite_vmess_remark(link, remark)
    if "#" in link:
        base = link.rsplit("#", 1)[0]
    else:
        base = link
    return f"{base}#{quote(remark, safe='')}"


def _rewrite_vmess_remark(link: str, remark: str) -> str:
    payload = link[8:].split("#", 1)[0].strip()
    pad = (-len(payload)) % 4
    try:
        obj = json.loads(base64.b64decode(payload + ("=" * pad)).decode("utf-8", errors="ignore"))
    except Exception:
        # Fall back to fragment-only if JSON is unreadable
        base = link.rsplit("#", 1)[0]
        return f"{base}#{quote(remark, safe='')}"
    if not isinstance(obj, dict):
        base = link.rsplit("#", 1)[0]
        return f"{base}#{quote(remark, safe='')}"
    obj["ps"] = remark
    encoded = base64.b64encode(
        json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    # Keep a short ASCII-safe fragment too (some UIs only read #name)
    return f"vmess://{encoded}#{quote(remark, safe='')}"


def normalize_for_dedup(cfg_host: str, cfg_port: int, scheme: str, credential: str) -> str:
    return f"{scheme.lower()}|{cfg_host.lower()}|{cfg_port}|{credential}"


def strip_query_noise(link: str) -> str:
    """Best-effort normalize URI for comparison (does not alter published raw)."""
    try:
        p = urlparse(link)
        return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path, "", p.query, ""))
    except Exception:
        return link.strip()
