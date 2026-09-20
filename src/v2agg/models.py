from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any


ALLOWED_SCHEMES = ("vmess", "vless", "trojan", "ss", "ssr", "hysteria2", "hy2")


@dataclass
class ProxyConfig:
    """Normalized proxy share-link representation."""

    scheme: str
    raw: str
    host: str
    port: int
    uuid_or_password: str = ""
    remark: str = ""
    fingerprint: str = ""
    network: str = ""
    security: str = ""
    sni: str = ""
    path: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    # Runtime / health fields (not part of outbound identity)
    latency_ms: float | None = None
    throughput_mbps: float | None = None
    score: float = 0.0
    alive: bool = False
    fail_count: int = 0
    last_ok_ts: float | None = None
    last_test_ts: float | None = None
    first_seen_ts: float | None = None
    source_id: str = ""  # internal only — never published

    def ensure_fingerprint(self) -> str:
        if self.fingerprint:
            return self.fingerprint
        parts = [
            self.scheme.lower().strip(),
            self.host.lower().strip(),
            str(self.port),
            (self.uuid_or_password or "").strip(),
            (self.network or "").lower().strip(),
            (self.security or "").lower().strip(),
            (self.sni or "").lower().strip(),
            (self.path or "").strip(),
        ]
        digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
        self.fingerprint = digest[:32]
        return self.fingerprint

    def to_public_link(self, remark: str | None = None) -> str:
        """Return share link suitable for clients (no provenance)."""
        link = self.raw.strip()
        r = remark if remark is not None else self.remark
        if not r:
            return link
        # Replace / append fragment remark for URI-style schemes
        if "#" in link:
            base = link.rsplit("#", 1)[0]
            from urllib.parse import quote

            return f"{base}#{quote(r, safe='')}"
        return link

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProxyConfig:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


@dataclass
class SourceResult:
    source_id: str
    url: str
    ok: bool
    configs_found: int = 0
    error: str = ""
    elapsed_ms: float = 0.0


@dataclass
class RunMetrics:
    started_ts: float = 0.0
    finished_ts: float = 0.0
    fetched_sources_ok: int = 0
    fetched_sources_fail: int = 0
    raw_links: int = 0
    after_dedup: int = 0
    tested: int = 0
    alive: int = 0
    published: int = 0
    telegram_posted: int = 0
    resumed_from_checkpoint: bool = False
    source_results: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_HOST_RE = re.compile(r"^[A-Za-z0-9._\-:\[\]]+$")


def is_valid_host(host: str) -> bool:
    h = (host or "").strip()
    if not h or len(h) > 253:
        return False
    return bool(_HOST_RE.match(h))
