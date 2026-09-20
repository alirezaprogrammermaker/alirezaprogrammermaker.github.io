from __future__ import annotations

import os
import time
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from v2agg.models import ProxyConfig, RunMetrics
from v2agg.parse.normalize import rewrite_remark
from v2agg.util.logging import get_logger
from v2agg.util.ranking import remark_with_latency

logger = get_logger(__name__)


class TelegramClient:
    """Telegram Bot API helper. Secrets from environment only."""

    def __init__(self, settings: dict[str, Any]) -> None:
        tg = settings.get("telegram") or {}
        self.token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
        self.channel_id = (os.environ.get("TELEGRAM_CHANNEL_ID") or "").strip()
        self.channel_username = (tg.get("channel_username") or "@v2ray_active_config").strip()
        self.rate_per_min = float(tg.get("rate_limit_per_minute", 12))
        self.dry_run = bool(tg.get("dry_run", False)) or os.environ.get("TELEGRAM_DRY_RUN", "").lower() in {
            "1",
            "true",
            "yes",
        }
        self.message_template = tg.get("message_template") or "✅ Active config\n`{link}`"
        self.channel_description = (settings.get("app") or {}).get(
            "channel_description",
            "Active V2Ray/Xray configs · auto-tested · refreshed regularly",
        )
        self._resolved_chat: str | None = None
        self._last_send_ts = 0.0
        self._min_interval = 60.0 / max(self.rate_per_min, 1.0)

    @property
    def enabled(self) -> bool:
        return bool(self.token) and not self.dry_run

    def _api(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    def resolve_chat_id(self) -> str:
        if self._resolved_chat:
            return self._resolved_chat
        if self.channel_id:
            self._resolved_chat = self.channel_id
            return self._resolved_chat
        # Resolve username via getChat
        chat = self.channel_username
        if not self.token:
            self._resolved_chat = chat
            return chat
        try:
            with httpx.Client(timeout=20) as client:
                resp = client.get(self._api("getChat"), params={"chat_id": chat})
                resp.raise_for_status()
                data = resp.json()
                if data.get("ok") and data.get("result", {}).get("id") is not None:
                    self._resolved_chat = str(data["result"]["id"])
                    logger.info("resolved telegram chat id")
                    return self._resolved_chat
        except Exception as exc:
            logger.warning("getChat failed, using username: %s", type(exc).__name__)
        self._resolved_chat = chat
        return chat

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_send_ts
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

    @retry(reraise=True, stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=1, max=8))
    def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=30) as client:
            resp = client.post(self._api(method), json=payload)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                raise RuntimeError(data.get("description") or "telegram error")
            return data

    def send_message(self, text: str, *, disable_preview: bool = True) -> bool:
        if self.dry_run or not self.token:
            logger.info("telegram dry-run message chars=%d", len(text))
            return True
        self._throttle()
        chat_id = self.resolve_chat_id()
        self._post(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text[:4000],
                "parse_mode": "Markdown",
                "disable_web_page_preview": disable_preview,
            },
        )
        self._last_send_ts = time.monotonic()
        return True

    def post_config(self, cfg: ProxyConfig, index: int) -> bool:
        remark = remark_with_latency(cfg, "⚡", index)
        link = rewrite_remark(cfg.raw, remark)
        # Escape backticks in link for Markdown
        safe_link = link.replace("`", "'")
        if cfg.throughput_mbps is not None and cfg.throughput_mbps > 0:
            throughput_s = f"{cfg.throughput_mbps:.1f}"
        else:
            throughput_s = "n/a"
        text = self.message_template.format(
            protocol=cfg.scheme.upper(),
            latency_ms=int(cfg.latency_ms or 0),
            throughput_mbps=throughput_s,
            score=int(cfg.score),
            link=safe_link,
        )
        return self.send_message(text)

    def post_nightly_report(self, metrics: RunMetrics, daily_posted: int) -> bool:
        # Source health without naming scrape tricks — only counts / status
        ok = metrics.fetched_sources_ok
        fail = metrics.fetched_sources_fail
        lines = [
            "📊 Nightly summary",
            "",
            f"Posted today: {daily_posted}",
            f"Alive this run: {metrics.alive}",
            f"Tested this run: {metrics.tested}",
            f"Published list size: {metrics.published}",
            f"Sources OK/Fail: {ok}/{fail}",
            "",
            "Only healthy servers remain in the public list.",
        ]
        return self.send_message("\n".join(lines))

    def update_description(self, last_activity: str | None = None, alive_count: int | None = None) -> bool:
        desc = self.channel_description.strip()
        if alive_count is not None:
            desc = f"{desc}\nAlive: {alive_count}"
        if last_activity:
            desc = f"{desc}\nLast update: {last_activity}"
        desc = desc[:255]
        if self.dry_run or not self.token:
            logger.info("telegram dry-run setChatDescription chars=%d", len(desc))
            return True
        chat_id = self.resolve_chat_id()
        try:
            self._post("setChatDescription", {"chat_id": chat_id, "description": desc})
            return True
        except Exception as exc:
            logger.warning("setChatDescription failed: %s", type(exc).__name__)
            return False
