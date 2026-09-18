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
    assert cfg.ensure_fingerprint()


def test_parse_vless():
    link = (
        "vless://11111111-2222-3333-4444-555555555555@example.com:443"
        "?encryption=none&security=tls&type=ws&path=%2Fpath&sni=example.com#MyNode"
    )
    cfg = parse_link(link)
    assert cfg is not None
    assert cfg.scheme == "vless"
    assert cfg.host == "example.com"
    assert cfg.port == 443
    assert cfg.sni == "example.com"


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
