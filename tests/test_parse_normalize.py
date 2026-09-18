from __future__ import annotations

import base64
import json

import pytest

from v2agg.collect.dedup import deduplicate, evict_stale
from v2agg.models import ProxyConfig
from v2agg.parse.links import extract_links, parse_link, parse_many
from v2agg.parse.normalize import sanitize_remark
from v2agg.test.live import score_latency
from v2agg.util.encoding import decode_subscription_body, encode_subscription_base64, try_b64_decode


def test_parse_vmess():
    payload = base64.b64encode(
        json.dumps(
            {
                "v": "2",
                "ps": "test-node",
                "add": "1.2.3.4",
                "port": "443",
                "id": "11111111-2222-3333-4444-555555555555",
                "aid": "0",
                "net": "ws",
                "type": "none",
                "host": "example.com",
                "path": "/ray",
                "tls": "tls",
                "sni": "sni.example.com",
            }
        ).encode()
    ).decode()
    link = f"vmess://{payload}"
    cfg = parse_link(link)
    assert cfg is not None
    assert cfg.scheme == "vmess"
    assert cfg.host == "1.2.3.4"
    assert cfg.port == 443
    assert cfg.network == "ws"
    assert cfg.security == "tls"
    assert cfg.sni == "sni.example.com"
    assert cfg.extra.get("host") == "example.com"
    assert cfg.ensure_fingerprint()


def test_parse_vmess_tls_bool():
    payload = base64.b64encode(
        json.dumps(
            {
                "add": "9.9.9.9",
                "port": 443,
                "id": "11111111-2222-3333-4444-555555555555",
                "net": "tcp",
                "tls": True,
            }
        ).encode()
    ).decode()
    cfg = parse_link(f"vmess://{payload}")
    assert cfg is not None
    assert cfg.security == "tls"


def test_parse_vless():
    link = (
        "vless://11111111-2222-3333-4444-555555555555@example.com:443"
        "?encryption=none&security=tls&type=ws&path=%2Fpath&sni=sni.example.com&host=cdn.example.com#MyNode"
    )
    cfg = parse_link(link)
    assert cfg is not None
    assert cfg.scheme == "vless"
    assert cfg.host == "example.com"
    assert cfg.port == 443
    assert cfg.sni == "sni.example.com"
    assert cfg.extra.get("host") == "cdn.example.com"


def test_parse_trojan():
    link = "trojan://secretpass@cdn.example.net:443?security=tls&sni=cdn.example.net#tr"
    cfg = parse_link(link)
    assert cfg is not None
    assert cfg.scheme == "trojan"
    assert cfg.uuid_or_password == "secretpass"


def test_parse_ss_userinfo():
    userinfo = base64.b64encode(b"aes-256-gcm:password123").decode()
    link = f"ss://{userinfo}@10.0.0.1:8388#ssnode"
    cfg = parse_link(link)
    assert cfg is not None
    assert cfg.scheme == "ss"
    assert cfg.host == "10.0.0.1"
    assert cfg.port == 8388


def test_extract_and_parse_many():
    text = """
    junk
    vless://aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee@h.example:80?type=tcp#a
    trojan://pw@h2.example:443?security=tls#b
    """
    links = extract_links(text)
    assert len(links) >= 2
    configs = parse_many(text)
    assert len(configs) == 2


def test_dedup_by_fingerprint():
    a = ProxyConfig(scheme="vless", raw="vless://u@h:1?type=tcp#1", host="h", port=1, uuid_or_password="u")
    b = ProxyConfig(scheme="vless", raw="vless://u@h:1?type=tcp#2", host="h", port=1, uuid_or_password="u")
    a.ensure_fingerprint()
    b.ensure_fingerprint()
    assert a.fingerprint == b.fingerprint
    out = deduplicate([a, b])
    assert len(out) == 1


def test_evict_stale_fail_count():
    c = ProxyConfig(scheme="ss", raw="ss://x", host="h", port=1, uuid_or_password="m:p", fail_count=9)
    assert evict_stale([c], max_fail_count=5) == []


def test_sanitize_remark_strips_provenance():
    assert "github" not in sanitize_remark("from github mirror").lower()
    assert sanitize_remark("Clean Node", prefix="⚡").startswith("⚡")


def test_b64_subscription_roundtrip():
    links = ["vless://u@h:443?type=tcp#a", "trojan://p@h:443?security=tls#b"]
    blob = encode_subscription_base64(links)
    decoded = try_b64_decode(blob)
    assert decoded is not None
    assert "vless://" in decoded
    body = decode_subscription_body(blob)
    assert "trojan://" in body


def test_score_latency():
    settings = {"testing": {}}
    assert score_latency(100, settings) == 100.0
    assert score_latency(5000, settings) < 50
    assert score_latency(0, settings) == 0.0


def test_invalid_port_rejected():
    link = "vless://u@host.example:0?type=tcp#x"
    assert parse_link(link) is None


def test_parse_tuic_and_hysteria():
    tuic = parse_link("tuic://11111111-2222-3333-4444-555555555555:pass@tuic.example:443?sni=tuic.example#t")
    assert tuic is not None and tuic.scheme == "tuic" and tuic.port == 443
    hy = parse_link("hysteria://pwd@hy.example:443?peer=hy.example#h")
    assert hy is not None and hy.scheme == "hysteria"
    socks = parse_link("socks5://user:pass@127.0.0.1:1080#s")
    assert socks is not None and socks.scheme == "socks"


def test_sort_by_latency():
    from v2agg.util.ranking import sort_by_latency

    a = ProxyConfig(scheme="vless", raw="vless://a@h:1", host="h", port=1, uuid_or_password="a", alive=True, latency_ms=500, score=80)
    b = ProxyConfig(scheme="vless", raw="vless://b@h:2", host="h", port=2, uuid_or_password="b", alive=True, latency_ms=100, score=50)
    a.ensure_fingerprint()
    b.ensure_fingerprint()
    ordered = sort_by_latency([a, b])
    assert ordered[0].latency_ms == 100


def test_fingerprint_normalizes_empty_security():
    c = ProxyConfig(scheme="vless", raw="vless://u@h:1", host="h", port=1, uuid_or_password="u", security="none")
    d = ProxyConfig(scheme="vless", raw="vless://u@h:1", host="h", port=1, uuid_or_password="u", security="")
    assert c.ensure_fingerprint() == d.ensure_fingerprint()


def test_no_tcp_fake_alive_for_hysteria_when_xray_mode():
    from v2agg.test.live import LiveTester

    settings = {
        "testing": {
            "mode": "xray",
            "accept_tcp_only": False,
            "xray_bin": "/nonexistent/xray-binary",
            "concurrency": 1,
        }
    }
    # Force xray path even if binary missing: patch available()
    tester = LiveTester(settings)
    tester._use_xray = True  # type: ignore[attr-defined]
    tester.xray.probe = lambda cfg, port: (None, None)  # type: ignore[method-assign]
    cfg = ProxyConfig(
        scheme="hysteria2",
        raw="hysteria2://p@1.2.3.4:443?sni=x",
        host="1.2.3.4",
        port=443,
        uuid_or_password="p",
    )
    cfg.ensure_fingerprint()
    out = tester.test_one(cfg)
    assert out.alive is False


def test_classify_usecase_from_real_latency():
    from v2agg.util.ranking import USECASE_DOWNLOAD, USECASE_GAME, USECASE_WEB, classify_usecase, remark_with_latency

    settings = {"publish": {"usecase": {"game_max_ms": 150, "web_max_ms": 500, "download_min_kbps": 400}}}
    game = ProxyConfig(scheme="vless", raw="vless://u@h:1", host="h", port=1, uuid_or_password="u", alive=True, latency_ms=80)
    web = ProxyConfig(scheme="vless", raw="vless://u@h:2", host="h", port=2, uuid_or_password="u", alive=True, latency_ms=300)
    dl = ProxyConfig(scheme="vless", raw="vless://u@h:3", host="h", port=3, uuid_or_password="u", alive=True, latency_ms=900)
    assert classify_usecase(game, settings) == USECASE_GAME
    assert classify_usecase(web, settings) == USECASE_WEB
    assert classify_usecase(dl, settings) == USECASE_DOWNLOAD
    # Mid latency + strong measured throughput → دانلود (real pipe, not random)
    pipe = ProxyConfig(
        scheme="vless",
        raw="vless://u@h:4",
        host="h",
        port=4,
        uuid_or_password="u",
        alive=True,
        latency_ms=320,
        throughput_kbps=1200,
    )
    assert classify_usecase(pipe, settings) == USECASE_DOWNLOAD
    # Dead / untested never get a fake tag
    dead = ProxyConfig(scheme="vless", raw="vless://u@h:5", host="h", port=5, uuid_or_password="u", alive=False, latency_ms=50)
    assert classify_usecase(dead, settings) == ""
    game.usecase = USECASE_GAME
    remark = remark_with_latency(game, "⚡", 1, settings=settings)
    assert "80ms" in remark and USECASE_GAME in remark

