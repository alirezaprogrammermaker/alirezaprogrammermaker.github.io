from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from v2agg.models import ProxyConfig, RunMetrics
from v2agg.util.logging import get_logger

logger = get_logger(__name__)


class StateStore:
    """Persists checkpoint / healthy DB for resumable runs."""

    def __init__(self, settings: dict[str, Any]) -> None:
        st = settings.get("state") or {}
        self.dir = Path(st.get("dir") or "state")
        self.dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_path = self.dir / (st.get("checkpoint_file") or "checkpoint.json")
        self.metrics_path = self.dir / (st.get("metrics_file") or "metrics.json")
        self.healthy_path = self.dir / (st.get("healthy_db_file") or "healthy.json")

    def load_checkpoint(self) -> dict[str, Any] | None:
        if not self.checkpoint_path.exists():
            return None
        try:
            data = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                logger.info("loaded checkpoint tested=%s", len(data.get("tested_fingerprints") or []))
                return data
        except Exception as exc:
            logger.warning("checkpoint load failed: %s", exc)
        return None

    def save_checkpoint(
        self,
        *,
        configs: list[ProxyConfig],
        tested_fingerprints: set[str],
        posted_fingerprints: set[str],
        metrics: RunMetrics,
        phase: str,
    ) -> None:
        payload = {
            "version": 1,
            "saved_ts": time.time(),
            "phase": phase,
            "tested_fingerprints": sorted(tested_fingerprints),
            "posted_fingerprints": sorted(posted_fingerprints),
            "configs": [c.to_dict() for c in configs],
            "metrics": metrics.to_dict(),
        }
        tmp = self.checkpoint_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.checkpoint_path)
        logger.info("checkpoint saved phase=%s configs=%d", phase, len(configs))

    def clear_checkpoint(self) -> None:
        if self.checkpoint_path.exists():
            self.checkpoint_path.unlink()
            logger.info("checkpoint cleared")

    def load_healthy(self) -> list[ProxyConfig]:
        if not self.healthy_path.exists():
            return []
        try:
            data = json.loads(self.healthy_path.read_text(encoding="utf-8"))
            items = data.get("configs") if isinstance(data, dict) else data
            if not isinstance(items, list):
                return []
            return [ProxyConfig.from_dict(x) for x in items if isinstance(x, dict)]
        except Exception as exc:
            logger.warning("healthy db load failed: %s", exc)
            return []

    def save_healthy(self, configs: list[ProxyConfig]) -> None:
        payload = {"saved_ts": time.time(), "configs": [c.to_dict() for c in configs]}
        tmp = self.healthy_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.healthy_path)

    def save_metrics(self, metrics: RunMetrics) -> None:
        self.metrics_path.write_text(json.dumps(metrics.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def load_daily_counter(self) -> dict[str, Any]:
        path = self.dir / "daily.json"
        if not path.exists():
            return {"date": "", "posted": 0, "alive": 0, "tested": 0}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"date": "", "posted": 0, "alive": 0, "tested": 0}

    def save_daily_counter(self, data: dict[str, Any]) -> None:
        path = self.dir / "daily.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
