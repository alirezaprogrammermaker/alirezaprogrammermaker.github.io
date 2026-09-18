#!/usr/bin/env python3
"""Minimal client smoke test against the live Qwen Workflow API.

Usage:
  export BRIDGE_URL=https://qwen-workflow-api.qwen-workflow-api.workers.dev
  export API_KEY=...
  # optional — if set, this script also runs the poller for one job:
  export WORKER_KEY=...
  export QWEN_CLI_PATH=../tools/qwen_cli.py

  python3 simple_test.py
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

UA = "Mozilla/5.0 (compatible; QwenSimpleTest/1.0)"


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
    base = os.environ.get("BRIDGE_URL", "").rstrip("/")
    api_key = os.environ.get("API_KEY", "")
    if not base or not api_key:
        print("Set BRIDGE_URL and API_KEY", file=sys.stderr)
        return 2

    print("1) health")
    _, health = req("GET", f"{base}/health", api_key)
    print("  ", health)

    prompt = os.environ.get("TEST_PROMPT", "Reply with exactly: SIMPLE_TEST_OK")
    print("2) enqueue chat")
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
    chat_id = job.get("chat_id")
    print(f"   job_id={job_id}")
    print(f"   chat_id={chat_id}")
    print(f"   status={job.get('status')}")

    worker_key = os.environ.get("WORKER_KEY", "")
    cli = os.environ.get("QWEN_CLI_PATH", "")
    if worker_key and cli and Path(cli).is_file():
        print("3) run poller for 1 job (like GitHub Actions)")
        env = {
            **os.environ,
            "BRIDGE_URL": base,
            "WORKER_KEY": worker_key,
            "QWEN_CLI_PATH": cli,
            "QWEN_CLI_CONFIG_DIR": os.environ.get(
                "QWEN_CLI_CONFIG_DIR", "/tmp/qwen-simple-test-cfg"
            ),
            "MAX_JOBS": "1",
            "IDLE_EXITS": "5",
            "POLL_SECONDS": "5",
            "JOB_TIMEOUT": os.environ.get("JOB_TIMEOUT", "300"),
            "WORKER_ID": "simple-test",
        }
        poller = Path(__file__).resolve().parents[1] / "poller" / "poller.py"
        subprocess.run([sys.executable, str(poller)], env=env, check=False)
    else:
        print("3) skip poller (set WORKER_KEY + QWEN_CLI_PATH to execute the job)")

    print("4) poll job status")
    final = None
    for i in range(36):
        _, final = req("GET", f"{base}/v1/jobs/{job_id}", api_key)
        status = final.get("status")
        print(f"   [{i}] status={status}")
        if status in ("succeeded", "failed"):
            break
        time.sleep(5)

    print("5) result")
    print(json.dumps(final, indent=2, ensure_ascii=False)[:2000])
    if not final or final.get("status") != "succeeded":
        return 1
    content = ((final.get("result") or {}).get("content")) or ""
    print("\nassistant:", content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
