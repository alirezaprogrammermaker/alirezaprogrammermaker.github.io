from __future__ import annotations

from typing import Iterable

from v2agg.models import ProxyConfig


def latency_sort_key(cfg: ProxyConfig) -> tuple[float, float, str]:
    """Lowest ping first; score as tie-breaker; fingerprint for stability."""
    lat = cfg.latency_ms if cfg.latency_ms is not None and cfg.latency_ms >= 0 else 999_999.0
    return (lat, -float(cfg.score or 0.0), cfg.ensure_fingerprint())


def sort_by_latency(configs: Iterable[ProxyConfig]) -> list[ProxyConfig]:
    return sorted(configs, key=latency_sort_key)


def remark_with_latency(cfg: ProxyConfig, prefix: str, index: int) -> str:
    """Public remark: ping first so client UIs show speed order clearly."""
    if cfg.latency_ms is not None and cfg.alive:
        ms = int(round(cfg.latency_ms))
        return f"{prefix}{ms}ms-{index}"[:40]
    return f"{prefix}{index}"[:32]
