from __future__ import annotations

import subprocess
from pathlib import Path

from v2agg.util.logging import get_logger

logger = get_logger(__name__)


def push_subs_if_changed(repo_root: Path | None = None) -> bool:
    """Commit and push subs/ via scripts/publish-subs.sh. Returns True if a commit was made."""
    root = repo_root or Path.cwd()
    script = root / "scripts" / "publish-subs.sh"
    if not script.is_file():
        logger.warning("publish-subs.sh missing — skip git publish")
        return False
    try:
        proc = subprocess.run(
            ["bash", str(script)],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            logger.warning("git publish failed code=%s out=%s", proc.returncode, out[-500:])
            return False
        if "No subscription changes" in out or "nothing to publish" in out.lower():
            return False
        logger.info("git publish ok")
        return True
    except Exception as exc:
        logger.warning("git publish error: %s", type(exc).__name__)
        return False
