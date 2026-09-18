from __future__ import annotations

import base64
import json
import re
from typing import Callable
from urllib.parse import parse_qs, unquote, urlparse

from v2agg.models import ALLOWED_SCHEMES, ProxyConfig, is_valid_host
from v2agg.util.logging import get_logger

logger = get_logger(__name__)

# Share-link schemes commonly used by V2Ray/Xray/sing-box clients
_KNOWN_SCHEMES = set(ALLOWED_SCHEMES) | {
    "hysteria",
    "tuic",
    "wireguard",
    "wg",
    "socks",
    "socks5",
    "http",
    "https",
    "juicity",
    "anytls",
    "brook",
    "naive",
    "mieru",
}

_SCHEME_RE = re.compile(
    r"(?P<link>(?:"
    + "|".join(sorted(_KNOWN_SCHEMES, key=len, reverse=True))
    + r")://[^\s<>\"']+)",
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
        if "://" not in line:
            continue
        scheme = line.lower().split("://", 1)[0]
        if scheme in _KNOWN_SCHEMES and line not in found:
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


def _vmess_security(tls_val: object) -> str:
    """Normalize vmess `tls` field (bool / string) to xray security name."""
    if isinstance(tls_val, bool):
        return "tls" if tls_val else ""
    s = str(tls_val or "").strip().lower()
    if s in {"1", "true", "yes", "on"}:
        return "tls"
    if s in {"", "0", "false", "no", "none", "off"}:
        return ""
    return s


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
        security=_vmess_security(obj.get("tls")),
        sni=str(obj.get("sni") or obj.get("host") or ""),
        path=str(obj.get("path") or ""),
        extra={
            "aid": obj.get("aid"),
            "type": obj.get("type"),
            "v": obj.get("v"),
            # WS/HTTP Host header — must stay separate from server address / SNI
            "host": obj.get("host") or "",
            "fp": obj.get("fp") or "",
            "alpn": obj.get("alpn") or "",
        },
    )
    cfg.ensure_fingerprint()
    return cfg


def _normalize_scheme(scheme: str) -> str:
    s = scheme.lower()
    if s == "hy2":
        return "hysteria2"
    if s == "wg":
        return "wireguard"
    if s == "socks5":
        return "socks"
    if s == "https":
        return "http"
    return s


def parse_uri_style(link: str, scheme: str) -> ProxyConfig | None:
    """Parse URI-style share links (vless/trojan/ss/hysteria2/tuic/…)."""
    try:
        parsed = urlparse(link)
    except Exception:
        return None

    raw_scheme = parsed.scheme.lower()
    want = scheme.lower()
    aliases = {
        "hysteria2": {"hysteria2", "hy2"},
        "wireguard": {"wireguard", "wg"},
        "socks": {"socks", "socks5"},
        "http": {"http", "https"},
    }
    allowed = aliases.get(want, {want})
    if raw_scheme not in allowed and raw_scheme != want:
        return None

    host = parsed.hostname or ""
    port = parsed.port or 0
    user = unquote(parsed.username or "")
    password = unquote(parsed.password or "") if parsed.password else ""
    remark = unquote(parsed.fragment or "")
    qs = {k: v[0] if v else "" for k, v in parse_qs(parsed.query).items()}

    if want == "ss":
        # ss://METHOD:PASSWORD@host:port or ss://base64@host:port
        if not user and parsed.netloc:
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

    # Default ports for schemes that often omit them
    if not port:
        defaults = {
            "http": 80 if raw_scheme == "http" else 443,
            "socks": 1080,
            "hysteria": 443,
            "hysteria2": 443,
            "tuic": 443,
            "wireguard": 51820,
            "juicity": 443,
            "anytls": 443,
            "naive": 443,
        }
        port = defaults.get(want, 0)

    uuid_or_password = user if want in {
        "vless",
        "trojan",
        "hysteria2",
        "hysteria",
        "tuic",
        "juicity",
        "anytls",
        "brook",
        "mieru",
    } else (password or user)

    if want == "trojan":
        uuid_or_password = user or password
    if want == "ss":
        uuid_or_password = f"{user}:{password}" if user and password else (password or user)
    if want in {"socks", "http", "naive"}:
        uuid_or_password = f"{user}:{password}" if user or password else ""
    if want == "tuic":
        # tuic://uuid:password@host:port
        uuid_or_password = f"{user}:{password}" if password else user
    if want == "wireguard":
        uuid_or_password = user or qs.get("private_key") or qs.get("privateKey") or ""

    if not host or not port:
        return None

    net = qs.get("type") or qs.get("network") or ""
    security = qs.get("security") or qs.get("tls") or ""
    sni = qs.get("sni") or qs.get("peer") or ""
    path = qs.get("path") or ""
    # Keep WS/HTTP Host header distinct from SNI (CDN setups often differ)
    host_header = qs.get("host") or ""
    if not sni and host_header:
        sni = host_header

    normalized_scheme = _normalize_scheme(want if want != "hy2" else "hysteria2")
    if want in {"hy2", "hysteria2"}:
        normalized_scheme = "hysteria2"
    if want in {"wg", "wireguard"}:
        normalized_scheme = "wireguard"
    if want in {"socks", "socks5"}:
        normalized_scheme = "socks"
    if want in {"http", "https"}:
        normalized_scheme = "http"

    extra = {
        k: v
        for k, v in qs.items()
        if k not in {"type", "network", "security", "tls", "sni", "peer", "path"}
    }
    if host_header:
        extra["host"] = host_header

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
        extra=extra,
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
    "hysteria": lambda l: parse_uri_style(l, "hysteria"),
    "tuic": lambda l: parse_uri_style(l, "tuic"),
    "wireguard": lambda l: parse_uri_style(l, "wireguard"),
    "wg": lambda l: parse_uri_style(l, "wireguard"),
    "socks": lambda l: parse_uri_style(l, "socks"),
    "socks5": lambda l: parse_uri_style(l, "socks"),
    "http": lambda l: parse_uri_style(l, "http"),
    "https": lambda l: parse_uri_style(l, "http"),
    "juicity": lambda l: parse_uri_style(l, "juicity"),
    "anytls": lambda l: parse_uri_style(l, "anytls"),
    "brook": lambda l: parse_uri_style(l, "brook"),
    "naive": lambda l: parse_uri_style(l, "naive"),
    "mieru": lambda l: parse_uri_style(l, "mieru"),
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
