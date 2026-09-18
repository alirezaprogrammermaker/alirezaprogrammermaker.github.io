from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from v2agg.models import ProxyConfig
from v2agg.parse.links import parse_link
from v2agg.parse.normalize import rewrite_remark
from v2agg.util.encoding import encode_subscription_base64
from v2agg.util.logging import get_logger
from v2agg.util.ranking import (
    USECASE_DOWNLOAD,
    USECASE_GAME,
    USECASE_WEB,
    classify_usecase,
    remark_with_latency,
    sort_by_latency,
)

logger = get_logger(__name__)

_MS_RE = re.compile(r"(\d+)\s*ms", re.IGNORECASE)


class Publisher:
    """Write lean subscription files for GitHub Pages (no provenance)."""

    def __init__(self, settings: dict[str, Any]) -> None:
        pub = settings.get("publish") or {}
        self.settings = settings
        self.output_dir = Path(pub.get("output_dir") or "subs")
        self.all_file = pub.get("all_file") or "all.txt"
        self.all_b64 = pub.get("all_base64_file") or "all.base64"
        self.best_file = pub.get("best_file") or "best.txt"
        self.best_b64 = pub.get("best_base64_file") or "best.base64"
        self.by_proto = pub.get("by_protocol_dir") or "by-protocol"
        self.sanitize = bool(pub.get("sanitize_remarks", True))
        self.remark_prefix = pub.get("remark_prefix") or "⚡"
        self.max_healthy = int((settings.get("pipeline") or {}).get("max_healthy_publish", 200))
        self.best_threshold = float((settings.get("pipeline") or {}).get("best_score_threshold", 40))
        self.pages_base_url = ((settings.get("app") or {}).get("pages_base_url") or "").rstrip("/")

    def _public_links(self, configs: list[ProxyConfig]) -> list[str]:
        links: list[str] = []
        for i, cfg in enumerate(configs, start=1):
            if self.sanitize:
                remark = remark_with_latency(cfg, self.remark_prefix, i, settings=self.settings)
            else:
                remark = cfg.remark or f"{self.remark_prefix}{i}"
            links.append(rewrite_remark(cfg.raw, remark))
        return links

    def load_public_configs(self) -> list[ProxyConfig]:
        """Parse current subs/all.txt into configs (best-effort latency/usecase from remark)."""
        path = self.output_dir / self.all_file
        if not path.is_file():
            return []
        text = path.read_text(encoding="utf-8", errors="ignore")
        out: list[ProxyConfig] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or "://" not in line:
                continue
            cfg = parse_link(line)
            if cfg is None:
                continue
            remark = unquote(line.rsplit("#", 1)[-1]) if "#" in line else (cfg.remark or "")
            cfg.remark = remark
            m = _MS_RE.search(remark)
            if m:
                cfg.latency_ms = float(m.group(1))
                cfg.alive = True
                cfg.score = max(cfg.score, 50.0)
            if USECASE_GAME in remark:
                cfg.usecase = USECASE_GAME
            elif USECASE_WEB in remark:
                cfg.usecase = USECASE_WEB
            elif USECASE_DOWNLOAD in remark:
                cfg.usecase = USECASE_DOWNLOAD
            elif cfg.alive:
                cfg.usecase = classify_usecase(cfg, self.settings)
            out.append(cfg)
        return out

    def needs_remark_retag(self) -> bool:
        """True if public list still uses broken middle-dot remarks or vmess ps mismatch."""
        path = self.output_dir / self.all_file
        if not path.is_file() or path.stat().st_size == 0:
            return False
        text = path.read_text(encoding="utf-8", errors="ignore")
        # Middle-dot separator broke some clients after usecase labels
        if "·" in text or "%C2%B7" in text:
            return True
        return False

    def publish(self, healthy: list[ProxyConfig]) -> dict[str, Path]:
        alive = [c for c in healthy if c.alive]
        # Lowest ping first (user-facing list order)
        alive = sort_by_latency(alive)[: self.max_healthy]
        best = [c for c in alive if c.score >= self.best_threshold][: max(20, self.max_healthy // 4)]
        # best already latency-sorted as a subset of alive order; re-sort for safety
        best = sort_by_latency(best)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        by_dir = self.output_dir / self.by_proto
        by_dir.mkdir(parents=True, exist_ok=True)

        all_links = self._public_links(alive)
        best_links = self._public_links(best)

        paths: dict[str, Path] = {}
        paths["all"] = self.output_dir / self.all_file
        paths["all"].write_text("\n".join(all_links) + ("\n" if all_links else ""), encoding="utf-8")
        paths["all_b64"] = self.output_dir / self.all_b64
        paths["all_b64"].write_text(encode_subscription_base64(all_links), encoding="utf-8")
        paths["best"] = self.output_dir / self.best_file
        paths["best"].write_text("\n".join(best_links) + ("\n" if best_links else ""), encoding="utf-8")
        paths["best_b64"] = self.output_dir / self.best_b64
        paths["best_b64"].write_text(encode_subscription_base64(best_links), encoding="utf-8")

        pages_base = self.pages_base_url
        files = {
            "all": self.all_file,
            "all_base64": self.all_b64,
            "best": self.best_file,
            "best_base64": self.best_b64,
        }
        payload: dict[str, Any] = {
            "count_all": len(all_links),
            "count_best": len(best_links),
            "sort": "latency_asc",
            "files": files,
        }
        if pages_base:
            payload["urls"] = {
                "all": f"{pages_base}/subs/{self.all_file}",
                "all_base64": f"{pages_base}/subs/{self.all_b64}",
                "best": f"{pages_base}/subs/{self.best_file}",
                "best_base64": f"{pages_base}/subs/{self.best_b64}",
            }
        index = self.output_dir / "index.json"
        index.write_text(__import__("json").dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        paths["index"] = index

        by_scheme: dict[str, list[ProxyConfig]] = defaultdict(list)
        for c in alive:
            by_scheme[c.scheme].append(c)
        for scheme, items in by_scheme.items():
            ordered = sort_by_latency(items)
            links = self._public_links(ordered)
            p = by_dir / f"{scheme}.txt"
            p.write_text("\n".join(links) + ("\n" if links else ""), encoding="utf-8")
            pb = by_dir / f"{scheme}.base64"
            pb.write_text(encode_subscription_base64(links), encoding="utf-8")
            paths[f"proto_{scheme}"] = p

        readme = self.output_dir / "README.md"
        readme.write_text(
            "# Subscriptions\n\n"
            "Lists are sorted by **lowest ping first**. Dead servers are removed on each refresh.\n\n"
            "Add one of these URLs as a subscription in v2rayNG / Clash-compatible clients "
            "that support V2Ray share links.\n\n"
            + (
                f"- All (base64): `{self.pages_base_url}/subs/{self.all_b64}`\n"
                f"- Best (base64): `{self.pages_base_url}/subs/{self.best_b64}`\n"
                f"- All (plain): `{self.pages_base_url}/subs/{self.all_file}`\n"
                f"- Best (plain): `{self.pages_base_url}/subs/{self.best_file}`\n"
                if self.pages_base_url
                else (
                    f"- All (base64): `{self.all_b64}`\n"
                    f"- Best (base64): `{self.best_b64}`\n"
                    f"- All (plain): `{self.all_file}`\n"
                    f"- Best (plain): `{self.best_file}`\n"
                )
            ),
            encoding="utf-8",
        )
        paths["readme"] = readme

        logger.info("published all=%d best=%d dir=%s sort=latency", len(all_links), len(best_links), self.output_dir)
        return paths
