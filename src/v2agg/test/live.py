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
from v2agg.util.ranking import classify_usecase
from v2agg.util.logging import get_logger

logger = get_logger(__name__)

_SOCKS_WARNING_EMITTED = False


def socks_proxy_supported() -> bool:
    """httpx needs the socksio extra to speak SOCKS5 (used for Xray local probes)."""
    try:
        import socksio  # noqa: F401

        return True
    except ImportError:
        return False


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
    if network in {"", "none"}:
        network = "tcp"
    security = (cfg.security or "").lower()
    stream: dict[str, Any] = {"network": network}
    host_header = str(cfg.extra.get("host") or cfg.sni or cfg.host or "")
    if security in {"tls", "xtls", "reality"}:
        stream["security"] = "tls" if security != "reality" else "reality"
        if stream["security"] == "reality":
            stream["realitySettings"] = {
                "serverName": cfg.sni or cfg.host,
                "fingerprint": cfg.extra.get("fp") or "chrome",
                "publicKey": cfg.extra.get("pbk") or "",
                "shortId": cfg.extra.get("sid") or "",
                "spiderX": cfg.extra.get("spx") or "",
            }
        else:
            stream["tlsSettings"] = {
                "serverName": cfg.sni or host_header or cfg.host,
                "allowInsecure": True,
                "fingerprint": cfg.extra.get("fp") or "chrome",
                "alpn": ["h2", "http/1.1"],
            }
    if network == "ws":
        stream["wsSettings"] = {
            "path": cfg.path or cfg.extra.get("path") or "/",
            "headers": {"Host": host_header or cfg.host},
        }
    elif network in {"grpc", "gun"}:
        stream["network"] = "grpc"
        stream["grpcSettings"] = {
            "serviceName": cfg.path or cfg.extra.get("serviceName") or cfg.extra.get("servicename") or ""
        }
    elif network == "h2":
        stream["httpSettings"] = {
            "path": cfg.path or "/",
            "host": [host_header] if host_header else [cfg.host],
        }
    elif network == "httpupgrade":
        stream["httpupgradeSettings"] = {
            "path": cfg.path or "/",
            "host": host_header or cfg.host,
        }
    elif network == "splithttp" or network == "xhttp":
        stream["network"] = "xhttp" if network == "xhttp" else network
        key = "xhttpSettings" if network == "xhttp" else "splithttpSettings"
        stream[key] = {"path": cfg.path or "/", "host": host_header or cfg.host}
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

    def probe(self, cfg: ProxyConfig, local_port: int) -> tuple[float | None, float | None]:
        """Return (latency_ms, throughput_kbps). Either may be None."""
        conf = build_xray_config(cfg, local_port)
        if conf is None:
            return None, None
        conf_path = self.workdir / f"cfg-{local_port}.json"
        conf_path.write_text(json.dumps(conf), encoding="utf-8")
        proc: subprocess.Popen[bytes] | None = None
        try:
            proc = subprocess.Popen(
                [self.xray_bin, "run", "-c", str(conf_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # Give xray time to bind (busy runners need a bit more)
            time.sleep(0.55)
            if proc.poll() is not None:
                time.sleep(0.35)
                if proc.poll() is not None:
                    return None, None
            proxy = f"socks5://127.0.0.1:{local_port}"
            latency: float | None = None
            throughput: float | None = None
            with httpx.Client(
                proxy=proxy,
                timeout=self.timeout_sec,
                follow_redirects=True,
                verify=False,
            ) as client:
                t0 = time.monotonic()
                resp = client.get(self.probe_url)
                if resp.status_code >= 500:
                    return None, None
                latency = (time.monotonic() - t0) * 1000
                # Real throughput sample (~100 KiB) for download suitability.
                # Short timeout so a hung speed test never stalls the worker pool.
                try:
                    t1 = time.monotonic()
                    dl = client.get(
                        "https://speed.cloudflare.com/__down?bytes=102400",
                        timeout=min(6.0, float(self.timeout_sec)),
                    )
                    elapsed = max(time.monotonic() - t1, 0.001)
                    if dl.status_code < 500 and dl.content:
                        throughput = (len(dl.content) * 8 / 1000.0) / elapsed  # kbps
                except Exception:
                    throughput = None
            return latency, throughput
        except Exception as exc:
            global _SOCKS_WARNING_EMITTED
            # Missing socksio makes EVERY xray probe look "dead" — surface loudly once.
            if isinstance(exc, ImportError) and "socks" in str(exc).lower():
                if not _SOCKS_WARNING_EMITTED:
                    logger.error(
                        "httpx SOCKS support missing (%s) — install httpx[socks]/socksio or all live probes fail",
                        exc,
                    )
                    _SOCKS_WARNING_EMITTED = True
            else:
                logger.debug("xray probe fail fp=%s err=%s", cfg.fingerprint, exc)
            return None, None
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


class Hysteria2Probe:
    """Real hysteria2 client probe via local SOCKS → HTTP (not TCP-open fakes)."""

    def __init__(self, hy_bin: str, workdir: Path, probe_url: str, timeout_sec: float) -> None:
        self.hy_bin = hy_bin
        self.workdir = workdir
        self.probe_url = probe_url
        self.timeout_sec = timeout_sec
        self.workdir.mkdir(parents=True, exist_ok=True)

    def available(self) -> bool:
        if Path(self.hy_bin).exists():
            return True
        return shutil.which(self.hy_bin) is not None

    def build_client_config(self, cfg: ProxyConfig, local_port: int) -> dict[str, Any] | None:
        scheme = (cfg.scheme or "").lower()
        if scheme not in {"hysteria2", "hy2", "hysteria"}:
            return None
        auth = cfg.uuid_or_password or ""
        if not auth:
            return None
        insecure_raw = cfg.extra.get("insecure")
        if insecure_raw is None or str(insecure_raw).strip() == "":
            # Public share links often use self-signed certs
            insecure = True
        else:
            insecure = str(insecure_raw).lower() in {"1", "true", "yes"}
        conf: dict[str, Any] = {
            "server": f"{cfg.host}:{cfg.port}",
            "auth": auth,
            "tls": {"sni": cfg.sni or cfg.host, "insecure": insecure},
            "socks5": {"listen": f"127.0.0.1:{local_port}"},
        }
        obfs = cfg.extra.get("obfs") or ""
        obfs_password = cfg.extra.get("obfs-password") or cfg.extra.get("obfs_password") or ""
        if obfs:
            conf["obfs"] = {"type": obfs, "salamander": {"password": obfs_password}}
        return conf

    def probe(self, cfg: ProxyConfig, local_port: int) -> tuple[float | None, float | None]:
        conf = self.build_client_config(cfg, local_port)
        if conf is None:
            return None, None
        conf_path = self.workdir / f"hy2-{local_port}.json"
        conf_path.write_text(json.dumps(conf), encoding="utf-8")
        proc: subprocess.Popen[bytes] | None = None
        try:
            proc = subprocess.Popen(
                [self.hy_bin, "-c", str(conf_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(0.7)
            if proc.poll() is not None:
                time.sleep(0.4)
                if proc.poll() is not None:
                    return None, None
            proxy = f"socks5://127.0.0.1:{local_port}"
            latency: float | None = None
            throughput: float | None = None
            with httpx.Client(
                proxy=proxy,
                timeout=self.timeout_sec,
                follow_redirects=True,
                verify=False,
            ) as client:
                t0 = time.monotonic()
                resp = client.get(self.probe_url)
                if resp.status_code >= 500:
                    return None, None
                latency = (time.monotonic() - t0) * 1000
                try:
                    t1 = time.monotonic()
                    dl = client.get(
                        "https://speed.cloudflare.com/__down?bytes=102400",
                        timeout=min(6.0, float(self.timeout_sec)),
                    )
                    elapsed = max(time.monotonic() - t1, 0.001)
                    if dl.status_code < 500 and dl.content:
                        throughput = (len(dl.content) * 8 / 1000.0) / elapsed
                except Exception:
                    throughput = None
            return latency, throughput
        except Exception as exc:
            logger.debug("hy2 probe fail fp=%s err=%s", cfg.fingerprint, type(exc).__name__)
            return None, None
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
    # Schemes verified with hysteria2 client (real QUIC path — not TCP-open)
    HY2_SCHEMES = frozenset({"hysteria2", "hy2", "hysteria"})
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
        self.hy2 = Hysteria2Probe(
            hy_bin=t.get("hysteria_bin") or "bin/hysteria",
            workdir=Path(t.get("hysteria_workdir") or "state/runtime/hysteria"),
            probe_url=self.probe_url,
            timeout_sec=float(t.get("hysteria_timeout_sec") or self.xray_timeout),
        )
        self._use_xray = self.mode == "xray" or (self.mode == "auto" and self.xray.available())
        self._use_hy2 = self.hy2.available()
        if self._use_xray and not socks_proxy_supported():
            logger.error(
                "Xray binary present but httpx[socks]/socksio is NOT installed — "
                "SOCKS probes cannot run; refusing fake TCP alives"
            )
            # Keep xray mode (don't fall back to TCP fakes); probes will hard-fail until deps fixed
        if self._use_xray:
            logger.info(
                "live test mode=xray binary=%s accept_tcp_only=%s socksio=%s hy2=%s",
                self.xray.xray_bin,
                self.accept_tcp_only,
                socks_proxy_supported(),
                self._use_hy2,
            )
        else:
            logger.info("live test mode=tcp/tls (xray unavailable or disabled) hy2=%s", self._use_hy2)
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
        except Exception as exc:
            logger.debug("httpx proxy probe fail fp=%s err=%s", cfg.fingerprint, type(exc).__name__)
            return None

    def test_one(self, cfg: ProxyConfig, worker_idx: int = 0) -> ProxyConfig:
        cfg.last_test_ts = time.time()
        latency: float | None = None
        throughput: float | None = None
        scheme = (cfg.scheme or "").lower()

        if self._use_xray and scheme in self.XRAY_SCHEMES:
            local_port = self.local_base + (worker_idx % 5000)
            latency, throughput = self.xray.probe(cfg, local_port)
        elif self._use_hy2 and scheme in self.HY2_SCHEMES:
            local_port = self.local_base + 4000 + (worker_idx % 4000)
            latency, throughput = self.hy2.probe(cfg, local_port)
        elif scheme in self.HTTPX_PROXY_SCHEMES:
            latency = self._httpx_proxy_probe(cfg)
        elif scheme in self.HY2_SCHEMES and not self._use_hy2:
            if self.accept_tcp_only:
                latency = tcp_connect(cfg.host, cfg.port, self.tcp_timeout)
            else:
                latency = None
                logger.debug("skip hy2 — hysteria binary missing")
        elif self._use_xray and scheme not in self.XRAY_SCHEMES:
            # tuic/wireguard/… — no real probe built yet
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
            cfg.throughput_kbps = None
            cfg.usecase = ""
            cfg.score = 0.0
            cfg.fail_count += 1
            return cfg

        cfg.alive = True
        cfg.latency_ms = latency
        cfg.throughput_kbps = throughput
        cfg.score = score_latency(latency, self.settings)
        cfg.fail_count = 0
        cfg.last_ok_ts = time.time()
        cfg.usecase = classify_usecase(cfg, self.settings)
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
