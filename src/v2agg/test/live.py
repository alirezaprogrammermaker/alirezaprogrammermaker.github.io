from __future__ import annotations

import json
import shutil
import socket
import ssl
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

import httpx

from v2agg.models import ProxyConfig
from v2agg.util.logging import get_logger

logger = get_logger(__name__)

_SOCKS_WARNING_EMITTED = False


def socks_proxy_supported() -> bool:
    """httpx needs socksio to speak SOCKS5 used by local Xray probes."""
    try:
        import socksio  # noqa: F401

        return True
    except ImportError:
        return False


def _warn_missing_socksio_once() -> None:
    global _SOCKS_WARNING_EMITTED
    if _SOCKS_WARNING_EMITTED:
        return
    _SOCKS_WARNING_EMITTED = True
    logger.error(
        "socksio is not installed — httpx cannot use SOCKS5 proxies; "
        "all Xray/SOCKS live probes will fail. Install with: pip install 'httpx[socks]' socksio"
    )


def score_latency(latency_ms: float, settings: dict[str, Any]) -> float:
    t = settings.get("testing") or {}
    excellent = float(t.get("score_latency_excellent_ms", 400))
    good = float(t.get("score_latency_good_ms", 1200))
    ok = float(t.get("score_latency_ok_ms", 3000))
    if latency_ms <= 0:
        return 0.0
    if latency_ms <= excellent:
        return 100.0
    if latency_ms <= good:
        return 80.0 - (latency_ms - excellent) / max(good - excellent, 1) * 20
    if latency_ms <= ok:
        return 50.0 - (latency_ms - good) / max(ok - good, 1) * 30
    return max(0.0, 20.0 - (latency_ms - ok) / 1000.0)


def tcp_connect(host: str, port: int, timeout: float) -> float | None:
    """Return latency_ms on success, None on failure. Real TCP connect."""
    family = socket.AF_INET6 if ":" in host and not host.startswith("[") and host.count(":") > 1 else socket.AF_INET
    # Prefer getaddrinfo for dual-stack
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return None
    last_err: Exception | None = None
    for fam, socktype, proto, _, sockaddr in infos:
        sock = socket.socket(fam, socktype, proto)
        sock.settimeout(timeout)
        t0 = time.monotonic()
        try:
            sock.connect(sockaddr)
            latency = (time.monotonic() - t0) * 1000
            sock.close()
            return latency
        except Exception as exc:
            last_err = exc
            try:
                sock.close()
            except Exception:
                pass
    if last_err:
        logger.debug("tcp fail host=%s port=%s err=%s", host, port, last_err)
    return None


def tls_handshake(host: str, port: int, server_hostname: str | None, timeout: float) -> float | None:
    """TCP + TLS handshake probe (does not validate proxy auth)."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return None
    ctx = ssl.create_default_context()
    # Many proxy certs won't match; we still want handshake capability
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    for fam, socktype, proto, _, sockaddr in infos:
        sock = socket.socket(fam, socktype, proto)
        sock.settimeout(timeout)
        t0 = time.monotonic()
        try:
            sock.connect(sockaddr)
            with ctx.wrap_socket(sock, server_hostname=server_hostname or host) as ssock:
                ssock.do_handshake()
            return (time.monotonic() - t0) * 1000
        except Exception:
            try:
                sock.close()
            except Exception:
                pass
    return None


def build_xray_config(cfg: ProxyConfig, local_port: int) -> dict[str, Any] | None:
    """Build minimal Xray config with SOCKS inbound + single outbound."""
    outbound: dict[str, Any] | None = None
    scheme = cfg.scheme.lower()

    if scheme == "vmess":
        outbound = {
            "protocol": "vmess",
            "settings": {
                "vnext": [
                    {
                        "address": cfg.host,
                        "port": cfg.port,
                        "users": [{"id": cfg.uuid_or_password, "alterId": int(cfg.extra.get("aid") or 0), "security": "auto"}],
                    }
                ]
            },
            "streamSettings": _stream_settings(cfg),
        }
    elif scheme == "vless":
        outbound = {
            "protocol": "vless",
            "settings": {
                "vnext": [
                    {
                        "address": cfg.host,
                        "port": cfg.port,
                        "users": [{"id": cfg.uuid_or_password, "encryption": "none", "flow": cfg.extra.get("flow") or ""}],
                    }
                ]
            },
            "streamSettings": _stream_settings(cfg),
        }
    elif scheme == "trojan":
        outbound = {
            "protocol": "trojan",
            "settings": {"servers": [{"address": cfg.host, "port": cfg.port, "password": cfg.uuid_or_password}]},
            "streamSettings": _stream_settings(cfg),
        }
    elif scheme == "ss":
        method, _, password = cfg.uuid_or_password.partition(":")
        if not password:
            return None
        outbound = {
            "protocol": "shadowsocks",
            "settings": {
                "servers": [
                    {
                        "address": cfg.host,
                        "port": cfg.port,
                        "method": method,
                        "password": password,
                    }
                ]
            },
        }
    else:
        return None

    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "socks",
                "listen": "127.0.0.1",
                "port": local_port,
                "protocol": "socks",
                "settings": {"udp": False, "auth": "noauth"},
            }
        ],
        "outbounds": [outbound, {"protocol": "freedom", "tag": "direct"}],
    }


def _stream_settings(cfg: ProxyConfig) -> dict[str, Any]:
    network = (cfg.network or "tcp").lower()
    security = (cfg.security or "").lower()
    stream: dict[str, Any] = {"network": network if network else "tcp"}
    if security in {"tls", "xtls", "reality"}:
        stream["security"] = "tls" if security != "reality" else "reality"
        tls: dict[str, Any] = {"serverName": cfg.sni or cfg.host, "allowInsecure": True}
        if stream["security"] == "reality":
            tls = {
                "serverName": cfg.sni or cfg.host,
                "fingerprint": cfg.extra.get("fp") or "chrome",
                "publicKey": cfg.extra.get("pbk") or "",
                "shortId": cfg.extra.get("sid") or "",
            }
            stream["realitySettings"] = tls
        else:
            stream["tlsSettings"] = tls
    if network == "ws":
        stream["wsSettings"] = {"path": cfg.path or "/", "headers": {"Host": cfg.sni or cfg.host}}
    elif network == "grpc":
        stream["grpcSettings"] = {"serviceName": cfg.path or cfg.extra.get("serviceName") or ""}
    return stream


class XrayProbe:
    def __init__(self, xray_bin: str, workdir: Path, probe_url: str, timeout_sec: float) -> None:
        self.xray_bin = xray_bin
        self.workdir = workdir
        self.probe_url = probe_url
        self.timeout_sec = timeout_sec
        self.workdir.mkdir(parents=True, exist_ok=True)

    def available(self) -> bool:
        if Path(self.xray_bin).exists():
            return True
        return shutil.which(self.xray_bin) is not None

    def probe(self, cfg: ProxyConfig, local_port: int) -> float | None:
        conf = build_xray_config(cfg, local_port)
        if conf is None:
            return None
        conf_path = self.workdir / f"cfg-{local_port}.json"
        conf_path.write_text(json.dumps(conf), encoding="utf-8")
        proc: subprocess.Popen[bytes] | None = None
        try:
            proc = subprocess.Popen(
                [self.xray_bin, "run", "-c", str(conf_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # Give xray a moment to bind
            time.sleep(0.35)
            if proc.poll() is not None:
                return None
            proxy = f"socks5://127.0.0.1:{local_port}"
            t0 = time.monotonic()
            with httpx.Client(
                proxy=proxy,
                timeout=self.timeout_sec,
                follow_redirects=True,
                verify=False,
            ) as client:
                resp = client.get(self.probe_url)
                if resp.status_code >= 500:
                    return None
            return (time.monotonic() - t0) * 1000
        except ImportError as exc:
            # Missing socksio surfaces as ImportError from httpx SOCKS transport
            _warn_missing_socksio_once()
            logger.debug("xray probe fail fp=%s err=%s", cfg.fingerprint, exc)
            return None
        except Exception as exc:
            logger.debug("xray probe fail fp=%s err=%s", cfg.fingerprint, exc)
            return None
        finally:
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
            try:
                conf_path.unlink(missing_ok=True)
            except Exception:
                pass


class LiveTester:
    """Real connectivity tests — never fake-pass."""

    # Schemes we can verify through Xray SOCKS→HTTP probe
    XRAY_SCHEMES = frozenset({"vmess", "vless", "trojan", "ss"})
    # Schemes we can verify by speaking the proxy protocol directly via httpx
    HTTPX_PROXY_SCHEMES = frozenset({"socks", "http"})

    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings
        t = settings.get("testing") or {}
        self.mode = (t.get("mode") or "auto").lower()
        self.tcp_timeout = float(t.get("tcp_timeout_sec", 5))
        self.tls_timeout = float(t.get("tls_timeout_sec", 8))
        self.xray_timeout = float(t.get("xray_timeout_sec", 20))
        self.concurrency = int(t.get("concurrency", 16))
        self.probe_url = t.get("probe_url") or "https://www.cloudflare.com/cdn-cgi/trace"
        self.local_base = int(t.get("local_socks_base_port", 21000))
        # When Xray is available, never treat "TCP port open" as proof of a working proxy
        self.accept_tcp_only = bool(t.get("accept_tcp_only", False))
        self.xray = XrayProbe(
            xray_bin=t.get("xray_bin") or "xray",
            workdir=Path(t.get("xray_workdir") or "state/runtime/xray"),
            probe_url=self.probe_url,
            timeout_sec=self.xray_timeout,
        )
        self._use_xray = self.mode == "xray" or (self.mode == "auto" and self.xray.available())
        if self._use_xray:
            logger.info("live test mode=xray binary=%s accept_tcp_only=%s", self.xray.xray_bin, self.accept_tcp_only)
        else:
            logger.info("live test mode=tcp/tls (xray unavailable or disabled)")
        if not socks_proxy_supported():
            _warn_missing_socksio_once()

    def _httpx_proxy_probe(self, cfg: ProxyConfig) -> float | None:
        """Probe socks/http proxies by fetching probe_url through them."""
        userinfo = cfg.uuid_or_password or ""
        auth = ""
        if userinfo and userinfo != ":":
            auth = f"{userinfo}@"
        if cfg.scheme == "socks":
            proxy = f"socks5://{auth}{cfg.host}:{cfg.port}"
        else:
            proxy = f"http://{auth}{cfg.host}:{cfg.port}"
        try:
            t0 = time.monotonic()
            with httpx.Client(proxy=proxy, timeout=self.xray_timeout, follow_redirects=True, verify=False) as client:
                resp = client.get(self.probe_url)
                if resp.status_code >= 500:
                    return None
            return (time.monotonic() - t0) * 1000
        except ImportError:
            _warn_missing_socksio_once()
            return None
        except Exception as exc:
            logger.debug("httpx proxy probe fail fp=%s err=%s", cfg.fingerprint, type(exc).__name__)
            return None

    def test_one(self, cfg: ProxyConfig, worker_idx: int = 0) -> ProxyConfig:
        cfg.last_test_ts = time.time()
        latency: float | None = None
        scheme = (cfg.scheme or "").lower()

        if self._use_xray and scheme in self.XRAY_SCHEMES:
            local_port = self.local_base + (worker_idx % 5000)
            latency = self.xray.probe(cfg, local_port)
        elif scheme in self.HTTPX_PROXY_SCHEMES:
            latency = self._httpx_proxy_probe(cfg)
        elif self._use_xray and scheme not in self.XRAY_SCHEMES:
            # hysteria2/tuic/… — Xray outbound not built; TCP-open is NOT a real pass
            if self.accept_tcp_only:
                latency = tcp_connect(cfg.host, cfg.port, self.tcp_timeout)
            else:
                latency = None
                logger.debug("skip unverified scheme=%s (no real proxy probe)", scheme)
        else:
            # Pure TCP/TLS mode (no xray) — best-effort reachability only
            latency = tcp_connect(cfg.host, cfg.port, self.tcp_timeout)
            if latency is not None and (cfg.security or "").lower() in {"tls", "xtls", "reality"}:
                tls_lat = tls_handshake(cfg.host, cfg.port, cfg.sni or cfg.host, self.tls_timeout)
                if tls_lat is None:
                    latency = None
                else:
                    latency = max(latency, tls_lat)

        if latency is None:
            cfg.alive = False
            cfg.latency_ms = None
            cfg.score = 0.0
            cfg.fail_count += 1
            return cfg

        cfg.alive = True
        cfg.latency_ms = latency
        cfg.score = score_latency(latency, self.settings)
        cfg.fail_count = 0
        cfg.last_ok_ts = time.time()
        return cfg

    def test_many(
        self,
        configs: list[ProxyConfig],
        *,
        should_stop: Callable[[], bool] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        skip_fingerprints: set[str] | None = None,
    ) -> list[ProxyConfig]:
        skip = skip_fingerprints or set()
        pending = [c for c in configs if c.ensure_fingerprint() not in skip]
        total = len(pending)
        done = 0
        results: list[ProxyConfig] = []

        # Preserve already-tested skipped configs as-is from input
        already = [c for c in configs if c.ensure_fingerprint() in skip]
        results.extend(already)

        with ThreadPoolExecutor(max_workers=max(1, self.concurrency)) as pool:
            futures = {}
            for idx, cfg in enumerate(pending):
                if should_stop and should_stop():
                    break
                futures[pool.submit(self.test_one, cfg, idx)] = cfg

            for fut in as_completed(futures):
                if should_stop and should_stop():
                    break
                try:
                    results.append(fut.result())
                except Exception as exc:
                    cfg = futures[fut]
                    cfg.alive = False
                    cfg.fail_count += 1
                    results.append(cfg)
                    logger.debug("test exception fp=%s err=%s", cfg.fingerprint, exc)
                done += 1
                if on_progress and done % 25 == 0:
                    on_progress(done, total)

        # Cancel remaining if stopping
        for fut in futures:
            if not fut.done():
                fut.cancel()

        logger.info("tested=%d alive=%d", done, sum(1 for c in results if c.alive))
        return results
