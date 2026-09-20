from __future__ import annotations

import json
import shutil
import socket
import ssl
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from v2agg.models import ProxyConfig
from v2agg.util.logging import get_logger

logger = get_logger(__name__)

HY2_SCHEMES = frozenset({"hysteria2", "hy2"})


@dataclass
class ProbeResult:
    """Outcome of a real connectivity probe. Never invent success or Mbps."""

    latency_ms: float
    throughput_mbps: float | None = None
    throughput_attempted: bool = False


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


def score_throughput(mbps: float, settings: dict[str, Any]) -> float:
    """Map measured Mbps to 0–100. Knees: ≥8 → 100, ≥3 → ~70, ≥1 → ~40."""
    t = settings.get("testing") or {}
    excellent = float(t.get("score_throughput_excellent_mbps", 8))
    good = float(t.get("score_throughput_good_mbps", 3))
    ok = float(t.get("score_throughput_ok_mbps", 1))
    if mbps <= 0:
        return 0.0
    if mbps >= excellent:
        return 100.0
    if mbps >= good:
        return 70.0 + (mbps - good) / max(excellent - good, 0.01) * 30.0
    if mbps >= ok:
        return 40.0 + (mbps - ok) / max(good - ok, 0.01) * 30.0
    return max(0.0, 40.0 * (mbps / max(ok, 0.01)))


def combined_score(
    latency_ms: float,
    throughput_mbps: float | None,
    settings: dict[str, Any],
    *,
    throughput_attempted: bool = True,
) -> float:
    """Blend latency + throughput.

    Default: ``score = 0.65 * latency_score + 0.35 * throughput_score``.
    If throughput is disabled or was not attempted (TCP-only path), return
    latency_score unchanged. If a real proxy probe succeeded but the Mbps
    download failed, apply ``score_throughput_missing_penalty`` (default 20%)
    to the latency score — never fake Mbps.
    """
    lat = score_latency(latency_ms, settings)
    t = settings.get("testing") or {}
    if not bool(t.get("throughput_enabled", True)) or not throughput_attempted:
        return lat
    lw = float(t.get("score_latency_weight", 0.65))
    tw = float(t.get("score_throughput_weight", 0.35))
    total = lw + tw
    if total <= 0:
        lw, tw = 0.65, 0.35
    else:
        lw, tw = lw / total, tw / total
    if throughput_mbps is None:
        penalty = float(t.get("score_throughput_missing_penalty", 0.20))
        penalty = min(max(penalty, 0.0), 0.9)
        return lat * (1.0 - penalty)
    return lw * lat + tw * score_throughput(throughput_mbps, settings)


def tcp_connect(host: str, port: int, timeout: float) -> float | None:
    """Return latency_ms on success, None on failure. Real TCP connect."""
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


def _throughput_url(template: str, nbytes: int) -> str:
    if "{bytes}" in template:
        return template.replace("{bytes}", str(int(nbytes)))
    parts = urlsplit(template)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    if "bytes" not in q:
        q["bytes"] = str(int(nbytes))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), parts.fragment))


def measure_throughput(
    proxy: str,
    url: str,
    timeout_sec: float,
    *,
    min_bytes: int = 1024,
) -> float | None:
    """Download a small payload through SOCKS and return Mbps, or None on failure."""
    try:
        t0 = time.monotonic()
        with httpx.Client(
            proxy=proxy,
            timeout=timeout_sec,
            follow_redirects=True,
            verify=False,
        ) as client:
            resp = client.get(url)
            if resp.status_code >= 400:
                return None
            data = resp.content
        elapsed = time.monotonic() - t0
        n = len(data)
        if elapsed <= 0 or n < min_bytes:
            return None
        return (n * 8.0) / (elapsed * 1_000_000.0)
    except Exception as exc:
        logger.debug("throughput probe fail proxy=%s err=%s", proxy, exc)
        return None


def http_probe_via_socks(
    proxy: str,
    probe_url: str,
    timeout_sec: float,
    *,
    throughput_url: str | None = None,
    throughput_timeout_sec: float = 15.0,
    throughput_min_bytes: int = 1024,
) -> ProbeResult | None:
    try:
        t0 = time.monotonic()
        with httpx.Client(
            proxy=proxy,
            timeout=timeout_sec,
            follow_redirects=True,
            verify=False,
        ) as client:
            resp = client.get(probe_url)
            if resp.status_code >= 500:
                return None
        latency_ms = (time.monotonic() - t0) * 1000
    except Exception:
        return None

    mbps: float | None = None
    attempted = False
    if throughput_url:
        attempted = True
        mbps = measure_throughput(
            proxy,
            throughput_url,
            throughput_timeout_sec,
            min_bytes=throughput_min_bytes,
        )
    return ProbeResult(latency_ms=latency_ms, throughput_mbps=mbps, throughput_attempted=attempted)


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


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def build_singbox_hysteria2_config(cfg: ProxyConfig, local_port: int) -> dict[str, Any] | None:
    """SOCKS inbound + hysteria2 outbound from a parsed hy2/hysteria2 share link."""
    scheme = cfg.scheme.lower()
    if scheme not in HY2_SCHEMES:
        return None
    password = (cfg.uuid_or_password or "").strip()
    if not password or not cfg.host or not cfg.port:
        return None
    extra = cfg.extra or {}
    sni = (cfg.sni or extra.get("sni") or extra.get("peer") or cfg.host or "").strip()
    # Match Xray probes: do not fail public nodes on cert mismatch.
    insecure = True
    if "insecure" in extra or "allowInsecure" in extra:
        insecure = _truthy(extra.get("insecure", extra.get("allowInsecure")))
    outbound: dict[str, Any] = {
        "type": "hysteria2",
        "tag": "proxy",
        "server": cfg.host,
        "server_port": int(cfg.port),
        "password": password,
        "tls": {
            "enabled": True,
            "server_name": sni or cfg.host,
            "insecure": insecure,
        },
    }
    obfs = str(extra.get("obfs") or extra.get("obfuscation") or "").strip().lower()
    obfs_password = (
        extra.get("obfs-password")
        or extra.get("obfs_password")
        or extra.get("obfsPassword")
        or extra.get("obfsparam")
        or ""
    )
    obfs_password = str(obfs_password).strip()
    if obfs == "salamander" or obfs_password:
        outbound["obfs"] = {
            "type": obfs or "salamander",
            "password": obfs_password,
        }
    mport = extra.get("mport") or extra.get("ports")
    if mport:
        outbound["server_ports"] = [str(mport)]
    pin = extra.get("pinSHA256") or extra.get("pinsha256")
    if pin:
        outbound["tls"]["certificate_public_key_sha256"] = [str(pin)]

    return {
        "log": {"level": "warn"},
        "inbounds": [
            {
                "type": "socks",
                "tag": "socks-in",
                "listen": "127.0.0.1",
                "listen_port": int(local_port),
            }
        ],
        "outbounds": [outbound, {"type": "direct", "tag": "direct"}],
    }


def _stop_proc(proc: subprocess.Popen[bytes] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()


def _run_socks_binary_probe(
    *,
    binary: str,
    args: list[str],
    conf_path: Path,
    local_port: int,
    probe_url: str,
    timeout_sec: float,
    fingerprint: str,
    log_tag: str,
    throughput_url: str | None,
    throughput_timeout_sec: float,
) -> ProbeResult | None:
    proc: subprocess.Popen[bytes] | None = None
    try:
        proc = subprocess.Popen(
            [binary, *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.35)
        if proc.poll() is not None:
            return None
        proxy = f"socks5://127.0.0.1:{local_port}"
        return http_probe_via_socks(
            proxy,
            probe_url,
            timeout_sec,
            throughput_url=throughput_url,
            throughput_timeout_sec=throughput_timeout_sec,
        )
    except Exception as exc:
        logger.debug("%s probe fail fp=%s err=%s", log_tag, fingerprint, exc)
        return None
    finally:
        _stop_proc(proc)
        try:
            conf_path.unlink(missing_ok=True)
        except Exception:
            pass


class XrayProbe:
    def __init__(
        self,
        xray_bin: str,
        workdir: Path,
        probe_url: str,
        timeout_sec: float,
        *,
        throughput_url: str | None = None,
        throughput_timeout_sec: float = 15.0,
    ) -> None:
        self.xray_bin = xray_bin
        self.workdir = workdir
        self.probe_url = probe_url
        self.timeout_sec = timeout_sec
        self.throughput_url = throughput_url
        self.throughput_timeout_sec = throughput_timeout_sec
        self.workdir.mkdir(parents=True, exist_ok=True)

    def available(self) -> bool:
        if Path(self.xray_bin).exists():
            return True
        return shutil.which(self.xray_bin) is not None

    def probe(self, cfg: ProxyConfig, local_port: int) -> ProbeResult | None:
        conf = build_xray_config(cfg, local_port)
        if conf is None:
            return None
        conf_path = self.workdir / f"cfg-{local_port}.json"
        conf_path.write_text(json.dumps(conf), encoding="utf-8")
        return _run_socks_binary_probe(
            binary=self.xray_bin,
            args=["run", "-c", str(conf_path)],
            conf_path=conf_path,
            local_port=local_port,
            probe_url=self.probe_url,
            timeout_sec=self.timeout_sec,
            fingerprint=cfg.fingerprint,
            log_tag="xray",
            throughput_url=self.throughput_url,
            throughput_timeout_sec=self.throughput_timeout_sec,
        )


class SingBoxProbe:
    def __init__(
        self,
        singbox_bin: str,
        workdir: Path,
        probe_url: str,
        timeout_sec: float,
        *,
        throughput_url: str | None = None,
        throughput_timeout_sec: float = 15.0,
    ) -> None:
        self.singbox_bin = singbox_bin
        self.workdir = workdir
        self.probe_url = probe_url
        self.timeout_sec = timeout_sec
        self.throughput_url = throughput_url
        self.throughput_timeout_sec = throughput_timeout_sec
        self.workdir.mkdir(parents=True, exist_ok=True)

    def available(self) -> bool:
        if Path(self.singbox_bin).exists():
            return True
        return shutil.which(self.singbox_bin) is not None

    def probe(self, cfg: ProxyConfig, local_port: int) -> ProbeResult | None:
        conf = build_singbox_hysteria2_config(cfg, local_port)
        if conf is None:
            return None
        conf_path = self.workdir / f"hy2-{local_port}.json"
        conf_path.write_text(json.dumps(conf), encoding="utf-8")
        return _run_socks_binary_probe(
            binary=self.singbox_bin,
            args=["run", "-c", str(conf_path)],
            conf_path=conf_path,
            local_port=local_port,
            probe_url=self.probe_url,
            timeout_sec=self.timeout_sec,
            fingerprint=cfg.fingerprint,
            log_tag="sing-box",
            throughput_url=self.throughput_url,
            throughput_timeout_sec=self.throughput_timeout_sec,
        )


class LiveTester:
    """Real connectivity tests — never fake-pass."""

    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings
        t = settings.get("testing") or {}
        self.mode = (t.get("mode") or "auto").lower()
        self.tcp_timeout = float(t.get("tcp_timeout_sec", 5))
        self.tls_timeout = float(t.get("tls_timeout_sec", 8))
        self.xray_timeout = float(t.get("xray_timeout_sec", 20))
        self.singbox_timeout = float(t.get("singbox_timeout_sec", t.get("xray_timeout_sec", 20)))
        self.concurrency = int(t.get("concurrency", 16))
        self.probe_url = t.get("probe_url") or "https://www.cloudflare.com/cdn-cgi/trace"
        self.local_base = int(t.get("local_socks_base_port", 21000))
        self.singbox_base = int(t.get("singbox_socks_base_port", 22000))
        self.throughput_enabled = bool(t.get("throughput_enabled", True))
        self.throughput_bytes = int(t.get("throughput_bytes", 262144))
        self.throughput_timeout = float(t.get("throughput_timeout_sec", 15))
        tpl = t.get("throughput_url") or "https://speed.cloudflare.com/__down?bytes={bytes}"
        self.throughput_url = _throughput_url(str(tpl), self.throughput_bytes) if self.throughput_enabled else None
        self.xray = XrayProbe(
            xray_bin=t.get("xray_bin") or "xray",
            workdir=Path(t.get("xray_workdir") or "state/runtime/xray"),
            probe_url=self.probe_url,
            timeout_sec=self.xray_timeout,
            throughput_url=self.throughput_url,
            throughput_timeout_sec=self.throughput_timeout,
        )
        self.singbox = SingBoxProbe(
            singbox_bin=t.get("singbox_bin") or "sing-box",
            workdir=Path(t.get("singbox_workdir") or "state/runtime/singbox"),
            probe_url=self.probe_url,
            timeout_sec=self.singbox_timeout,
            throughput_url=self.throughput_url,
            throughput_timeout_sec=self.throughput_timeout,
        )
        self._use_xray = self.mode == "xray" or (self.mode == "auto" and self.xray.available())
        self._use_singbox = self.singbox.available()
        if self._use_xray:
            logger.info("live test mode=xray binary=%s", self.xray.xray_bin)
        else:
            logger.info("live test mode=tcp/tls (xray unavailable or disabled)")
        if self._use_singbox:
            logger.info("hysteria2 probes via sing-box binary=%s", self.singbox.singbox_bin)
        else:
            logger.warning(
                "sing-box unavailable (%s); hysteria2/hy2 probes fail closed (no TCP fake-pass)",
                self.singbox.singbox_bin,
            )

    def _mark_dead(self, cfg: ProxyConfig) -> ProxyConfig:
        cfg.alive = False
        cfg.latency_ms = None
        cfg.throughput_mbps = None
        cfg.score = 0.0
        cfg.fail_count += 1
        return cfg

    def _mark_alive(self, cfg: ProxyConfig, result: ProbeResult) -> ProxyConfig:
        cfg.alive = True
        cfg.latency_ms = result.latency_ms
        cfg.throughput_mbps = result.throughput_mbps
        cfg.score = combined_score(
            result.latency_ms,
            result.throughput_mbps,
            self.settings,
            throughput_attempted=result.throughput_attempted,
        )
        cfg.fail_count = 0
        cfg.last_ok_ts = time.time()
        return cfg

    def test_one(self, cfg: ProxyConfig, worker_idx: int = 0) -> ProxyConfig:
        cfg.last_test_ts = time.time()
        scheme = cfg.scheme.lower()

        if scheme in HY2_SCHEMES:
            if not self._use_singbox:
                logger.debug(
                    "hysteria2 fail-closed: sing-box unavailable fp=%s",
                    cfg.fingerprint,
                )
                return self._mark_dead(cfg)
            local_port = self.singbox_base + (worker_idx % 5000)
            result = self.singbox.probe(cfg, local_port)
            if result is None:
                return self._mark_dead(cfg)
            return self._mark_alive(cfg, result)

        if self._use_xray:
            local_port = self.local_base + (worker_idx % 5000)
            result = self.xray.probe(cfg, local_port)
            if result is not None:
                return self._mark_alive(cfg, result)
            # SSR (and other non-hy2 schemes Xray cannot build) may TCP-probe.
            # hysteria2 never reaches here.
            if scheme == "ssr":
                latency = tcp_connect(cfg.host, cfg.port, self.tcp_timeout)
                if latency is not None:
                    return self._mark_alive(cfg, ProbeResult(latency_ms=latency, throughput_attempted=False))
            return self._mark_dead(cfg)

        latency = tcp_connect(cfg.host, cfg.port, self.tcp_timeout)
        if latency is not None and (cfg.security or "").lower() in {"tls", "xtls", "reality"}:
            tls_lat = tls_handshake(cfg.host, cfg.port, cfg.sni or cfg.host, self.tls_timeout)
            if tls_lat is None:
                latency = None
            else:
                latency = max(latency, tls_lat)
        if latency is None:
            return self._mark_dead(cfg)
        return self._mark_alive(cfg, ProbeResult(latency_ms=latency, throughput_attempted=False))

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
