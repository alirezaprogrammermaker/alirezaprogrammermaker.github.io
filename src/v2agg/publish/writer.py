from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from v2agg.models import ProxyConfig
from v2agg.parse.normalize import rewrite_remark
from v2agg.util.encoding import encode_subscription_base64
from v2agg.util.logging import get_logger
from v2agg.util.ranking import remark_with_latency, select_best_configs

logger = get_logger(__name__)


class Publisher:
    """Write lean subscription files for GitHub Pages (no provenance)."""

    def __init__(self, settings: dict[str, Any]) -> None:
        pub = settings.get("publish") or {}
        self.output_dir = Path(pub.get("output_dir") or "subs")
        self.all_file = pub.get("all_file") or "all.txt"
        self.all_b64 = pub.get("all_base64_file") or "all.base64"
        self.best_file = pub.get("best_file") or "best.txt"
        self.best_b64 = pub.get("best_base64_file") or "best.base64"
        self.by_proto = pub.get("by_protocol_dir") or "by-protocol"
        self.sanitize = bool(pub.get("sanitize_remarks", True))
        self.remark_prefix = pub.get("remark_prefix") or "⚡"
        pipe = settings.get("pipeline") or {}
        # Defaults must match config/settings.yaml so a missed YAML key still
        # keeps `best` a strict Top-N subset of `all`.
        self.max_healthy = int(pipe.get("max_healthy_publish", 150))
        self.best_threshold = float(pipe.get("best_score_threshold", 70))
        self.best_max_publish = int(pipe.get("best_max_publish", 30))

    def _public_links(self, configs: list[ProxyConfig]) -> list[str]:
        links: list[str] = []
        for i, cfg in enumerate(configs, start=1):
            if self.sanitize:
                remark = remark_with_latency(cfg, self.remark_prefix, i)
            else:
                remark = cfg.remark or f"{self.remark_prefix}{i}"
            links.append(rewrite_remark(cfg.raw, remark))
        return links

    def publish(self, healthy: list[ProxyConfig]) -> dict[str, Path]:
        alive = [c for c in healthy if c.alive]
        alive.sort(key=lambda c: (-c.score, c.latency_ms if c.latency_ms is not None else 99999))
        alive = alive[: self.max_healthy]
        best = select_best_configs(
            alive,
            score_threshold=self.best_threshold,
            max_publish=self.best_max_publish,
        )

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

        # index for humans (no source mentions)
        index = self.output_dir / "index.json"
        index.write_text(
            __import__("json").dumps(
                {
                    "count_all": len(all_links),
                    "count_best": len(best_links),
                    "files": {
                        "all": self.all_file,
                        "all_base64": self.all_b64,
                        "best": self.best_file,
                        "best_base64": self.best_b64,
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        paths["index"] = index

        by_scheme: dict[str, list[ProxyConfig]] = defaultdict(list)
        for c in alive:
            by_scheme[c.scheme].append(c)
        for scheme, items in by_scheme.items():
            links = self._public_links(items)
            p = by_dir / f"{scheme}.txt"
            p.write_text("\n".join(links) + ("\n" if links else ""), encoding="utf-8")
            pb = by_dir / f"{scheme}.base64"
            pb.write_text(encode_subscription_base64(links), encoding="utf-8")
            paths[f"proto_{scheme}"] = p

        # Keep Pages root friendly
        readme = self.output_dir / "README.md"
        readme.write_text(
            "# Subscriptions\n\n"
            "Add one of these URLs as a subscription in v2rayNG / Clash-compatible clients "
            "that support V2Ray share links.\n\n"
            f"- All (base64): `{self.all_b64}`\n"
            f"- Best (base64): `{self.best_b64}`\n"
            f"- All (plain): `{self.all_file}`\n"
            f"- Best (plain): `{self.best_file}`\n",
            encoding="utf-8",
        )
        paths["readme"] = readme

        logger.info("published all=%d best=%d dir=%s", len(all_links), len(best_links), self.output_dir)
        return paths
