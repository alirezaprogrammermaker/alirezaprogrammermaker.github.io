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
    """Public remark: ping first (optional Mbps) so clients can sort. No provenance."""
    bits: list[str] = []
    if cfg.alive and cfg.latency_ms is not None:
        bits.append(f"{int(round(cfg.latency_ms))}ms")
    if cfg.alive and cfg.throughput_mbps is not None and cfg.throughput_mbps > 0:
        mbps = cfg.throughput_mbps
        bits.append(f"{mbps:.0f}M" if mbps >= 10 else f"{mbps:.1f}M")
    core = "-".join(bits)
    label = f"{prefix}{core}-{index}" if core else f"{prefix}{index}"
    return label[:40]


def select_best_configs(
    alive: list[ProxyConfig],
    *,
    score_threshold: float,
    max_publish: int,
) -> list[ProxyConfig]:
    """Alive configs with score ≥ threshold, best-first, hard Top-N cap."""
    ranked = sorted(
        (c for c in alive if c.alive and c.score >= score_threshold),
        key=lambda c: (-float(c.score or 0.0), c.latency_ms if c.latency_ms is not None else 999_999.0),
    )
    cap = max(0, int(max_publish))
    return ranked[:cap]
