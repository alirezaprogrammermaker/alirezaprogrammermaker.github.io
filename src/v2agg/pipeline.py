from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2agg.collect.dedup import deduplicate, evict_stale
from v2agg.collect.fetcher import Fetcher, load_sources
from v2agg.models import ProxyConfig, RunMetrics
from v2agg.publish.writer import Publisher
from v2agg.state.store import StateStore
from v2agg.telegram.client import TelegramClient
from v2agg.test.live import LiveTester
from v2agg.util.config import load_yaml
from v2agg.util.logging import get_logger, setup_logging
from v2agg.util.timefmt import format_activity_label

logger = get_logger(__name__)


class Pipeline:
    def __init__(
        self,
        settings_path: str | Path,
        sources_path: str | Path,
        *,
        mode: str = "refresh",
        dry_run_telegram: bool = False,
    ) -> None:
        self.settings = load_yaml(settings_path)
        self.sources_cfg = load_yaml(sources_path)
        log_cfg = self.settings.get("logging") or {}
        setup_logging(log_cfg.get("level", "INFO"), bool(log_cfg.get("json", False)))
        if dry_run_telegram:
            self.settings.setdefault("telegram", {})["dry_run"] = True

        self.mode = mode  # refresh | nightly | publish-only
        self.store = StateStore(self.settings)
        self.fetcher = Fetcher(self.settings)
        self.tester = LiveTester(self.settings)
        self.publisher = Publisher(self.settings)
        self.telegram = TelegramClient(self.settings)

        pipe = self.settings.get("pipeline") or {}
        self.max_runtime = float(pipe.get("max_runtime_sec", 19800))
        self.checkpoint_interval = float(pipe.get("checkpoint_interval_sec", 120))
        self.max_test = int(pipe.get("max_configs_to_test_per_run", 800))
        self.max_tg = int(pipe.get("max_telegram_post_per_run", 15))
        self.best_threshold = float(pipe.get("best_score_threshold", 40))
        self._deadline = time.monotonic() + self.max_runtime
        self._last_checkpoint = time.monotonic()

    def _should_stop(self) -> bool:
        return time.monotonic() >= self._deadline

    def _maybe_checkpoint(
        self,
        configs: list[ProxyConfig],
        tested: set[str],
        posted: set[str],
        metrics: RunMetrics,
        phase: str,
        force: bool = False,
    ) -> None:
        if force or (time.monotonic() - self._last_checkpoint) >= self.checkpoint_interval:
            self.store.save_checkpoint(
                configs=configs,
                tested_fingerprints=tested,
                posted_fingerprints=posted,
                metrics=metrics,
                phase=phase,
            )
            self._last_checkpoint = time.monotonic()

    def run(self) -> RunMetrics:
        metrics = RunMetrics(started_ts=time.time())
        tested: set[str] = set()
        posted: set[str] = set()
        configs: list[ProxyConfig] = []

        ckpt = self.store.load_checkpoint()
        if ckpt:
            metrics.resumed_from_checkpoint = True
            tested = set(ckpt.get("tested_fingerprints") or [])
            posted = set(ckpt.get("posted_fingerprints") or [])
            configs = [ProxyConfig.from_dict(x) for x in (ckpt.get("configs") or []) if isinstance(x, dict)]
            prev = ckpt.get("metrics") or {}
            metrics.raw_links = int(prev.get("raw_links") or 0)
            metrics.after_dedup = int(prev.get("after_dedup") or 0)
            metrics.fetched_sources_ok = int(prev.get("fetched_sources_ok") or 0)
            metrics.fetched_sources_fail = int(prev.get("fetched_sources_fail") or 0)
            metrics.source_results = list(prev.get("source_results") or [])
            logger.info("resuming checkpoint configs=%d tested=%d", len(configs), len(tested))

        if not configs and self.mode != "publish-only":
            sources = load_sources(self.sources_cfg)
            collected, source_results = self.fetcher.collect(sources)
            metrics.fetched_sources_ok = sum(1 for s in source_results if s.ok)
            metrics.fetched_sources_fail = sum(1 for s in source_results if not s.ok)
            # Public metrics: only id + ok/fail counts — no scrape method details
            metrics.source_results = [
                {
                    "id": s.source_id,
                    "ok": s.ok,
                    "configs_found": s.configs_found,
                    "elapsed_ms": round(s.elapsed_ms, 1),
                    "error": s.error,
                }
                for s in source_results
            ]
            metrics.raw_links = len(collected)
            prev_healthy = self.store.load_healthy()
            merged = deduplicate(list(collected) + prev_healthy)
            val = self.settings.get("validation") or {}
            merged = evict_stale(
                merged,
                max_fail_count=int(val.get("max_fail_count", 5)),
                max_age_hours=float(val.get("max_age_hours", 72)),
            )
            metrics.after_dedup = len(merged)
            # Cap work for this run; remaining wait for next cron via checkpoint
            configs = merged[: self.max_test]
            self._maybe_checkpoint(configs, tested, posted, metrics, "collected", force=True)

        if self.mode != "publish-only" and configs:
            def on_progress(done: int, total: int) -> None:
                logger.info("progress tested=%d/%d", done, total)
                self._maybe_checkpoint(configs, tested, posted, metrics, "testing")

            # Mark fingerprints we're about to skip as already tested
            results = self.tester.test_many(
                configs,
                should_stop=self._should_stop,
                on_progress=on_progress,
                skip_fingerprints=tested,
            )
            # Update tested set from results that have last_test_ts
            for c in results:
                if c.last_test_ts:
                    tested.add(c.ensure_fingerprint())
            configs = results
            metrics.tested = len(tested)
            metrics.alive = sum(1 for c in configs if c.alive)
            self._maybe_checkpoint(configs, tested, posted, metrics, "tested", force=True)

            if self._should_stop():
                logger.warning("runtime budget exhausted — checkpoint saved; next cron will resume")
                metrics.finished_ts = time.time()
                self.store.save_metrics(metrics)
                return metrics

        healthy = [c for c in configs if c.alive]
        # Merge with prior healthy that weren't in this batch
        prior = {c.ensure_fingerprint(): c for c in self.store.load_healthy()}
        for c in healthy:
            prior[c.ensure_fingerprint()] = c
        # Drop dead from prior if retested dead
        for c in configs:
            if not c.alive and c.ensure_fingerprint() in prior and c.last_test_ts:
                prior.pop(c.ensure_fingerprint(), None)
        healthy_all = sorted(prior.values(), key=lambda x: (-x.score, x.latency_ms or 99999))
        self.store.save_healthy(healthy_all)

        paths = self.publisher.publish(healthy_all)
        metrics.published = sum(1 for c in healthy_all if c.alive)
        logger.info("publish paths=%s", list(paths.keys()))

        # Telegram: post best new configs
        if self.mode in {"refresh", "nightly"}:
            candidates = [
                c
                for c in healthy_all
                if c.alive and c.score >= self.best_threshold and c.ensure_fingerprint() not in posted
            ]
            candidates.sort(key=lambda c: (-c.score, c.latency_ms or 99999))
            posted_count = 0
            for i, cfg in enumerate(candidates[: self.max_tg], start=1):
                if self._should_stop():
                    break
                try:
                    if self.telegram.post_config(cfg, i):
                        posted.add(cfg.ensure_fingerprint())
                        posted_count += 1
                except Exception as exc:
                    logger.warning("telegram post failed: %s", type(exc).__name__)
            metrics.telegram_posted = posted_count
            self._bump_daily(posted=posted_count, alive=metrics.alive, tested=metrics.tested)

            try:
                self.telegram.update_description(
                    last_activity=format_activity_label(),
                    alive_count=metrics.published or len(healthy_all),
                )
            except Exception as exc:
                logger.warning("telegram description update failed: %s", type(exc).__name__)

        if self.mode == "nightly":
            daily = self.store.load_daily_counter()
            try:
                self.telegram.post_nightly_report(metrics, int(daily.get("posted") or 0))
            except Exception as exc:
                logger.warning("nightly report failed: %s", type(exc).__name__)

        # Completed full cycle — clear checkpoint so next run starts fresh collect
        if not self._should_stop():
            self.store.clear_checkpoint()
        else:
            self._maybe_checkpoint(configs, tested, posted, metrics, "partial_complete", force=True)

        metrics.finished_ts = time.time()
        self.store.save_metrics(metrics)
        return metrics

    def _bump_daily(self, *, posted: int, alive: int, tested: int) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        data = self.store.load_daily_counter()
        if data.get("date") != today:
            data = {"date": today, "posted": 0, "alive": 0, "tested": 0}
        data["posted"] = int(data.get("posted") or 0) + posted
        data["alive"] = max(int(data.get("alive") or 0), alive)
        data["tested"] = int(data.get("tested") or 0) + tested
        self.store.save_daily_counter(data)
