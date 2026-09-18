from __future__ import annotations

from typing import Any, Iterable

from v2agg.models import ProxyConfig

# Real use-case tags derived only from measured probe metrics (never random).
USECASE_GAME = "بازی"
USECASE_WEB = "وب"
USECASE_DOWNLOAD = "دانلود"


def latency_sort_key(cfg: ProxyConfig) -> tuple[float, float, str]:
    """Lowest ping first; score as tie-breaker; fingerprint for stability."""
    lat = cfg.latency_ms if cfg.latency_ms is not None and cfg.latency_ms >= 0 else 999_999.0
    return (lat, -float(cfg.score or 0.0), cfg.ensure_fingerprint())


def sort_by_latency(configs: Iterable[ProxyConfig]) -> list[ProxyConfig]:
    return sorted(configs, key=latency_sort_key)


def classify_usecase(cfg: ProxyConfig, settings: dict[str, Any] | None = None) -> str:
    """
    Assign بازی / وب / دانلود from real probe numbers only.

    - بازی: low latency (interactive / gaming)
    - وب: medium latency (browsing)
    - دانلود: higher latency and/or solid measured throughput (bulk transfer)
    """
    pub = (settings or {}).get("publish") or {}
    uc = pub.get("usecase") or {}
    game_max = float(uc.get("game_max_ms", 150))
    web_max = float(uc.get("web_max_ms", 500))
    download_min_kbps = float(uc.get("download_min_kbps", 400))

    if not cfg.alive or cfg.latency_ms is None:
        return ""

    lat = float(cfg.latency_ms)
    thr = float(cfg.throughput_kbps or 0.0)

    # Excellent ping → interactive / gaming (never fake this from throughput alone)
    if lat <= game_max:
        return USECASE_GAME
    # Measured strong pipe → download, even at mid latency
    if thr >= download_min_kbps:
        return USECASE_DOWNLOAD
    # Mid ping without a strong pipe → browsing
    if lat <= web_max:
        return USECASE_WEB
    # Higher ping still usable for bulk transfer
    return USECASE_DOWNLOAD


def remark_with_latency(
    cfg: ProxyConfig,
    prefix: str,
    index: int,
    *,
    settings: dict[str, Any] | None = None,
) -> str:
    """
    Public remark: optional country flag + ping + real use-case tag.

    Uses ASCII hyphen (not middle-dot) so fragile clients still parse the URI.
    Example: 🇺🇸⚡85ms-بازی-1
    """
    from v2agg.parse.normalize import extract_flag

    flag = extract_flag(cfg.remark or "")
    if cfg.latency_ms is not None and cfg.alive:
        ms = int(round(cfg.latency_ms))
        tag = cfg.usecase or classify_usecase(cfg, settings)
        head = f"{flag}{prefix}{ms}ms" if flag else f"{prefix}{ms}ms"
        if tag:
            return f"{head}-{tag}-{index}"[:48]
        return f"{head}-{index}"[:40]
    bare = f"{flag}{prefix}{index}" if flag else f"{prefix}{index}"
    return bare[:32]
