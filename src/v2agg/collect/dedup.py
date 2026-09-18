from __future__ import annotations

import time
from typing import Iterable

from v2agg.models import ProxyConfig
from v2agg.util.logging import get_logger

logger = get_logger(__name__)


def deduplicate(configs: Iterable[ProxyConfig]) -> list[ProxyConfig]:
    """Dedup by outbound fingerprint; keep first occurrence, merge fail metadata."""
    by_fp: dict[str, ProxyConfig] = {}
    for cfg in configs:
        fp = cfg.ensure_fingerprint()
        existing = by_fp.get(fp)
        if existing is None:
            if cfg.first_seen_ts is None:
                cfg.first_seen_ts = time.time()
            by_fp[fp] = cfg
            continue
        # Prefer longer raw / richer remark internally but public remark sanitized later
        if len(cfg.raw) > len(existing.raw):
            cfg.fail_count = max(cfg.fail_count, existing.fail_count)
            cfg.first_seen_ts = existing.first_seen_ts or cfg.first_seen_ts
            cfg.last_ok_ts = existing.last_ok_ts or cfg.last_ok_ts
            by_fp[fp] = cfg
        else:
            existing.fail_count = max(existing.fail_count, cfg.fail_count)
    out = list(by_fp.values())
    logger.info("dedup input_unique=%d", len(out))
    return out


def evict_stale(
    configs: Iterable[ProxyConfig],
    *,
    max_fail_count: int = 5,
    max_age_hours: float = 72,
    now: float | None = None,
) -> list[ProxyConfig]:
    now_ts = now if now is not None else time.time()
    max_age_sec = max_age_hours * 3600
    kept: list[ProxyConfig] = []
    for cfg in configs:
        if cfg.fail_count >= max_fail_count:
            continue
        if cfg.first_seen_ts and (now_ts - cfg.first_seen_ts) > max_age_sec and not cfg.alive:
            # Drop long-dead never-revived entries
            if cfg.last_ok_ts is None or (now_ts - cfg.last_ok_ts) > max_age_sec:
                continue
        kept.append(cfg)
    return kept
