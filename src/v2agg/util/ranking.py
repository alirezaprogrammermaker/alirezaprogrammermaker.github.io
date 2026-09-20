from __future__ import annotations

import ipaddress
from collections import Counter
from typing import Any, Iterable

from v2agg.models import ProxyConfig

HY2_SCHEMES = frozenset({"hysteria2", "hy2"})


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


def is_hy2(cfg: ProxyConfig) -> bool:
    return (cfg.scheme or "").lower() in HY2_SCHEMES


def is_reality(cfg: ProxyConfig) -> bool:
    if (cfg.security or "").lower() == "reality":
        return True
    return bool(reality_pbk(cfg))


def config_sni(cfg: ProxyConfig) -> str:
    extra = cfg.extra or {}
    return (cfg.sni or extra.get("sni") or extra.get("peer") or "").strip().lower()


def sni_matches_denylist(sni: str, denylist: Iterable[Any]) -> bool:
    needle = (sni or "").strip().lower().rstrip(".")
    if not needle:
        return False
    for raw in denylist:
        listed = str(raw or "").strip().lower().rstrip(".")
        if not listed:
            continue
        if needle == listed or needle.endswith("." + listed):
            return True
    return False


def host_in_cidrs(host: str, cidrs: Iterable[Any]) -> bool:
    text = (host or "").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return False
    for raw in cidrs:
        try:
            net = ipaddress.ip_network(str(raw).strip(), strict=False)
        except ValueError:
            continue
        if addr in net:
            return True
    return False


def protocol_score_bonus(cfg: ProxyConfig, settings: dict[str, Any] | None) -> float:
    """Additive ranking bonus from ``testing.protocol_score_bonus`` (e.g. hysteria2: 15)."""
    t = (settings or {}).get("testing") or {}
    bonus_map = t.get("protocol_score_bonus") or {}
    if not isinstance(bonus_map, dict):
        return 0.0
    scheme = (cfg.scheme or "").lower()
    if scheme in HY2_SCHEMES:
        val = bonus_map.get("hysteria2", bonus_map.get("hy2", 0))
        try:
            return float(val or 0)
        except (TypeError, ValueError):
            return 0.0
    if scheme not in bonus_map:
        return 0.0
    try:
        return float(bonus_map.get(scheme) or 0)
    except (TypeError, ValueError):
        return 0.0


def _pool_popularity(alive: Iterable[ProxyConfig]) -> tuple[Counter[str], Counter[str]]:
    eligible = [c for c in alive if c.alive]
    pbk_counts: Counter[str] = Counter(reality_pbk(c) for c in eligible if reality_pbk(c))
    sni_counts: Counter[str] = Counter(
        config_sni(c) for c in eligible if is_reality(c) and config_sni(c)
    )
    return pbk_counts, sni_counts


def effective_score(
    cfg: ProxyConfig,
    settings: dict[str, Any] | None = None,
    *,
    pbk_counts: Counter[str] | None = None,
    sni_counts: Counter[str] | None = None,
    apply_best_penalties: bool = True,
) -> float:
    """Ranking score for ``best`` / ``best-hy2``. Does not mutate ``cfg.score``.

    Stored scores stay the latency+throughput blend and ``all`` is unchanged.
    ``best`` adds a Hysteria2 bonus and (optionally) Reality burned-pattern
    penalties so mass-cloned yahoo.com / Softlayer clusters lose to hy2 and
    uncommon-SNI Reality when alternatives exist.
    """
    score = float(cfg.score or 0.0)
    score += protocol_score_bonus(cfg, settings)
    if not apply_best_penalties or not is_reality(cfg):
        return score
    pipe = (settings or {}).get("pipeline") or {}
    sni = config_sni(cfg)
    if sni_matches_denylist(sni, pipe.get("reality_burned_sni") or []):
        try:
            score -= float(pipe.get("reality_burned_sni_penalty") or 0)
        except (TypeError, ValueError):
            pass
    if host_in_cidrs(cfg.host, pipe.get("reality_burned_prefix24") or []):
        try:
            score -= float(pipe.get("reality_burned_prefix_penalty") or 0)
        except (TypeError, ValueError):
            pass
    pbk = reality_pbk(cfg)
    try:
        min_share = int(pipe.get("reality_shared_pbk_min") or 0)
    except (TypeError, ValueError):
        min_share = 0
    if pbk and pbk_counts is not None and min_share > 0 and pbk_counts.get(pbk, 0) >= min_share:
        try:
            score -= float(pipe.get("reality_shared_pbk_penalty") or 0)
        except (TypeError, ValueError):
            pass
    try:
        uncommon_max = int(pipe.get("reality_uncommon_sni_max") or 0)
    except (TypeError, ValueError):
        uncommon_max = 0
    if sni and sni_counts is not None and uncommon_max > 0:
        n = sni_counts.get(sni, 0)
        if 0 < n <= uncommon_max:
            try:
                score += float(pipe.get("reality_uncommon_sni_bonus") or 0)
            except (TypeError, ValueError):
                pass
    return score


def _score_sort_key(cfg: ProxyConfig, score: float) -> tuple[float, int, float, str]:
    """Higher effective score first; hy2 wins ties, then lower latency."""
    lat = cfg.latency_ms if cfg.latency_ms is not None else 999_999.0
    return (-float(score), 0 if is_hy2(cfg) else 1, lat, cfg.ensure_fingerprint())


def select_best_configs(
    alive: list[ProxyConfig],
    *,
    score_threshold: float,
    max_publish: int,
    max_per_prefix24: int = 2,
    max_per_reality_pbk: int = 2,
    settings: dict[str, Any] | None = None,
) -> list[ProxyConfig]:
    """Pick ``best``: score-first, then diversity backfill, always with caps.

    Ranking uses ``effective_score`` (protocol bonus + Reality burned-pattern
    penalties) for both the threshold and sort order. Stored ``cfg.score`` and
    ``all`` are not modified. Hy2 is preferred; remaining slots prefer Reality
    with uncommon SNI / non-burned prefixes over yahoo.com Softlayer clones.

    Phase 1: alive configs with *effective* score ≥ threshold, sorted best-first,
    greedily filled while keeping at most ``max_per_prefix24`` per IPv4 /24
    (or per hostname) and ``max_per_reality_pbk`` per Reality ``pbk`` /
    ``(pbk, sni)``. Caps ≤ 0 disable that constraint.

    Phase 2: if still under ``max_publish``, fill remaining slots from lower-score
    *alive* survivors that add a **new** /24 or **new** pbk (prefer path
    diversity over raw Mbps). Caps still apply — a 169.40.42.0/24 Reality
    cluster cannot occupy more than two slots.
    """
    cap = max(0, int(max_publish))
    net_cap = int(max_per_prefix24)
    pbk_cap = int(max_per_reality_pbk)
    selected: list[ProxyConfig] = []
    selected_fps: set[str] = set()
    net_counts: Counter[str] = Counter()
    pbk_counts: Counter[str] = Counter()
    pair_counts: Counter[str] = Counter()
    pbk_pop, sni_pop = _pool_popularity(alive)
    score_of: dict[str, float] = {
        c.ensure_fingerprint(): effective_score(
            c,
            settings,
            pbk_counts=pbk_pop,
            sni_counts=sni_pop,
            apply_best_penalties=True,
        )
        for c in alive
        if c.alive
    }

    def _sort_key(cfg: ProxyConfig) -> tuple[float, int, float, str]:
        return _score_sort_key(cfg, score_of.get(cfg.ensure_fingerprint(), float(cfg.score or 0.0)))

    def _fits(cfg: ProxyConfig, *, require_new: bool) -> bool:
        net_key = network_diversity_key(cfg)
        pbk = reality_pbk(cfg)
        pair = reality_pbk_sni_key(cfg)
        if net_cap > 0 and net_counts[net_key] >= net_cap:
            return False
        if pbk_cap > 0 and pbk and pbk_counts[pbk] >= pbk_cap:
            return False
        if pbk_cap > 0 and pair and pair_counts[pair] >= pbk_cap:
            return False
        if require_new:
            new_net = net_counts[net_key] == 0
            new_pbk = bool(pbk) and pbk_counts[pbk] == 0
            if not (new_net or new_pbk):
                return False
        return True

    def _add(cfg: ProxyConfig) -> None:
        fp = cfg.ensure_fingerprint()
        if fp in selected_fps:
            return
        selected.append(cfg)
        selected_fps.add(fp)
        net_counts[network_diversity_key(cfg)] += 1
        pbk = reality_pbk(cfg)
        if pbk:
            pbk_counts[pbk] += 1
        pair = reality_pbk_sni_key(cfg)
        if pair:
            pair_counts[pair] += 1

    high = sorted(
        (c for c in alive if c.alive and score_of.get(c.ensure_fingerprint(), 0.0) >= score_threshold),
        key=_sort_key,
    )
    for cfg in high:
        if len(selected) >= cap:
            break
        if _fits(cfg, require_new=False):
            _add(cfg)

    if len(selected) < cap:
        rest = sorted(
            (c for c in alive if c.alive and c.ensure_fingerprint() not in selected_fps),
            key=_sort_key,
        )
        for cfg in rest:
            if len(selected) >= cap:
                break
            if _fits(cfg, require_new=True):
                _add(cfg)
    return selected


def select_best_hy2(
    alive: list[ProxyConfig],
    *,
    max_publish: int = 40,
    max_per_prefix24: int = 2,
    settings: dict[str, Any] | None = None,
) -> list[ProxyConfig]:
    """Alive hysteria2/hy2 only, score-sorted, with /24 diversity when the host is an IP."""
    cap = max(0, int(max_publish))
    net_cap = int(max_per_prefix24)
    pool = [c for c in alive if c.alive and is_hy2(c)]
    ranked = sorted(
        pool,
        key=lambda c: _score_sort_key(
            c,
            effective_score(c, settings, apply_best_penalties=False),
        ),
    )
    selected: list[ProxyConfig] = []
    net_counts: Counter[str] = Counter()
    for cfg in ranked:
        if len(selected) >= cap:
            break
        prefix = ipv4_prefix24(cfg.host)
        if prefix and net_cap > 0:
            net_key = f"p24:{prefix}"
            if net_counts[net_key] >= net_cap:
                continue
            net_counts[net_key] += 1
        selected.append(cfg)
    return selected
