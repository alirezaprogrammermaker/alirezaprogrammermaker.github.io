#!/usr/bin/env python3
"""GitHub Actions / local poller — claims jobs and runs qwen_cli.py.

Env:
  BRIDGE_URL      e.g. https://qwen-workflow-api.<subdomain>.workers.dev
  WORKER_KEY      Worker bearer token
  QWEN_CLI_PATH   path to qwen_cli.py
  QWEN_CLI_CONFIG_DIR  optional
  POLL_SECONDS    default 8 (keep low request volume)
  WORKER_ID       default hostname
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def _req(method: str, url: str, key: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    r = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            raw = resp.read()
            if resp.status == 204 or not raw:
                return resp.status, None
            return resp.status, json.loads(raw.decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {raw}") from e


def run_job(cli: Path, config_dir: Path, account: dict, job: dict) -> dict:
    kind = job["kind"]
    req = job.get("request") or {}
    prompt = req.get("prompt") or ""
    mode = req.get("mode") or ("image" if kind == "image" else "video" if kind == "video" else None)
    name = account["name"]
    # Ensure account present for CLI
    subprocess.run(
        [sys.executable, str(cli), "add", "-e", account["email"], "-p", account["password"], "-n", name, "-y"],
        check=False,
        env={**os.environ, "QWEN_CLI_CONFIG_DIR": str(config_dir)},
        capture_output=True,
        text=True,
    )
    args = [sys.executable, str(cli), "chat", "-a", name, "--headless", "--raw"]
    if job.get("qwen_chat_id"):
        args += ["--chat-id", job["qwen_chat_id"]]
    else:
        args += ["-n"]
    if mode and mode != "chat":
        args += ["--mode", mode]
    think = req.get("think")
    if think:
        args += ["-t", think]
    args += ["-p", prompt]
    out_dir = None
    if kind in ("image", "video"):
        out_dir = tempfile.mkdtemp(prefix="qwen-out-")
        args += ["-d", out_dir]
    proc = subprocess.run(
        args,
        env={**os.environ, "QWEN_CLI_CONFIG_DIR": str(config_dir)},
        capture_output=True,
        text=True,
        timeout=int(os.environ.get("JOB_TIMEOUT", "600")),
    )
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    # Best-effort: last non-empty line as content for text
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    content = lines[-1] if lines else text[-2000:]
    result = {"content": content, "exit_code": proc.returncode}
    if out_dir:
        files = list(Path(out_dir).glob("*"))
        result["images" if kind == "image" else "videos"] = [str(f) for f in files]
    ok = proc.returncode == 0
    return {
        "status": "succeeded" if ok else "failed",
        "result": result,
        "error": None if ok else f"cli exit {proc.returncode}",
        "assistant_content": content if ok else None,
        "qwen_chat_id": job.get("qwen_chat_id"),
    }


def main() -> int:
    base = os.environ["BRIDGE_URL"].rstrip("/")
    key = os.environ["WORKER_KEY"]
    cli = Path(os.environ.get("QWEN_CLI_PATH", "qwen_cli.py"))
    config_dir = Path(os.environ.get("QWEN_CLI_CONFIG_DIR", tempfile.mkdtemp(prefix="qwen-cfg-")))
    config_dir.mkdir(parents=True, exist_ok=True)
    poll = int(os.environ.get("POLL_SECONDS", "8"))
    worker_id = os.environ.get("WORKER_ID") or socket.gethostname()
    print(f"poller start worker_id={worker_id} poll={poll}s", flush=True)
    while True:
        try:
            status, payload = _req("POST", f"{base}/v1/worker/claim", key, {"worker_id": worker_id})
            if status == 204 or not payload:
                time.sleep(poll)
                continue
            job = payload["job"]
            account = payload["account"]
            print(f"claimed {job['id']} kind={job['kind']}", flush=True)
            outcome = run_job(cli, config_dir, account, job)
            _req("POST", f"{base}/v1/worker/jobs/{job['id']}/complete", key, outcome)
            print(f"completed {job['id']} status={outcome['status']}", flush=True)
        except Exception as e:
            print(f"poller error: {e}", flush=True)
            time.sleep(poll)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
