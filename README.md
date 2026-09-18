# V2Ray / Xray Subscription Aggregator

English below · فارسی در ادامه

Modular aggregator that collects public V2Ray/Xray share links, **live-tests** them (real TCP/TLS and Xray proxy probes — never fake passes), publishes lean subscription lists on **GitHub Pages**, and posts healthy configs to Telegram.

---

## English

### Features

- Config-driven sources (`config/sources.yaml`) — add URLs without code changes
- Parses `vmess` / `vless` / `trojan` / `ss` / `hysteria2` (and related)
- Dedup by outbound fingerprint; fail-count & max-age eviction
- Live tests via **Xray-core** HTTP probe through SOCKS when available; TCP/TLS fallback
- Publishes to `subs/` for GitHub Pages (**sorted by lowest ping first**)
- **Continuous ~6h live job**: discovery loop + **parallel health-watch every 2 minutes** (dead servers dropped & list republished immediately); cron every 5h starts the next job
- Remarks include **real use-case tags** from measured ping/throughput: `بازی` / `وب` / `دانلود` (never random)
- Protocols: `vmess` `vless` `trojan` `ss` `ssr` `hysteria`/`hysteria2` `tuic` `wireguard` `socks` `http` `juicity` `anytls` `brook` `naive` `mieru`
- Telegram: best configs + nightly summary + channel description update
- Channel description shows **Shamsi (Tehran) last activity** plus subscription URLs
- State via cache/artifact across runs; `subs/` committed whenever the live list changes
- **Never** mentions sources or scrape methods in Telegram or public subscription files

### Fork & secrets

1. Fork / clone this repo (GitHub Pages site: `alirezaprogrammermaker.github.io`)
2. Repo **Settings → Secrets and variables → Actions**, add:
   - `TELEGRAM_BOT_TOKEN` — bot token (bot must be **admin** of the channel)
   - `TELEGRAM_CHANNEL_ID` — numeric chat id **or** `@v2ray_active_config` (channel; not the bot username)
3. Enable **Actions** and **GitHub Pages** (deploy from branch `main` / root, or your existing Pages setup)
4. Ensure the workflow has permission to push (`contents: write`) so `subs/` can be updated

### Add sources

Edit `config/sources.yaml`:

```yaml
sources:
  - id: my-sub
    url: https://example.com/sub.txt
    enabled: true
    timeout_sec: 30
```

### Subscription URL (v2rayNG)

After the first successful workflow run, use one of:

| List | URL |
|------|-----|
| All (base64) | `https://alirezaprogrammermaker.github.io/subs/all.base64` |
| Best (base64) | `https://alirezaprogrammermaker.github.io/subs/best.base64` |
| All (plain) | `https://alirezaprogrammermaker.github.io/subs/all.txt` |
| Best (plain) | `https://alirezaprogrammermaker.github.io/subs/best.txt` |

Raw GitHub alternative:

`https://raw.githubusercontent.com/alirezaprogrammermaker/alirezaprogrammermaker.github.io/main/subs/all.base64`

In **v2rayNG**: Subscriptions → `+` → paste the base64 URL → update.

### Local run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
bash scripts/install-xray.sh
export PATH="$PWD/bin:$PATH"
export TELEGRAM_DRY_RUN=true   # or set real TELEGRAM_* secrets
python -m v2agg --mode refresh --telegram-dry-run --print-metrics
pytest -q
```

### Continuous 6h + 2-min health watch

| Workflow | Schedule (UTC) | Purpose |
|----------|----------------|---------|
| `refresh.yml` | every 5 hours | ~5h30m continuous run: discover + **parallel 2-min healthy re-check** → drop dead → push `subs/` |
| `nightly.yml` | 00:30 | one-shot refresh + nightly Telegram summary |

Each refresh job stays alive for `pipeline.max_runtime_sec` (~5h30m). A background thread re-probes **all** currently healthy servers every `health_watch_interval_sec` (120s) and immediately removes failures from the public list. The next cron is scheduled every 5h so it queues and starts as soon as the previous job ends — near-continuous coverage within Actions limits.

### Dry-run Telegram

Set secret-less local flag `--telegram-dry-run` or env `TELEGRAM_DRY_RUN=true`, or workflow_dispatch input on `refresh.yml`.

### Layout

```
config/           settings + sources YAML
src/v2agg/        collect / parse / test / publish / telegram / state
subs/             published subscription files (Pages)
.github/workflows/
scripts/
tests/
```

---

## فارسی

### خلاصه

این پروژه لینک‌های اشتراک V2Ray/Xray را از منابع قابل‌پیکربندی جمع می‌کند، با **تست واقعی اتصال** (نه قبول جعلی) فیلتر می‌کند، لیست تمیز را روی **GitHub Pages** منتشر می‌کند و بهترین‌ها را به کانال تلگرام می‌فرستد. در خروجی عمومی و پیام‌های تلگرام **هیچ اشاره‌ای به منبع یا روش جمع‌آوری** نمی‌شود.

### راه‌اندازی سریع

1. ریپو را Fork کنید
2. در Secrets اکشن‌ها این‌ها را بگذارید:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHANNEL_ID` (مثلاً `@v2ray_active_config` — کانال، نه یوزرنیم بات)
3. Actions را فعال کنید؛ بات باید ادمین کانال باشد
4. منابع را در `config/sources.yaml` اضافه کنید (`enabled: true`)

### آدرس اشتراک برای v2rayNG

`https://alirezaprogrammermaker.github.io/subs/all.base64`

یا نسخه بهترین‌ها:

`https://alirezaprogrammermaker.github.io/subs/best.base64`

در v2rayNG از منوی اشتراک‌ها این آدرس را اضافه و به‌روز کنید.

### ازسرگیری بعد از ۶ ساعت

رانرهای عمومی گیت‌هاب حدود ۶ ساعت زمان دارند. پایپ‌لاین قبل از اتمام زمان، checkpoint ذخیره می‌کند؛ اجرای بعدی کرون از همان‌جا تست را ادامه می‌دهد. فقط فایل‌های `subs/` در گیت commit می‌شوند.

### مجوز

MIT — فایل `LICENSE`.
