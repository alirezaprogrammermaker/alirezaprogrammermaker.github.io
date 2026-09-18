from __future__ import annotations

from pathlib import Path

from v2agg.models import ProxyConfig
from v2agg.pipeline import Pipeline


def _alive(host: str, port: int, ms: float) -> ProxyConfig:
    c = ProxyConfig(
        scheme="vless",
        raw=f"vless://u@{host}:{port}?type=tcp#n",
        host=host,
        port=port,
        uuid_or_password="u",
        alive=True,
        latency_ms=ms,
        score=90,
        last_ok_ts=1_000_000.0,
    )
    c.ensure_fingerprint()
    return c


def test_filter_fresh_healthy_drops_stale(tmp_path: Path, monkeypatch):
    settings = tmp_path / "settings.yaml"
    sources = tmp_path / "sources.yaml"
    settings.write_text(
        f"""
app: {{pages_base_url: "https://example.test"}}
pipeline:
  continuous: false
  healthy_max_age_hours: 0.01
  max_configs_to_test_per_run: 10
  git_publish: false
state:
  dir: {tmp_path / "state"}
  checkpoint_file: checkpoint.json
  metrics_file: metrics.json
  healthy_db_file: healthy.json
publish:
  output_dir: {tmp_path / "subs"}
testing:
  mode: tcp
  concurrency: 2
telegram:
  dry_run: true
logging:
  level: WARNING
""",
        encoding="utf-8",
    )
    sources.write_text("sources: []\n", encoding="utf-8")
    pipe = Pipeline(settings, sources, mode="publish-only", dry_run_telegram=True)
    fresh = _alive("1.1.1.1", 443, 50)
    import time as _t

    fresh.last_ok_ts = _t.time()
    stale = _alive("2.2.2.2", 443, 40)
    stale.last_ok_ts = _t.time() - 3600
    kept = pipe._filter_fresh_healthy([fresh, stale])
    assert len(kept) == 1
    assert kept[0].host == "1.1.1.1"


def test_health_watch_removes_dead(tmp_path: Path):
    settings = tmp_path / "settings.yaml"
    sources = tmp_path / "sources.yaml"
    settings.write_text(
        f"""
app: {{pages_base_url: "https://example.test"}}
pipeline:
  continuous: true
  health_watch_interval_sec: 60
  max_runtime_sec: 5
  git_publish: false
  healthy_max_age_hours: 24
state:
  dir: {tmp_path / "state"}
  checkpoint_file: checkpoint.json
  metrics_file: metrics.json
  healthy_db_file: healthy.json
publish:
  output_dir: {tmp_path / "subs"}
testing:
  mode: tcp
  concurrency: 2
telegram:
  dry_run: true
logging:
  level: WARNING
""",
        encoding="utf-8",
    )
    sources.write_text("sources: []\n", encoding="utf-8")
    pipe = Pipeline(settings, sources, mode="refresh", dry_run_telegram=True)
    a = _alive("10.0.0.1", 443, 30)
    b = _alive("10.0.0.2", 443, 40)
    import time as _t

    now = _t.time()
    a.last_ok_ts = now
    b.last_ok_ts = now
    pipe.store.save_healthy([a, b])

    def fake_test_many(configs, **kwargs):
        out = []
        for c in configs:
            c = ProxyConfig.from_dict(c.to_dict())
            if c.host == "10.0.0.2":
                c.alive = False
                c.latency_ms = None
                c.score = 0
                c.fail_count = 1
            else:
                c.alive = True
                c.latency_ms = 25
                c.score = 100
                c.last_ok_ts = _t.time()
            c.last_test_ts = _t.time()
            out.append(c)
        return out

    pipe.watch_tester.test_many = fake_test_many  # type: ignore[method-assign]
    alive = pipe._health_watch_once()
    assert alive == 1
    stored = pipe.store.load_healthy()
    assert len(stored) == 1
    assert stored[0].host == "10.0.0.1"


def test_skip_empty_publish_keeps_previous_subs(tmp_path: Path):
    settings = tmp_path / "settings.yaml"
    sources = tmp_path / "sources.yaml"
    subs = tmp_path / "subs"
    subs.mkdir()
    (subs / "all.txt").write_text("vless://keep-me@h:1#old\n", encoding="utf-8")
    settings.write_text(
        f"""
app: {{pages_base_url: "https://example.test"}}
pipeline:
  continuous: false
  healthy_max_age_hours: 24
  git_publish: false
state:
  dir: {tmp_path / "state"}
  checkpoint_file: checkpoint.json
  metrics_file: metrics.json
  healthy_db_file: healthy.json
publish:
  output_dir: {subs}
  all_file: all.txt
testing:
  mode: tcp
telegram:
  dry_run: true
logging:
  level: WARNING
""",
        encoding="utf-8",
    )
    sources.write_text("sources: []\n", encoding="utf-8")
    pipe = Pipeline(settings, sources, mode="publish-only", dry_run_telegram=True)
    # Mid-run empty commit must not wipe existing public list
    out = pipe._commit_healthy([], reason="health-watch")
    assert out == []
    assert (subs / "all.txt").read_text(encoding="utf-8").startswith("vless://keep-me")


def test_retag_rewrites_middle_dot_remarks(tmp_path: Path):
    from urllib.parse import quote

    settings = tmp_path / "settings.yaml"
    sources = tmp_path / "sources.yaml"
    subs = tmp_path / "subs"
    subs.mkdir()
    # Broken middle-dot remark format from earlier release
    bad = "vless://11111111-2222-3333-4444-555555555555@example.com:443?security=tls&type=tcp#" + quote(
        "⚡40ms·بازی-1", safe=""
    )
    (subs / "all.txt").write_text(bad + "\n", encoding="utf-8")
    settings.write_text(
        f"""
app: {{pages_base_url: "https://example.test"}}
pipeline:
  continuous: false
  healthy_max_age_hours: 24
  git_publish: false
  max_healthy_publish: 50
  best_score_threshold: 40
state:
  dir: {tmp_path / "state"}
  checkpoint_file: checkpoint.json
  metrics_file: metrics.json
  healthy_db_file: healthy.json
publish:
  output_dir: {subs}
  all_file: all.txt
  remark_prefix: "⚡"
  usecase:
    game_max_ms: 150
    web_max_ms: 500
    download_min_kbps: 400
testing:
  mode: tcp
telegram:
  dry_run: true
logging:
  level: WARNING
""",
        encoding="utf-8",
    )
    sources.write_text("sources: []\n", encoding="utf-8")
    pipe = Pipeline(settings, sources, mode="publish-only", dry_run_telegram=True)
    assert pipe.publisher.needs_remark_retag() is True
    n = pipe._retag_public_list(reason="test")
    assert n == 1
    text = (subs / "all.txt").read_text(encoding="utf-8")
    assert "·" not in text and "%C2%B7" not in text
    from urllib.parse import unquote

    assert "بازی" in unquote(text)
