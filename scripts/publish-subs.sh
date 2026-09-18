#!/usr/bin/env bash
# Publish subscription outputs to GitHub Pages branch content (committed under subs/).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [[ ! -d subs ]]; then
  echo "No subs/ directory — nothing to publish"
  exit 0
fi

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

git add subs/
if git diff --cached --quiet; then
  echo "No subscription changes"
  exit 0
fi

git commit -m "chore(subs): refresh healthy subscription lists"

# Rebase onto remote before push — continuous job pushes often; avoid non-fast-forward failures
branch="$(git rev-parse --abbrev-ref HEAD)"
if git rev-parse --verify "origin/${branch}" >/dev/null 2>&1; then
  git pull --rebase --autostash origin "${branch}" || {
    echo "pull --rebase failed; trying push anyway"
  }
fi

git push origin "HEAD:${branch}"
