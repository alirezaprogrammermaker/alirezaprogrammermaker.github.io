from __future__ import annotations

import copy
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from v2agg.collect.dedup import deduplicate, evict_stale
from v2agg.collect.fetcher import Fetcher, load_sources
from v2agg.models import ProxyConfig, RunMetrics
from v2agg.publish.gitpush import push_subs_if_changed
from v2agg.publish.writer import Publisher
from v2agg.state.store import StateStore
from v2agg.telegram.client import TelegramClient
from v2agg.test.live import LiveTester
from v2agg.util.config import load_yaml
from v2agg.util.logging import get_logger, setup_logging
from v2agg.util.ranking import sort_by_latency
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
        # Parallel health-watch tester (separate SOCKS/xray ports to avoid clashes)
        watch_settings = copy.deepcopy(self.settings)
        tw = watch_settings.setdefault("testing", {})
        tw["local_socks_base_port"] = int(tw.get("watch_socks_base_port") or 26000)
        tw["xray_workdir"] = tw.get("watch_xray_workdir") or "state/runtime/xray-watch"
        tw["singbox_workdir"] = tw.get("watch_singbox_workdir") or "state/runtime/singbox-watch"
        tw["singbox_socks_base_port"] = int(tw.get("watch_singbox_socks_base_port") or 27000)
        tw["concurrency"] = int(tw.get("watch_concurrency") or min(16, int(tw.get("concurrency") or 16)))
        self.watch_tester = LiveTester(watch_settings)
        self.publisher = Publisher(self.settings)
        self.telegram = TelegramClient(self.settings)

        pipe = self.settings.get("pipeline") or {}
        self.max_runtime = float(pipe.get("max_runtime_sec", 19800))
        self.checkpoint_interval = float(pipe.get("checkpoint_interval_sec", 120))
        self.max_test = int(pipe.get("max_configs_to_test_per_run", 800))
        self.max_tg = int(pipe.get("max_telegram_post_per_run", 15))
        self.best_threshold = float(pipe.get("best_score_threshold", 70))
        self.best_max_publish = int(pipe.get("best_max_publish", 30))
        self.retest_healthy_first = bool(pipe.get("retest_healthy_first", True))
        self.healthy_max_age_hours = float(pipe.get("healthy_max_age_hours", 4))
        self.continuous = bool(pipe.get("continuous", True))
        self.health_watch_interval = float(pipe.get("health_watch_interval_sec", 120))
        self.discovery_pause = float(pipe.get("discovery_cycle_pause_sec", 10))
        self.git_publish = bool(pipe.get("git_publish", True))
        self._deadline = time.monotonic() + self.max_runtime
        self._last_checkpoint = time.monotonic()
        self._lock = threading.RLock()
        self._posted: set[str] = set()
        self._stop_watch = threading.Event()
        self._last_desc_ts = 0.0

    def _should_stop(self) -> bool:
        return time.monotonic() >= self._deadline or self._stop_watch.is_set()

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

    def _prioritize_queue(self, merged: list[ProxyConfig], prev_healthy: list[ProxyConfig]) -> list[ProxyConfig]:
        if not self.retest_healthy_first or not prev_healthy:
            return merged[: self.max_test]
        healthy_fps = {c.ensure_fingerprint() for c in prev_healthy}
        priority = [c for c in merged if c.ensure_fingerprint() in healthy_fps]
        rest = [c for c in merged if c.ensure_fingerprint() not in healthy_fps]
        return (priority + rest)[: self.max_test]

    def _filter_fresh_healthy(self, configs: list[ProxyConfig], now: float | None = None) -> list[ProxyConfig]:
        now_ts = now if now is not None else time.time()
        max_age = self.healthy_max_age_hours * 3600
        kept: list[ProxyConfig] = []
        for cfg in configs:
            if not cfg.alive or cfg.last_ok_ts is None:
                continue
            if (now_ts - cfg.last_ok_ts) > max_age:
                continue
            kept.append(cfg)
        return sort_by_latency(kept)

    def _commit_healthy(self, healthy: list[ProxyConfig], *, reason: str) -> list[ProxyConfig]:
        """Persist + publish (+ optional git push). Caller should hold lock when merging state."""
        fresh = self._filter_fresh_healthy(healthy)
        self.store.save_healthy(fresh)
        self.publisher.publish(fresh)
        logger.info("list updated reason=%s alive=%d", reason, len(fresh))
        if self.git_publish:
            push_subs_if_changed()
        # Throttle channel description updates (at most every ~2 min)
        now = time.monotonic()
        if now - self._last_desc_ts >= min(self.health_watch_interval, 120):
            try:
                self.telegram.update_description(
                    last_activity=format_activity_label(),
                    alive_count=len(fresh),
                )
                self._last_desc_ts = now
            except Exception as exc:
                logger.warning("telegram description update failed: %s", type(exc).__name__)
        return fresh

    def _merge_alive_into_store(self, probed: list[ProxyConfig]) -> list[ProxyConfig]:
        """Apply probe results onto the healthy DB under lock; drop dead; add newly alive."""
        with self._lock:
            current = {c.ensure_fingerprint(): c for c in self.store.load_healthy()}
            for c in probed:
                fp = c.ensure_fingerprint()
                if c.alive and c.last_ok_ts:
                    current[fp] = c
                elif c.last_test_ts and not c.alive:
                    current.pop(fp, None)
            return self._commit_healthy(list(current.values()), reason="probe-merge")

    def _health_watch_once(self) -> int:
        """Retest every currently healthy server; remove dead. Returns remaining alive count."""
        with self._lock:
            snapshot = list(self.store.load_healthy())
        if not snapshot:
            logger.info("health-watch: empty list")
            return 0
        logger.info("health-watch: probing %d healthy servers", len(snapshot))
        # Copy so tester mutations don't race discovery mid-list
        to_probe = [ProxyConfig.from_dict(c.to_dict()) for c in snapshot]
        results = self.watch_tester.test_many(
            to_probe,
            should_stop=self._should_stop,
        )
        alive = sum(1 for c in results if c.alive)
        dead = len(results) - alive
        self._merge_alive_into_store(results)
        logger.info("health-watch done alive=%d dead_removed=%d", alive, dead)
        return alive

    def _health_watch_loop(self) -> None:
        logger.info("health-watch started interval=%ss", int(self.health_watch_interval))
        # Immediate first pass so stale list is cleaned ASAP at job start
        try:
            self._health_watch_once()
        except Exception as exc:
            logger.warning("health-watch initial pass failed: %s", type(exc).__name__)
        while not self._stop_watch.wait(self.health_watch_interval):
            if self._should_stop():
                break
            try:
                self._health_watch_once()
            except Exception as exc:
                logger.warning("health-watch pass failed: %s", type(exc).__name__)
        logger.info("health-watch stopped")

    def _discovery_cycle(self, metrics: RunMetrics, posted: set[str]) -> None:
        """Fetch sources, test a batch of candidates, merge survivors into the live list."""
        sources = load_sources(self.sources_cfg)
        collected, source_results = self.fetcher.collect(sources)
        metrics.fetched_sources_ok = sum(1 for s in source_results if s.ok)
        metrics.fetched_sources_fail = sum(1 for s in source_results if not s.ok)
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

        with self._lock:
            prev_healthy = self.store.load_healthy()
            healthy_fps = {c.ensure_fingerprint() for c in prev_healthy}

        # Prefer brand-new candidates; also re-check any prior healthy not currently in DB
        candidates = [c for c in collected if c.ensure_fingerprint() not in healthy_fps]
        # Fill remaining quota with older pool for replacement capacity
        val = self.settings.get("validation") or {}
        pool = deduplicate(list(collected) + prev_healthy)
        pool = evict_stale(
            pool,
            max_fail_count=int(val.get("max_fail_count", 2)),
            max_age_hours=float(val.get("max_age_hours", 24)),
        )
        # New first, then the rest
        seen = {c.ensure_fingerprint() for c in candidates}
        for c in pool:
            fp = c.ensure_fingerprint()
            if fp not in seen:
                candidates.append(c)
                seen.add(fp)
        metrics.after_dedup = len(candidates)
        batch = candidates[: self.max_test]
        logger.info("discovery cycle queue=%d (newish focus)", len(batch))
        if not batch:
            return

        results = self.tester.test_many(
            batch,
            should_stop=self._should_stop,
            on_progress=lambda d, t: logger.info("discovery tested=%d/%d", d, t),
        )
        metrics.tested += sum(1 for c in results if c.last_test_ts)
        metrics.alive = sum(1 for c in results if c.alive)
        healthy = self._merge_alive_into_store(results)
        metrics.published = len(healthy)

        # Telegram: only brand-new low-ping winners
        tg_candidates = [
            c
            for c in healthy
            if c.alive
            and c.score >= self.best_threshold
            and c.ensure_fingerprint() not in posted
            and c.ensure_fingerprint() not in healthy_fps
        ]
        tg_candidates = sort_by_latency(tg_candidates)
        posted_count = 0
        for i, cfg in enumerate(tg_candidates[: self.max_tg], start=1):
            if self._should_stop():
                break
            try:
                if self.telegram.post_config(cfg, i):
                    posted.add(cfg.ensure_fingerprint())
                    posted_count += 1
            except Exception as exc:
                logger.warning("telegram post failed: %s", type(exc).__name__)
        metrics.telegram_posted += posted_count
        self._bump_daily(posted=posted_count, alive=metrics.alive, tested=metrics.tested)

    def run_continuous(self) -> RunMetrics:
        """Stay alive for ~max_runtime_sec with parallel 2-min healthy-list watchdog."""
        metrics = RunMetrics(started_ts=time.time())
        posted: set[str] = set(self._posted)
        logger.info(
            "continuous mode start runtime=%ss health_watch=%ss",
            int(self.max_runtime),
            int(self.health_watch_interval),
        )
        watch = threading.Thread(target=self._health_watch_loop, name="health-watch", daemon=True)
        watch.start()
        cycle = 0
        try:
            while not self._should_stop():
                cycle += 1
                logger.info("discovery cycle #%d remaining=%ss", cycle, int(self._deadline - time.monotonic()))
                try:
                    self._discovery_cycle(metrics, posted)
                except Exception as exc:
                    logger.warning("discovery cycle failed: %s", type(exc).__name__)
                self.store.save_metrics(metrics)
                # Pause between discovery cycles so health-watch gets CPU; exit early near deadline
                remaining = self._deadline - time.monotonic()
                if remaining <= 30:
                    break
                self._stop_watch.wait(min(self.discovery_pause, max(1.0, remaining - 15)))
        finally:
            self._stop_watch.set()
            watch.join(timeout=max(30.0, self.health_watch_interval))
            # Final publish of whatever is still healthy
            with self._lock:
                final = self._commit_healthy(self.store.load_healthy(), reason="shutdown")
            metrics.published = len(final)
            metrics.finished_ts = time.time()
            self.store.clear_checkpoint()
            self.store.save_metrics(metrics)
            logger.info(
                "continuous mode end cycles=%d published=%d elapsed=%ss",
                cycle,
                metrics.published,
                int(metrics.finished_ts - metrics.started_ts),
            )
        return metrics

    def run(self) -> RunMetrics:
        if self.mode == "publish-only":
            healthy = self._filter_fresh_healthy(self.store.load_healthy())
            self.store.save_healthy(healthy)
            self.publisher.publish(healthy)
            metrics = RunMetrics(started_ts=time.time(), finished_ts=time.time(), published=len(healthy))
            self.store.save_metrics(metrics)
            return metrics
        if self.mode == "refresh" and self.continuous:
            return self.run_continuous()
        return self.run_once()

    def run_once(self) -> RunMetrics:
        """Single collect→test→publish pass (nightly / non-continuous)."""
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

        if not configs:
            sources = load_sources(self.sources_cfg)
            collected, source_results = self.fetcher.collect(sources)
            metrics.fetched_sources_ok = sum(1 for s in source_results if s.ok)
            metrics.fetched_sources_fail = sum(1 for s in source_results if not s.ok)
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
            for c in prev_healthy:
                c.alive = False
            merged = deduplicate(list(collected) + prev_healthy)
            val = self.settings.get("validation") or {}
            merged = evict_stale(
                merged,
                max_fail_count=int(val.get("max_fail_count", 2)),
                max_age_hours=float(val.get("max_age_hours", 24)),
            )
            metrics.after_dedup = len(merged)
            configs = self._prioritize_queue(merged, prev_healthy)
            logger.info(
                "queue size=%d (healthy_priority=%d)",
                len(configs),
                min(len(prev_healthy), len(configs)),
            )
            self._maybe_checkpoint(configs, tested, posted, metrics, "collected", force=True)

        def on_progress(done: int, total: int) -> None:
            logger.info("progress tested=%d/%d", done, total)
            self._maybe_checkpoint(configs, tested, posted, metrics, "testing")

        results = self.tester.test_many(
            configs,
            should_stop=self._should_stop,
            on_progress=on_progress,
            skip_fingerprints=tested,
        )
        for c in results:
            if c.last_test_ts:
                tested.add(c.ensure_fingerprint())
        configs = results
        metrics.tested = len(tested)
        metrics.alive = sum(1 for c in configs if c.alive)
        self._maybe_checkpoint(configs, tested, posted, metrics, "tested", force=True)

        alive_now = [c for c in configs if c.alive and c.last_ok_ts]
        by_fp = {c.ensure_fingerprint(): c for c in alive_now}
        for c in configs:
            fp = c.ensure_fingerprint()
            if c.last_test_ts and not c.alive:
                by_fp.pop(fp, None)
        healthy_all = self._filter_fresh_healthy(list(by_fp.values()))
        self.store.save_healthy(healthy_all)
        self.publisher.publish(healthy_all)
        metrics.published = len(healthy_all)

        if self.mode in {"refresh", "nightly"}:
            candidates = [
                c
                for c in healthy_all
                if c.alive and c.score >= self.best_threshold and c.ensure_fingerprint() not in posted
            ]
            candidates = sort_by_latency(candidates)
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
                    alive_count=metrics.published,
                )
            except Exception as exc:
                logger.warning("telegram description update failed: %s", type(exc).__name__)

        if self.mode == "nightly":
            daily = self.store.load_daily_counter()
            try:
                self.telegram.post_nightly_report(metrics, int(daily.get("posted") or 0))
            except Exception as exc:
                logger.warning("nightly report failed: %s", type(exc).__name__)

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
