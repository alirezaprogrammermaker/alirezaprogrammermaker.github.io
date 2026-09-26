# GHA / host poller

Claims jobs from the Cloudflare control plane and executes `qwen_cli.py`.

```bash
export BRIDGE_URL=https://qwen-workflow-api.<subdomain>.workers.dev
export WORKER_KEY=...          # Worker secret (not the user API key)
export QWEN_CLI_PATH=/path/to/qwen_cli.py
export QWEN_CLI_CONFIG_DIR=/tmp/qwen-cfg
export POLL_SECONDS=8          # keep ≥5 to protect Workers/D1 free quotas
python3 poller.py
```
