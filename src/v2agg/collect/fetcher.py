from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from v2agg.models import ProxyConfig, SourceResult
from v2agg.parse.links import parse_many
from v2agg.util.encoding import decode_subscription_body
from v2agg.util.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SourceSpec:
    id: str
    url: str
    enabled: bool = True
    timeout_sec: float = 30.0
    weight: float = 1.0


def load_sources(config: dict[str, Any]) -> list[SourceSpec]:
    items = config.get("sources") or []
    out: list[SourceSpec] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("id") or "").strip()
        url = str(item.get("url") or "").strip()
        if not sid or not url:
            continue
        out.append(
            SourceSpec(
                id=sid,
                url=url,
                enabled=bool(item.get("enabled", True)),
                timeout_sec=float(item.get("timeout_sec", 30)),
                weight=float(item.get("weight", 1)),
            )
        )
    return out


class Fetcher:
    def __init__(self, settings: dict[str, Any]) -> None:
        fetch = settings.get("fetch") or {}
        self.user_agent = fetch.get("user_agent", "v2agg/1.0")
        self.retries = int(fetch.get("retries", 3))
        self.backoff_base = float(fetch.get("backoff_base_sec", 1.5))
        self.backoff_max = float(fetch.get("backoff_max_sec", 20))
        self.connect_timeout = float(fetch.get("connect_timeout_sec", 15))
        self.read_timeout = float(fetch.get("read_timeout_sec", 45))
        self.concurrency = int(fetch.get("concurrency", 8))

    def _client(self, timeout_sec: float) -> httpx.Client:
        timeout = httpx.Timeout(
            connect=min(self.connect_timeout, timeout_sec),
            read=min(self.read_timeout, timeout_sec),
            write=timeout_sec,
            pool=timeout_sec,
        )
        return httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": self.user_agent, "Accept": "text/plain,*/*"},
        )

    def fetch_text(self, url: str, timeout_sec: float) -> str:
        attempts = max(1, self.retries)

        @retry(
            reraise=True,
            stop=stop_after_attempt(attempts),
            wait=wait_exponential_jitter(initial=self.backoff_base, max=self.backoff_max),
            retry=retry_if_exception_type((httpx.HTTPError, TimeoutError)),
        )
        def _do() -> str:
            with self._client(timeout_sec) as client:
                resp = client.get(url)
                resp.raise_for_status()
                return resp.text

        return _do()

    def _fetch_one(self, src: SourceSpec) -> tuple[list[ProxyConfig], SourceResult]:
        t0 = time.monotonic()
        try:
            body = self.fetch_text(src.url, src.timeout_sec)
            text = decode_subscription_body(body)
            parsed = parse_many(text)
            for c in parsed:
                c.source_id = src.id
            elapsed = (time.monotonic() - t0) * 1000
            result = SourceResult(
                source_id=src.id,
                url=src.url,
                ok=True,
                configs_found=len(parsed),
                elapsed_ms=elapsed,
            )
            logger.info("source ok id=%s found=%d elapsed_ms=%.0f", src.id, len(parsed), elapsed)
            return parsed, result
        except Exception as exc:
            elapsed = (time.monotonic() - t0) * 1000
            result = SourceResult(
                source_id=src.id,
                url=src.url,
                ok=False,
                error=type(exc).__name__,
                elapsed_ms=elapsed,
            )
            logger.warning("source fail id=%s err=%s", src.id, type(exc).__name__)
            return [], result

    def collect(self, sources: list[SourceSpec]) -> tuple[list[ProxyConfig], list[SourceResult]]:
        enabled = [s for s in sources if s.enabled]
        for s in sources:
            if not s.enabled:
                logger.info("skip disabled source id=%s", s.id)

        configs: list[ProxyConfig] = []
        results: list[SourceResult] = []
        if not enabled:
            return configs, results

        workers = max(1, min(self.concurrency, len(enabled)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(self._fetch_one, src): src for src in enabled}
            for fut in as_completed(futs):
                parsed, result = fut.result()
                configs.extend(parsed)
                results.append(result)
        # Stable order by source id for metrics readability
        results.sort(key=lambda r: r.source_id)
        return configs, results
