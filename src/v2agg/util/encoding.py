from __future__ import annotations

import base64
import re
from typing import Iterable


_B64_RE = re.compile(r"^[A-Za-z0-9+/=\s]+$")


def try_b64_decode(text: str) -> str | None:
    """Decode base64 subscription payloads; return None if not base64-like."""
    raw = (text or "").strip()
    if not raw:
        return None
    # Subscriptions may be wrapped without padding
    compact = re.sub(r"\s+", "", raw)
    if len(compact) < 16 or not _B64_RE.match(compact):
        return None
    pad = (-len(compact)) % 4
    try:
        decoded = base64.b64decode(compact + ("=" * pad), validate=False)
        out = decoded.decode("utf-8", errors="ignore")
        if "://" in out or "vmess://" in out.lower() or "vless://" in out.lower():
            return out
        # Some subs are newline-separated base64 lines of links already decoded as text
        if out.count("\n") >= 1 and any(
            line.strip().lower().startswith(("vmess://", "vless://", "trojan://", "ss://"))
            for line in out.splitlines()
        ):
            return out
    except Exception:
        return None
    return None


def decode_subscription_body(body: str) -> str:
    """Return plaintext share-link body (decode base64 when needed)."""
    text = body or ""
    # Already looks like share links
    if re.search(r"(?im)^(vmess|vless|trojan|ss|ssr|hysteria2|hy2)://", text):
        return text
    decoded = try_b64_decode(text)
    return decoded if decoded is not None else text


def encode_subscription_base64(links: Iterable[str]) -> str:
    joined = "\n".join(link.strip() for link in links if link and link.strip())
    return base64.b64encode(joined.encode("utf-8")).decode("ascii")
