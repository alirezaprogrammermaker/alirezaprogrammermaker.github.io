# Qwen AI on Workflow — local copy

Complete project package for:

`D:\Projects\AI\qwen-ai-on-workflow`

## What is included

- Cloudflare Worker API (`src/`, `migrations/`, `wrangler.jsonc`)
- GHA poller (`poller/`) + vendored CLI (`tools/qwen_cli.py`)
- GitHub Actions workflow (`.github/workflows/qwen-worker.yml`)
- API test: `examples/simple_test.py` + `run_api_test.bat`

## Put it on your D: drive

### Option A — from Agent Store zip (easiest)

1. Open zip:  
   `...\AgentStores\...\bc-d5d239f5-...\files\media\qwen-ai-on-workflow.zip`
2. Extract to:  
   `D:\Projects\AI\qwen-ai-on-workflow`

PowerShell:

```powershell
New-Item -ItemType Directory -Force -Path D:\Projects\AI | Out-Null
Expand-Archive -Force `
  "$env:LOCALAPPDATA\Cursor\AgentStores\cursor_agent_stores\bc-d5d239f5-7a0f-4c31-9312-5531f0468691\files\media\qwen-ai-on-workflow.zip" `
  D:\Projects\AI\qwen-ai-on-workflow
```

### Option B — copy the folder

Copy this whole directory:

`services/qwen-ai-on-workflow/`

to:

`D:\Projects\AI\qwen-ai-on-workflow`

### Option C — from GitHub PR branch

```powershell
git clone -b cursor/qwen-workflow-api-73c3 --single-branch `
  https://github.com/alirezaprogrammermaker/alirezaprogrammermaker.github.io.git `
  D:\Projects\AI\qwen-ai-on-workflow-tmp
# then take the qwen-workflow-api folder (+ .github/workflows/qwen-worker.yml)
```

## Run the API test

```powershell
cd D:\Projects\AI\qwen-ai-on-workflow
copy .env.example .env
notepad .env
# fill API_KEY (and WORKER_KEY for full E2E with CLI)

python -m pip install rich click playwright
python -m playwright install chromium

# API-only (enqueue + poll status):
python examples\simple_test.py

# Or double-click:
# run_api_test.bat
```

For full E2E (~10s text), set in `.env`:

```
WORKER_KEY=...
QWEN_CLI_PATH=tools/qwen_cli.py
```

Keys live in Cloudflare Worker secrets (`API_KEY`, `WORKER_KEY`) — do not commit `.env`.
