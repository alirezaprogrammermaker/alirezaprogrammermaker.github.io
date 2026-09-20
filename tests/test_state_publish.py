from __future__ import annotations

import json
from pathlib import Path

from v2agg.models import ProxyConfig, RunMetrics
from v2agg.publish.writer import Publisher
from v2agg.state.store import StateStore


def test_checkpoint_roundtrip(tmp_path: Path):
    settings = {
        "state": {
            "dir": str(tmp_path / "state"),
            "checkpoint_file": "checkpoint.json",
            "metrics_file": "metrics.json",
            "healthy_db_file": "healthy.json",
        }
    }
    store = StateStore(settings)
    cfg = ProxyConfig(scheme="vless", raw="vless://u@h:443?type=tcp", host="h", port=443, uuid_or_password="u")
    cfg.ensure_fingerprint()
    metrics = RunMetrics(raw_links=1)
    store.save_checkpoint(
        configs=[cfg],
        tested_fingerprints={cfg.fingerprint},
        posted_fingerprints=set(),
        metrics=metrics,
        phase="testing",
    )
    loaded = store.load_checkpoint()
    assert loaded is not None
    assert loaded["phase"] == "testing"
    assert cfg.fingerprint in loaded["tested_fingerprints"]


def test_publisher_no_source_in_output(tmp_path: Path):
    settings = {
        "publish": {
            "output_dir": str(tmp_path / "subs"),
            "all_file": "all.txt",
            "all_base64_file": "all.base64",
            "best_file": "best.txt",
            "best_base64_file": "best.base64",
            "by_protocol_dir": "by-protocol",
            "sanitize_remarks": True,
            "remark_prefix": "⚡",
        },
        "pipeline": {"max_healthy_publish": 50, "best_score_threshold": 70, "best_max_publish": 30},
    }
    pub = Publisher(settings)
    cfg = ProxyConfig(
        scheme="vless",
        raw="vless://u@1.1.1.1:443?type=tcp#github-source-mirror",
        host="1.1.1.1",
        port=443,
        uuid_or_password="u",
        remark="github-source-mirror",
        alive=True,
        score=90,
        latency_ms=120,
        source_id="secret-source",
    )
    paths = pub.publish([cfg])
    text = paths["all"].read_text(encoding="utf-8")
    assert "secret-source" not in text
    assert "github" not in text.lower()
    assert "120ms" in text
    index = json.loads(paths["index"].read_text(encoding="utf-8"))
    assert index["count_all"] == 1
    assert index["count_best"] == 1
