from __future__ import annotations

import ipaddress
from collections import Counter
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


def ipv4_prefix24(host: str) -> str | None:
    """Return 'a.b.c.0/24' for an IPv4 literal, else None (hostname / IPv6)."""
    text = (host or "").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return None
    if addr.version != 4:
        return None
    return str(ipaddress.IPv4Network(f"{addr}/24", strict=False))


def network_diversity_key(cfg: ProxyConfig) -> str:
    """IPv4 → /24; hostnames and IPv6 skip /24 and group by host key instead.

    Ranking stays offline: hostnames are not resolved (Actions IPs would not
    match Iranian paths anyway). Same hostname still shares one cap slot.
    """
    prefix = ipv4_prefix24(cfg.host)
    if prefix:
        return f"p24:{prefix}"
    return f"host:{(cfg.host or '').strip().lower()}"


def reality_pbk(cfg: ProxyConfig) -> str:
    extra = cfg.extra or {}
    pbk = extra.get("pbk") or extra.get("publicKey") or extra.get("public_key") or ""
    return str(pbk).strip()


def reality_pbk_sni_key(cfg: ProxyConfig) -> str | None:
    pbk = reality_pbk(cfg)
    if not pbk:
        return None
    extra = cfg.extra or {}
    sni = (cfg.sni or extra.get("sni") or extra.get("peer") or "").strip().lower()
    return f"{pbk}|{sni}"


def _best_sort_key(cfg: ProxyConfig) -> tuple[float, float, str]:
    lat = cfg.latency_ms if cfg.latency_ms is not None else 999_999.0
    return (-float(cfg.score or 0.0), lat, cfg.ensure_fingerprint())


def select_best_configs(
    alive: list[ProxyConfig],
    *,
    score_threshold: float,
    max_publish: int,
    max_per_prefix24: int = 2,
    max_per_reality_pbk: int = 2,
) -> list[ProxyConfig]:
    """Alive configs with score ≥ threshold, best-first, with diversity caps.

    Sort by score then latency, then greedily fill until ``max_publish`` while
    keeping at most ``max_per_prefix24`` per IPv4 /24 (or per hostname) and
    at most ``max_per_reality_pbk`` per Reality ``pbk`` and per ``(pbk, sni)``.
    Caps ≤ 0 disable that constraint. Mbps / score filters are unchanged.
    """
    ranked = sorted(
        (c for c in alive if c.alive and c.score >= score_threshold),
        key=_best_sort_key,
    )
    cap = max(0, int(max_publish))
    net_cap = int(max_per_prefix24)
    pbk_cap = int(max_per_reality_pbk)
    selected: list[ProxyConfig] = []
    net_counts: Counter[str] = Counter()
    pbk_counts: Counter[str] = Counter()
    pair_counts: Counter[str] = Counter()

    for cfg in ranked:
        if len(selected) >= cap:
            break
        net_key = network_diversity_key(cfg)
        if net_cap > 0 and net_counts[net_key] >= net_cap:
            continue
        pbk = reality_pbk(cfg)
        if pbk_cap > 0 and pbk and pbk_counts[pbk] >= pbk_cap:
            continue
        pair = reality_pbk_sni_key(cfg)
        if pbk_cap > 0 and pair and pair_counts[pair] >= pbk_cap:
            continue
        selected.append(cfg)
        net_counts[net_key] += 1
        if pbk:
            pbk_counts[pbk] += 1
        if pair:
            pair_counts[pair] += 1
    return selected
