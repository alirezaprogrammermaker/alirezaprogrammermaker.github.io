# Agent integration guide — Qwen Workflow API

Use this document when connecting an application or another AI agent to the
Qwen Workflow control plane (Cloudflare Workers + D1). Jobs are **async**:
enqueue → poll → read result. A GitHub Actions / local poller must be running
to execute jobs against chat.qwen.ai.

---

## 1. Connection facts

| Item | Value |
| --- | --- |
| Base URL | `https://qwen-workflow-api.qwen-workflow-api.workers.dev` |
| Auth (apps) | `Authorization: Bearer <API_KEY>` |
| Auth (poller only) | `Authorization: Bearer <WORKER_KEY>` — never ship to end-user apps |
| Required headers | `Content-Type: application/json`, `Accept: application/json`, `User-Agent: Mozilla/5.0 …` |
| Protocol | HTTPS JSON, OpenAI-shaped paths |
| Streaming | **Not supported** (`stream: true` → 400) |

`API_KEY` / `WORKER_KEY` live in Cloudflare Worker secrets. Do not hardcode in
repos. Prefer env vars: `BRIDGE_URL`, `API_KEY`.

**User-Agent:** default Python/`curl` agents may get **403** from workers.dev.
Always send a browser-like UA.

---

## 2. Mental model (for agents)

```
Client app  --API_KEY-->  Worker (queue + D1)
                              ^
                              | WORKER_KEY
                         Poller + qwen_cli (Playwright)
                              |
                         chat.qwen.ai
```

1. Client creates a job (`queued`).
2. Poller claims job, runs CLI, completes (`succeeded` / `failed`).
3. Client polls `GET /v1/jobs/{id}` every **5–10 seconds** (not 1s — free-tier care).
4. Typical text latency when poller is healthy: **~10–15s** end-to-end.
5. Continuity: save `chat_id` (+ optional `account_id`) from the first response;
   send the same `chat_id` on later turns.

Without a running poller, jobs stay `queued` forever.

---

## 3. Models and endpoints

| Goal | Method | Path | `model` |
| --- | --- | --- | --- |
| Text chat | `POST` | `/v1/chat/completions` | `qwen-text` (aliases: `qwen-chat`, `text`, `gpt-4o-mini`) |
| Image | `POST` | `/v1/images/generations` | `qwen-image` (alias: `image`, `dall-e-3`) |
| Video | `POST` | `/v1/videos/generations` | `qwen-video` (alias: `video`) |
| Job status | `GET` | `/v1/jobs/{job_id}` | — |
| Job alias | `GET` | `/v1/chat/completions/{job_id}` | — |
| Chat history | `GET` | `/v1/chats/{chat_id}` | — |
| List accounts | `GET` | `/v1/accounts` | — |
| Add account | `POST` | `/v1/accounts` | — |
| Health | `GET` | `/health` | (no auth) |

Do **not** send `model: "qwen"` — returns 400 Unsupported model.

---

## 4. Request / response contracts

### 4.1 Text — enqueue

```http
POST /v1/chat/completions
Authorization: Bearer <API_KEY>
Content-Type: application/json
User-Agent: Mozilla/5.0 (compatible; MyApp/1.0)
```

```json
{
  "model": "qwen-text",
  "messages": [
    { "role": "user", "content": "Hello" }
  ],
  "think": "fast",
  "chat_id": null,
  "account_id": null,
  "stream": false
}
```

| Field | Required | Notes |
| --- | --- | --- |
| `messages` | yes | At least one `user` message; last user text is the prompt |
| `model` | no | Default `qwen-text` |
| `think` | no | `auto` \| `think` \| `fast` |
| `chat_id` | no | Resume same conversation + bound account |
| `account_id` | no | Pin account; ignored/rejected if conflicts with `chat_id` binding |
| `stream` | no | Must be `false` |

**Immediate response** (job not finished yet):

```json
{
  "id": "<job_uuid>",
  "object": "chat.completion",
  "status": "queued",
  "kind": "text",
  "model": "qwen-text",
  "chat_id": "<api_chat_uuid>",
  "account_id": "<account_uuid>",
  "qwen_chat_id": null,
  "choices": [],
  "error": null,
  "result": null
}
```

Persist `id` (job) and `chat_id` (conversation).

### 4.2 Poll until done

```http
GET /v1/jobs/<job_uuid>
Authorization: Bearer <API_KEY>
User-Agent: Mozilla/5.0 (compatible; MyApp/1.0)
```

`status`: `queued` → `running` → `succeeded` | `failed`

On success, assistant text is in:

- `choices[0].message.content`, and/or
- `result.content`

### 4.3 Continue a chat

```json
{
  "model": "qwen-text",
  "chat_id": "<same chat_id from first response>",
  "messages": [
    { "role": "user", "content": "Follow-up question" }
  ],
  "think": "fast"
}
```

If you pass a different `account_id` than the one bound to `chat_id` → **400**.

### 4.4 Image

```json
{
  "model": "qwen-image",
  "prompt": "a red circle on white",
  "chat_id": null,
  "account_id": null
}
```

`POST /v1/images/generations` → poll `/v1/jobs/{id}`.  
Media paths may be **local runner paths** (no public R2 on free tier).

### 4.5 Video

```json
{
  "model": "qwen-video",
  "prompt": "short clip of a bouncing ball"
}
```

`POST /v1/videos/generations` → poll. Video success requires a real video file
from the poller; thumbnails alone fail.

### 4.6 Register a Qwen account (pool)

```json
POST /v1/accounts
{
  "name": "primary",
  "email": "user@example.com",
  "password": "..."
}
```

Passwords are sealed at rest with `ACCOUNT_SECRET`. List with `GET /v1/accounts`
(no password returned).

---

## 5. Minimal client (Python) — copy into an agent tool

```python
import json, os, time, urllib.request, urllib.error

BASE = os.environ["BRIDGE_URL"].rstrip("/")
API_KEY = os.environ["API_KEY"]
UA = "Mozilla/5.0 (compatible; AgentClient/1.0)"

def api(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": UA,
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())

def chat(text, chat_id=None, think="fast", poll_s=5, timeout_s=120):
    body = {
        "model": "qwen-text",
        "messages": [{"role": "user", "content": text}],
        "think": think,
        "stream": False,
    }
    if chat_id:
        body["chat_id"] = chat_id
    job = api("POST", "/v1/chat/completions", body)
    job_id, chat_id = job["id"], job["chat_id"]
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        st = api("GET", f"/v1/jobs/{job_id}")
        if st["status"] in ("succeeded", "failed"):
            content = None
            if st.get("choices"):
                content = st["choices"][0]["message"]["content"]
            elif isinstance(st.get("result"), dict):
                content = st["result"].get("content")
            return {
                "ok": st["status"] == "succeeded",
                "job_id": job_id,
                "chat_id": chat_id,
                "account_id": st.get("account_id"),
                "content": content,
                "error": st.get("error"),
                "raw": st,
            }
        time.sleep(poll_s)
    return {"ok": False, "error": "poll_timeout", "job_id": job_id, "chat_id": chat_id}

# first turn
r1 = chat("Say hi in one sentence")
# continue
r2 = chat("Now say bye", chat_id=r1["chat_id"])
```

Repo smoke test (same idea): `examples/simple_test.py`.

---

## 6. Checklist for an integrating agent

When wiring an app, do all of the following:

1. **Config:** read `BRIDGE_URL` + `API_KEY` from env/secrets (not source).
2. **Headers:** always set Bearer + JSON + Mozilla-like `User-Agent`.
3. **Enqueue** with `model: qwen-text` (or image/video models above).
4. **Store** `job.id` and `chat_id` from the enqueue response.
5. **Poll** `GET /v1/jobs/{id}` every 5–10s until `succeeded`/`failed`.
6. **Surface** `choices[0].message.content` or `error` to the user.
7. **Multi-turn:** reuse `chat_id`; do not invent a new one each message.
8. **Do not** call `/v1/worker/*` from the product app (poller-only).
9. **Do not** set `stream: true`.
10. **Health-check** `GET /health` before first use in setup scripts.
11. If jobs stay `queued` > ~30s: poller/GHA is down — tell the operator to
    start `poller/poller.py` or the `qwen-worker` workflow (needs `WORKER_KEY`).
12. Respect free-tier: avoid 1s polling storms; one completion poller is enough.

---

## 7. Error map

| HTTP / status | Meaning | Agent action |
| --- | --- | --- |
| 401 | Bad/missing `API_KEY` | Fix secret |
| 403 | Often bad UA on workers.dev | Set Mozilla-like User-Agent |
| 400 Unsupported model | Wrong `model` string | Use `qwen-text` / `qwen-image` / `qwen-video` |
| 400 account mismatch | `account_id` ≠ chat binding | Omit `account_id` or use bound one |
| 400 stream | `stream: true` | Set false / omit |
| Job `failed` | CLI/poller error | Read `error` + `result`; retry once |
| Stays `queued` | No poller | Start GHA/local poller |

---

## 8. Operator side (not for end-user apps)

Poller env (GitHub Actions or local):

```bash
export BRIDGE_URL=https://qwen-workflow-api.qwen-workflow-api.workers.dev
export WORKER_KEY=...
export QWEN_CLI_PATH=./tools/qwen_cli.py
export QWEN_CLI_CONFIG_DIR=./.qwen-config
export MAX_JOBS=0          # 0 = until RUN_SECONDS
export RUN_SECONDS=21000   # ~6h GHA window
export POLL_SECONDS=8
python poller/poller.py
```

Workflow file: `.github/workflows/qwen-worker.yml`  
Repo secrets: `BRIDGE_URL`, `WORKER_KEY`.

---

## 9. What this API is / is not

**Is:** async OpenAI-shaped facade over a browser CLI worker; chat continuity via
`chat_id`; text / image / video job kinds; free Cloudflare Workers + D1.

**Is not:** a synchronous LLM HTTP API; not OpenAI-compatible streaming; not a
CDN for generated media (paths are runner-local unless you add storage later).

---

## 10. Quick verify commands

```bash
curl -s "$BRIDGE_URL/health"

curl -s "$BRIDGE_URL/v1/chat/completions" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -H "User-Agent: Mozilla/5.0" \
  -d '{"model":"qwen-text","messages":[{"role":"user","content":"ping"}],"think":"fast"}'
```

Then poll `/v1/jobs/<id>` until finished.
