from __future__ import annotations

import base64
import json
import re
from typing import Callable
from urllib.parse import parse_qs, unquote, urlparse

from v2agg.models import ProxyConfig, is_valid_host
from v2agg.util.logging import get_logger

logger = get_logger(__name__)

_SCHEME_RE = re.compile(
    r"(?P<link>(?:vmess|vless|trojan|ss|ssr|hysteria2|hy2)://[^\s<>\"']+)",
    re.IGNORECASE,
)


def extract_links(text: str) -> list[str]:
    if not text:
        return []
    found: list[str] = []
    for m in _SCHEME_RE.finditer(text):
        link = m.group("link").rstrip("),.;]'\"")
        found.append(link)
    # Also accept one-link-per-line without regex false negatives
    for line in text.splitlines():
        line = line.strip()
        if "://" in line and line.lower().split("://", 1)[0] in {
            "vmess",
            "vless",
            "trojan",
            "ss",
            "ssr",
            "hysteria2",
            "hy2",
        }:
            if line not in found:
                found.append(line)
    return found


def _b64json(payload: str) -> dict | None:
    raw = payload.strip()
    pad = (-len(raw)) % 4
    try:
        data = base64.b64decode(raw + ("=" * pad))
        obj = json.loads(data.decode("utf-8", errors="ignore"))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def parse_vmess(link: str) -> ProxyConfig | None:
    if not link.lower().startswith("vmess://"):
        return None
    payload = link[8:]
    obj = _b64json(payload)
    if not obj:
        return None
    host = str(obj.get("add") or obj.get("host") or "").strip()
    try:
        port = int(obj.get("port") or 0)
    except (TypeError, ValueError):
        return None
    uuid = str(obj.get("id") or "").strip()
    if not host or not port or not uuid:
        return None
    cfg = ProxyConfig(
        scheme="vmess",
        raw=link.strip(),
        host=host,
        port=port,
        uuid_or_password=uuid,
        remark=str(obj.get("ps") or ""),
        network=str(obj.get("net") or ""),
        security=str(obj.get("tls") or ""),
        sni=str(obj.get("sni") or obj.get("host") or ""),
        path=str(obj.get("path") or ""),
        extra={"aid": obj.get("aid"), "type": obj.get("type"), "v": obj.get("v")},
    )
    cfg.ensure_fingerprint()
    return cfg


def parse_uri_style(link: str, scheme: str) -> ProxyConfig | None:
    """Parse vless/trojan/ss/hysteria2 style URIs."""
    try:
        parsed = urlparse(link)
    except Exception:
        return None
    if parsed.scheme.lower() not in {scheme, "hy2"} and scheme != parsed.scheme.lower():
        # allow hy2 alias for hysteria2
        if not (scheme == "hysteria2" and parsed.scheme.lower() == "hy2"):
            if parsed.scheme.lower() != scheme:
                return None

    host = parsed.hostname or ""
    port = parsed.port or 0
    user = unquote(parsed.username or "")
    password = unquote(parsed.password or "") if parsed.password else ""
    remark = unquote(parsed.fragment or "")
    qs = {k: v[0] if v else "" for k, v in parse_qs(parsed.query).items()}

    if scheme == "ss":
        # ss://METHOD:PASSWORD@host:port or ss://base64@host:port
        if not user and parsed.netloc:
            # ss://BASE64#remark
            b64part = link[5:].split("#", 1)[0]
            if "@" in b64part:
                userinfo, hostport = b64part.rsplit("@", 1)
                try:
                    pad = (-len(userinfo)) % 4
                    decoded = base64.b64decode(userinfo + ("=" * pad)).decode("utf-8", errors="ignore")
                    if ":" in decoded:
                        method, password = decoded.split(":", 1)
                        user = method
                    else:
                        password = decoded
                except Exception:
                    password = userinfo
                if ":" in hostport:
                    host, port_s = hostport.rsplit(":", 1)
                    host = host.strip("[]")
                    try:
                        port = int(port_s)
                    except ValueError:
                        port = 0
            else:
                try:
                    pad = (-len(b64part)) % 4
                    decoded = base64.b64decode(b64part + ("=" * pad)).decode("utf-8", errors="ignore")
                    # method:pass@host:port
                    if "@" in decoded:
                        userinfo, hostport = decoded.rsplit("@", 1)
                        if ":" in userinfo:
                            user, password = userinfo.split(":", 1)
                        if ":" in hostport:
                            host, port_s = hostport.rsplit(":", 1)
                            host = host.strip("[]")
                            port = int(port_s)
                except Exception:
                    return None
        else:
            password = password or user
            user = user  # method may be in username for METHOD:PASS form via user:pass

    uuid_or_password = user if scheme in {"vless", "trojan", "hysteria2", "hy2"} else (password or user)
    if scheme == "trojan":
        uuid_or_password = user or password
    if scheme == "ss":
        uuid_or_password = f"{user}:{password}" if user and password else (password or user)

    if not host or not port:
        return None

    net = qs.get("type") or qs.get("network") or ""
    security = qs.get("security") or qs.get("tls") or ""
    sni = qs.get("sni") or qs.get("peer") or qs.get("host") or ""
    path = qs.get("path") or ""

    normalized_scheme = "hysteria2" if scheme in {"hysteria2", "hy2"} else scheme
    cfg = ProxyConfig(
        scheme=normalized_scheme,
        raw=link.strip(),
        host=host,
        port=int(port),
        uuid_or_password=uuid_or_password,
        remark=remark,
        network=net,
        security=security,
        sni=sni,
        path=path,
        extra={k: v for k, v in qs.items() if k not in {"type", "network", "security", "tls", "sni", "peer", "host", "path"}},
    )
    cfg.ensure_fingerprint()
    return cfg


_PARSERS: dict[str, Callable[[str], ProxyConfig | None]] = {
    "vmess": parse_vmess,
    "vless": lambda l: parse_uri_style(l, "vless"),
    "trojan": lambda l: parse_uri_style(l, "trojan"),
    "ss": lambda l: parse_uri_style(l, "ss"),
    "ssr": lambda l: parse_uri_style(l, "ssr"),
    "hysteria2": lambda l: parse_uri_style(l, "hysteria2"),
    "hy2": lambda l: parse_uri_style(l, "hysteria2"),
}


def parse_link(link: str) -> ProxyConfig | None:
    link = (link or "").strip()
    if not link or "://" not in link:
        return None
    scheme = link.split("://", 1)[0].lower()
    parser = _PARSERS.get(scheme)
    if not parser:
        return None
    try:
        cfg = parser(link)
    except Exception as exc:
        logger.debug("parse failed scheme=%s err=%s", scheme, exc)
        return None
    if cfg is None:
        return None
    if not is_valid_host(cfg.host):
        return None
    if not (1 <= cfg.port <= 65535):
        return None
    cfg.ensure_fingerprint()
    return cfg


def parse_many(text: str) -> list[ProxyConfig]:
    out: list[ProxyConfig] = []
    for link in extract_links(text):
        cfg = parse_link(link)
        if cfg:
            out.append(cfg)
    return out
