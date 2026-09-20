from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote

from v2agg.models import ProxyConfig
from v2agg.parse.links import parse_link
from v2agg.pipeline import Pipeline
from v2agg.publish.writer import Publisher
from v2agg.test.live import (
    HY2_SCHEMES,
    LiveTester,
    ProbeResult,
    build_singbox_hysteria2_config,
    combined_score,
    score_latency,
    score_throughput,
)
from v2agg.util.config import load_yaml
from v2agg.util.ranking import remark_with_latency, select_best_configs


def _cfg(i: int, *, score: float, latency_ms: float, mbps: float | None = None, alive: bool = True) -> ProxyConfig:
    c = ProxyConfig(
        scheme="vless",
        raw=f"vless://u@10.0.0.{i % 250}:443?type=tcp#n{i}",
        host=f"10.0.0.{i % 250}",
        port=443 + i,
        uuid_or_password=f"u{i}",
        alive=alive,
        score=score,
        latency_ms=latency_ms,
        throughput_mbps=mbps,
        last_ok_ts=1_700_000_000.0,
    )
    c.ensure_fingerprint()
    return c


def test_select_best_threshold_and_top_n():
    mixed = [
        _cfg(1, score=90, latency_ms=80),
        _cfg(2, score=85, latency_ms=90),
        _cfg(3, score=72, latency_ms=200),
        _cfg(4, score=70, latency_ms=150),
        _cfg(5, score=69.9, latency_ms=40),
        _cfg(6, score=40, latency_ms=30),
        _cfg(7, score=100, latency_ms=20, alive=False),
    ]
    best = select_best_configs(mixed, score_threshold=70, max_publish=3)
    assert len(best) == 3
    assert all(c.score >= 70 and c.alive for c in best)
    assert [c.score for c in best] == [90, 85, 72]


def test_publisher_best_is_strict_subset(tmp_path: Path):
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
        "pipeline": {
            "max_healthy_publish": 150,
            "best_score_threshold": 70,
            "best_max_publish": 30,
        },
    }
    configs = []
    for i in range(80):
        # 40 below threshold, 40 at/above; all would otherwise ≈ best
        score = 50.0 if i < 40 else 80.0 + (i % 10) / 10.0
        configs.append(_cfg(i, score=score, latency_ms=100 + i, mbps=5.5 if i >= 40 else None))
    pub = Publisher(settings)
    paths = pub.publish(configs)
    all_lines = [ln for ln in paths["all"].read_text(encoding="utf-8").splitlines() if ln]
    best_lines = [ln for ln in paths["best"].read_text(encoding="utf-8").splitlines() if ln]
    index = json.loads(paths["index"].read_text(encoding="utf-8"))
    assert len(all_lines) == 80
    assert len(best_lines) == 30
    assert index["count_best"] == 30
    assert index["count_all"] == 80
    assert index["count_best"] < index["count_all"]
    assert any("5.5M" in unquote(ln) for ln in best_lines)
    assert any("ms" in unquote(ln) for ln in all_lines)


def test_publisher_defaults_match_yaml_and_cap_best(tmp_path: Path):
    yaml_settings = load_yaml("config/settings.yaml")
    pipe = yaml_settings["pipeline"]
    testing = yaml_settings["testing"]
    assert pipe["best_score_threshold"] == 70
    assert pipe["best_max_publish"] == 30
    assert pipe["max_healthy_publish"] == 150
    assert testing["throughput_enabled"] is True
    assert testing["throughput_bytes"] == 262144
    assert testing["singbox_bin"] == "bin/sing-box"
    assert testing["score_latency_weight"] == 0.65
    assert testing["score_throughput_weight"] == 0.35

    pub = Publisher({"publish": {"output_dir": str(tmp_path / "subs")}, "pipeline": {}})
    assert pub.best_threshold == 70
    assert pub.best_max_publish == 30
    assert pub.max_healthy == 150

    configs = [_cfg(i, score=50 + (i % 45), latency_ms=200) for i in range(60)]
    paths = pub.publish(configs)
    index = json.loads(paths["index"].read_text(encoding="utf-8"))
    assert index["count_all"] == 60
    assert index["count_best"] <= 30
    assert index["count_best"] < index["count_all"]
    # With threshold 70, only scores >= 70 (50+20..50+44 → 70-94) qualify
    assert index["count_best"] == min(30, sum(1 for c in configs if c.score >= 70))


def test_score_throughput_knees():
    settings = {"testing": {}}
    assert score_throughput(8, settings) == 100.0
    assert score_throughput(20, settings) == 100.0
    assert abs(score_throughput(3, settings) - 70.0) < 1e-9
    assert abs(score_throughput(1, settings) - 40.0) < 1e-9
    assert score_throughput(0.5, settings) < 40
    assert score_throughput(0, settings) == 0.0


def test_combined_score_blend_and_missing_penalty():
    settings = {
        "testing": {
            "throughput_enabled": True,
            "score_latency_weight": 0.65,
            "score_throughput_weight": 0.35,
            "score_throughput_missing_penalty": 0.20,
        }
    }
    # Excellent ping + excellent Mbps → 100
    assert combined_score(100, 10, settings) == 100.0
    # Excellent ping, no Mbps after a real proxy probe → 80 (20% penalty, not fake Mbps)
    missing = combined_score(100, None, settings, throughput_attempted=True)
    assert abs(missing - 80.0) < 1e-9
    # TCP-only (not attempted) keeps latency score
    tcp_only = combined_score(100, None, settings, throughput_attempted=False)
    assert tcp_only == 100.0
    blended = combined_score(100, 3, settings)
    # 0.65*100 + 0.35*70 = 89.5
    assert abs(blended - 89.5) < 1e-9
    disabled = combined_score(100, 10, {"testing": {"throughput_enabled": False}})
    assert disabled == score_latency(100, settings)


def test_hy2_tcp_fallback_never_marks_alive(monkeypatch):
    tcp_calls: list[tuple] = []

    def fake_tcp(host, port, timeout):
        tcp_calls.append((host, port, timeout))
        return 12.0

    monkeypatch.setattr("v2agg.test.live.tcp_connect", fake_tcp)
    tester = LiveTester(
        {
            "testing": {
                "mode": "tcp",
                "tcp_timeout_sec": 1,
                "throughput_enabled": False,
                "singbox_bin": "/nonexistent/sing-box-missing",
                "xray_bin": "/nonexistent/xray-missing",
            }
        }
    )
    cfg = parse_link("hy2://secret@example.com:443?sni=example.com&insecure=1#n")
    assert cfg is not None
    assert cfg.scheme in HY2_SCHEMES
    out = tester.test_one(cfg)
    assert out.alive is False
    assert out.score == 0.0
    assert out.throughput_mbps is None
    assert tcp_calls == []


def test_hy2_xray_unsupported_does_not_tcp(monkeypatch):
    tcp_calls: list[tuple] = []
    monkeypatch.setattr("v2agg.test.live.tcp_connect", lambda *a, **k: tcp_calls.append(a) or 8.0)
    tester = LiveTester(
        {
            "testing": {
                "mode": "auto",
                "throughput_enabled": False,
                "singbox_bin": "/nonexistent/sing-box-missing",
                "xray_bin": "/nonexistent/xray-missing",
            }
        }
    )
    cfg = parse_link(
        "hysteria2://pw@hy.example.net:443?sni=cdn.example.net&insecure=1&obfs=salamander&obfs-password=frog"
    )
    assert cfg is not None
    out = tester.test_one(cfg)
    assert out.alive is False
    assert tcp_calls == []


def test_build_singbox_config_from_hy2_uri():
    cfg = parse_link(
        "hysteria2://secretpass@node.example.com:443"
        "?sni=cdn.example.com&insecure=1&obfs=salamander&obfs-password=frog#hy2"
    )
    assert cfg is not None
    assert cfg.scheme == "hysteria2"
    assert cfg.uuid_or_password == "secretpass"
    assert cfg.sni == "cdn.example.com"
    conf = build_singbox_hysteria2_config(cfg, 22100)
    assert conf is not None
    inbound = conf["inbounds"][0]
    assert inbound["type"] == "socks"
    assert inbound["listen_port"] == 22100
    outbound = conf["outbounds"][0]
    assert outbound["type"] == "hysteria2"
    assert outbound["server"] == "node.example.com"
    assert outbound["server_port"] == 443
    assert outbound["password"] == "secretpass"
    assert outbound["tls"]["server_name"] == "cdn.example.com"
    assert outbound["tls"]["insecure"] is True
    assert outbound["obfs"]["type"] == "salamander"
    assert outbound["obfs"]["password"] == "frog"


def test_build_singbox_respects_insecure_zero():
    cfg = parse_link("hy2://auth@host.example:8443?sni=host.example&insecure=0")
    assert cfg is not None
    conf = build_singbox_hysteria2_config(cfg, 1)
    assert conf is not None
    assert conf["outbounds"][0]["tls"]["insecure"] is False


def test_remark_includes_latency_and_mbps():
    cfg = _cfg(1, score=90, latency_ms=123.4, mbps=8.25)
    remark = remark_with_latency(cfg, "⚡", 1)
    assert "123ms" in remark
    assert "8.2M" in remark
    assert "github" not in remark.lower()


def test_publish_only_smoke_fake_healthy(tmp_path: Path):
    settings = tmp_path / "settings.yaml"
    sources = tmp_path / "sources.yaml"
    settings.write_text(
        f"""
app: {{pages_base_url: "https://example.test"}}
pipeline:
  continuous: false
  git_publish: false
  healthy_max_age_hours: 24
  max_healthy_publish: 150
  best_score_threshold: 70
  best_max_publish: 30
state:
  dir: {tmp_path / "state"}
  checkpoint_file: checkpoint.json
  metrics_file: metrics.json
  healthy_db_file: healthy.json
publish:
  output_dir: {tmp_path / "subs"}
  sanitize_remarks: true
  remark_prefix: "⚡"
testing:
  mode: tcp
  concurrency: 2
  throughput_enabled: false
telegram:
  dry_run: true
logging:
  level: WARNING
""",
        encoding="utf-8",
    )
    sources.write_text("sources: []\n", encoding="utf-8")
    pipe = Pipeline(settings, sources, mode="publish-only", dry_run_telegram=True)
    import time as _t

    now = _t.time()
    batch = []
    for i in range(40):
        c = _cfg(i, score=40 if i < 25 else 95, latency_ms=50 + i, mbps=4.0 if i >= 25 else None)
        c.last_ok_ts = now
        batch.append(c)
    pipe.store.save_healthy(batch)
    metrics = pipe.run()
    assert metrics.published == 40
    index = json.loads((tmp_path / "subs" / "index.json").read_text(encoding="utf-8"))
    assert index["count_all"] == 40
    assert index["count_best"] == 15  # 15 nodes with score 95
    assert index["count_best"] < index["count_all"]
    best_txt = (tmp_path / "subs" / "best.txt").read_text(encoding="utf-8")
    assert "secret-source" not in best_txt
    assert "github" not in best_txt.lower()


def test_singbox_probe_success_sets_throughput(monkeypatch):
    tester = LiveTester(
        {
            "testing": {
                "mode": "auto",
                "throughput_enabled": True,
                "singbox_bin": "/nonexistent/sing-box-missing",
                "xray_bin": "/nonexistent/xray-missing",
            }
        }
    )
    tester._use_singbox = True

    def fake_probe(cfg, local_port):
        return ProbeResult(latency_ms=90.0, throughput_mbps=6.5, throughput_attempted=True)

    tester.singbox.probe = fake_probe  # type: ignore[method-assign]
    cfg = parse_link("hy2://pw@h.example:443?sni=h.example&insecure=1")
    assert cfg is not None
    out = tester.test_one(cfg)
    assert out.alive is True
    assert out.throughput_mbps == 6.5
    assert out.score > 70
