#!/usr/bin/env python3
"""GitHub Actions / local poller — claims jobs and runs qwen_cli.py.

Env:
  BRIDGE_URL           Control-plane base URL (required)
  WORKER_KEY           Worker bearer token (required)
  QWEN_CLI_PATH        path to qwen_cli.py
  QWEN_CLI_CONFIG_DIR  browser profile / accounts dir
  POLL_SECONDS         default 8 (keep ≥5 for free-tier quotas)
  WORKER_ID            default hostname
  MAX_JOBS             stop after N completed jobs (0 = unlimited)
  RUN_SECONDS          stop after N seconds (0 = unlimited) — use ~21000 for 6h GHA
  IDLE_EXITS           consecutive empty claims before exit (0 = never)
  JOB_TIMEOUT          per-job CLI timeout seconds (default 600)
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

# workers.dev / WAF may reject the default Python-urllib User-Agent with 403.
USER_AGENT = os.environ.get(
    "BRIDGE_USER_AGENT",
    "Mozilla/5.0 (compatible; QwenWorkflowPoller/1.0; +https://github.com/)",
)


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
            "User-Agent": USER_AGENT,
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


def _extract_content(stdout: str, stderr: str) -> str:
    """Prefer --raw assistant text; skip Rich chrome / CLI status lines."""
    skip_prefixes = (
        "╭", "╰", "│", "Account:", "Session:", "Browser:", "Model:",
        "Sending...", "Navigating", "Waiting", "Mode:", "Think",
        "New chat", "Uploaded:", "Saved:", "Session active",
        "Not logged", "Already logged", "Login", "CHAT_ID:",
    )
    skip_exact = {
        "Create Video", "Edit", "Create Image", "Share", "Copy",
        "Regenerate", "Retry", "Retry...", "Retry send...", "Skip",
        "Sending...",
    }
    lines = []
    for ln in (stdout or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        if s in skip_exact:
            continue
        if any(s.startswith(p) for p in skip_prefixes):
            continue
        if s.startswith("[") and s.endswith("]"):
            continue
        lines.append(s)
    if lines:
        return "\n".join(lines[-40:])
    blob = ((stdout or "") + "\n" + (stderr or "")).strip()
    # Never treat CHAT_ID machine lines as assistant content.
    cleaned = "\n".join(
        ln for ln in blob.splitlines() if not ln.strip().startswith("CHAT_ID:")
    )
    return cleaned[-2000:]


def _extract_qwen_chat_id(stderr: str, stdout: str = "") -> str | None:
    for ln in ((stderr or "") + "\n" + (stdout or "")).splitlines():
        s = ln.strip()
        if s.startswith("CHAT_ID:"):
            cid = s.split(":", 1)[1].strip()
            if cid and re.fullmatch(r"[0-9a-fA-F-]{16,}", cid) and cid.lower() not in {"guest", "new"}:
                return cid
    return None


def _valid_qwen_chat_id(cid: object) -> bool:
    return (
        isinstance(cid, str)
        and bool(re.fullmatch(r"[0-9a-fA-F-]{16,}", cid))
        and cid.lower() not in {"guest", "new"}
    )


def run_job(cli: Path, config_dir: Path, account: dict, job: dict) -> dict:
    kind = job["kind"]
    req = job.get("request") or {}
    prompt = req.get("prompt") or ""
    mode = req.get("mode") or (
        "image" if kind == "image" else "video" if kind == "video" else None
    )
    name = account["name"]
    env = {**os.environ, "QWEN_CLI_CONFIG_DIR": str(config_dir)}

    subprocess.run(
        [
            sys.executable,
            str(cli),
            "add",
            "-e",
            account["email"],
            "-p",
            account["password"],
            "-n",
            name,
            "-y",
        ],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )

    args = [sys.executable, str(cli), "chat", "-a", name, "--headless", "--raw"]
    existing_cid = job.get("qwen_chat_id")
    if _valid_qwen_chat_id(existing_cid):
        args += ["--chat-id", existing_cid]
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
        env=env,
        capture_output=True,
        text=True,
        timeout=int(os.environ.get("JOB_TIMEOUT", "600")),
    )
    content = _extract_content(proc.stdout or "", proc.stderr or "")
    qwen_chat_id = _extract_qwen_chat_id(proc.stderr or "", proc.stdout or "")
    if not qwen_chat_id and _valid_qwen_chat_id(job.get("qwen_chat_id")):
        qwen_chat_id = job.get("qwen_chat_id")
    result: dict = {"content": content, "exit_code": proc.returncode}
    if out_dir:
        files = sorted(Path(out_dir).glob("*"))
        key = "images" if kind == "image" else "videos"
        if kind == "image":
            files = [f for f in files if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}]
        else:
            files = [f for f in files if f.suffix.lower() in {".mp4", ".webm", ".mov", ".mkv"}]
        result[key] = [str(f) for f in files]
        # If CLI saved media but stdout was noisy, still treat as success when files exist.
        if files and proc.returncode == 0 and not content:
            content = f"[{key} saved: {len(files)}]"
            result["content"] = content

    ok = proc.returncode == 0
    if kind in ("image", "video"):
        media = result.get("images") or result.get("videos")
        ok = proc.returncode == 0 and bool(media)
    # Guard against Rich status lines / soft timeouts being treated as success.
    low = (content or "").lower()
    if ok and (
        "response timeout" in low
        or low.startswith("[timeout")
        or "error on step" in low
    ):
        ok = False

    return {
        "status": "succeeded" if ok else "failed",
        "result": result,
        "error": None if ok else (f"cli exit {proc.returncode}" if proc.returncode else content[:240]),
        "assistant_content": content if ok else None,
        "qwen_chat_id": qwen_chat_id,
    }


def main() -> int:
    base = os.environ["BRIDGE_URL"].rstrip("/")
    key = os.environ["WORKER_KEY"]
    cli = Path(os.environ.get("QWEN_CLI_PATH", "qwen_cli.py"))
    if not cli.is_file():
        print(f"QWEN_CLI_PATH not found: {cli}", flush=True)
        return 2

    config_dir = Path(
        os.environ.get("QWEN_CLI_CONFIG_DIR", tempfile.mkdtemp(prefix="qwen-cfg-"))
    )
    config_dir.mkdir(parents=True, exist_ok=True)

    poll = int(os.environ.get("POLL_SECONDS", "8"))
    worker_id = os.environ.get("WORKER_ID") or socket.gethostname()
    max_jobs = int(os.environ.get("MAX_JOBS", "0"))
    run_seconds = int(os.environ.get("RUN_SECONDS", "0"))
    idle_exits = int(os.environ.get("IDLE_EXITS", "0"))

    started = time.time()
    completed = 0
    idle_streak = 0

    print(
        f"poller start worker_id={worker_id} poll={poll}s "
        f"max_jobs={max_jobs} run_seconds={run_seconds} idle_exits={idle_exits}",
        flush=True,
    )

    while True:
        if run_seconds and (time.time() - started) >= run_seconds:
            print("run_seconds reached; exiting", flush=True)
            break
        if max_jobs and completed >= max_jobs:
            print("max_jobs reached; exiting", flush=True)
            break

        try:
            status, payload = _req(
                "POST", f"{base}/v1/worker/claim", key, {"worker_id": worker_id}
            )
            if status == 204 or not payload:
                idle_streak += 1
                if idle_exits and idle_streak >= idle_exits:
                    print("idle_exits reached; exiting", flush=True)
                    break
                time.sleep(poll)
                continue

            idle_streak = 0
            job = payload["job"]
            account = payload["account"]
            print(f"claimed {job['id']} kind={job['kind']}", flush=True)
            try:
                outcome = run_job(cli, config_dir, account, job)
            except subprocess.TimeoutExpired as e:
                print(f"job timeout {job['id']}: {e}", flush=True)
                outcome = {
                    "status": "failed",
                    "result": {"content": f"job timeout after {e.timeout}s"},
                    "error": f"job timeout after {e.timeout}s",
                    "assistant_content": None,
                    "qwen_chat_id": job.get("qwen_chat_id")
                    if _valid_qwen_chat_id(job.get("qwen_chat_id"))
                    else None,
                }
            except Exception as e:
                print(f"job error {job['id']}: {e}", flush=True)
                outcome = {
                    "status": "failed",
                    "result": {"content": str(e)[:500]},
                    "error": str(e)[:500],
                    "assistant_content": None,
                    "qwen_chat_id": job.get("qwen_chat_id")
                    if _valid_qwen_chat_id(job.get("qwen_chat_id"))
                    else None,
                }
            _req("POST", f"{base}/v1/worker/jobs/{job['id']}/complete", key, outcome)
            completed += 1
            print(
                f"completed {job['id']} status={outcome['status']} done={completed}",
                flush=True,
            )
        except Exception as e:
            print(f"poller error: {e}", flush=True)
            time.sleep(poll)

    print(f"poller exit completed_jobs={completed}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
