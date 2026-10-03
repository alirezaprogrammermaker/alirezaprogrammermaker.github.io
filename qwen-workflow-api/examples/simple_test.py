#!/usr/bin/env python3
"""Minimal API smoke test for Qwen Workflow (Windows / Linux / macOS).

1) Copy `.env.example` → `.env` and fill API_KEY (and WORKER_KEY if you want full E2E).
2) Run:

   python examples/simple_test.py

Without WORKER_KEY: only health + enqueue + poll (job stays queued until a poller runs).
With WORKER_KEY + QWEN_CLI_PATH: also runs one poller job (~10s text).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UA = "Mozilla/5.0 (compatible; QwenSimpleTest/1.0)"


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def req(method: str, url: str, key: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    r = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": UA,
        },
    )
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            raw = resp.read()
            return resp.status, (None if not raw else json.loads(raw.decode()))
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            detail = json.loads(raw)
        except Exception:
            detail = raw
        raise SystemExit(f"HTTP {e.code} {method} {url}: {detail}") from e


def main() -> int:
    load_dotenv(ROOT / ".env")
    load_dotenv(Path.cwd() / ".env")

    base = os.environ.get("BRIDGE_URL", "").rstrip("/")
    api_key = os.environ.get("API_KEY", "")
    if not base or not api_key or api_key.startswith("replace-"):
        print(
            "Set BRIDGE_URL and API_KEY in .env (copy from .env.example).",
            file=sys.stderr,
        )
        return 2

    print("1) health", flush=True)
    _, health = req("GET", f"{base}/health", api_key)
    print("  ", health, flush=True)

    prompt = os.environ.get("TEST_PROMPT", "Reply with exactly: SIMPLE_TEST_OK")
    print("2) enqueue chat", flush=True)
    _, job = req(
        "POST",
        f"{base}/v1/chat/completions",
        api_key,
        {
            "model": "qwen-text",
            "think": "fast",
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    job_id = job["id"]
    print(f"   job_id={job_id}", flush=True)
    print(f"   chat_id={job.get('chat_id')}", flush=True)
    print(f"   status={job.get('status')}", flush=True)

    worker_key = os.environ.get("WORKER_KEY", "")
    cli = os.environ.get("QWEN_CLI_PATH", "")
    if not cli:
        candidate = ROOT / "tools" / "qwen_cli.py"
        if candidate.is_file():
            cli = str(candidate)

    if worker_key and not worker_key.startswith("replace-") and cli and Path(cli).is_file():
        print("3) run poller for 1 job", flush=True)
        env = {
            **os.environ,
            "BRIDGE_URL": base,
            "WORKER_KEY": worker_key,
            "QWEN_CLI_PATH": str(Path(cli).resolve()),
            "QWEN_CLI_CONFIG_DIR": os.environ.get(
                "QWEN_CLI_CONFIG_DIR", str(ROOT / ".qwen-config")
            ),
            "MAX_JOBS": "1",
            "IDLE_EXITS": "5",
            "POLL_SECONDS": "5",
            "JOB_TIMEOUT": os.environ.get("JOB_TIMEOUT", "60"),
            "WORKER_ID": "simple-test",
        }
        Path(env["QWEN_CLI_CONFIG_DIR"]).mkdir(parents=True, exist_ok=True)
        poller = ROOT / "poller" / "poller.py"
        subprocess.run([sys.executable, str(poller)], env=env, check=False)
    else:
        print(
            "3) skip poller (set WORKER_KEY in .env to execute the job with CLI)",
            flush=True,
        )

    print("4) poll job status", flush=True)
    final = None
    for i in range(36):
        _, final = req("GET", f"{base}/v1/jobs/{job_id}", api_key)
        status = final.get("status")
        print(f"   [{i}] status={status}", flush=True)
        if status in ("succeeded", "failed"):
            break
        time.sleep(2 if worker_key else 5)

    print("5) result", flush=True)
    print(json.dumps(final, indent=2, ensure_ascii=False)[:2000], flush=True)
    if not final or final.get("status") != "succeeded":
        return 1
    content = ((final.get("result") or {}).get("content")) or ""
    print("\nassistant:", content, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
