# V2Ray / Xray Subscription Aggregator

English below · فارسی در ادامه

Modular aggregator that collects public V2Ray/Xray share links, **live-tests** them (real TCP/TLS and Xray proxy probes — never fake passes), publishes lean subscription lists on **GitHub Pages**, and posts healthy configs to Telegram.

---

## English

### Features

- Config-driven sources (`config/sources.yaml`) — add URLs without code changes
- Parses `vmess` / `vless` / `trojan` / `ss` / `hysteria2` (and related)
- Dedup by outbound fingerprint; fail-count & max-age eviction
- Live tests via **Xray-core** HTTP probe through SOCKS when available; TCP/TLS fallback for non-hy2 only
- **Hysteria2 / hy2** is probed with **sing-box** (SOCKS inbound + hysteria2 outbound). Bare TCP/TLS never marks hy2 alive; if sing-box is missing, hy2 fails closed
- After a successful Xray/sing-box probe, a small download (default 256KB via Cloudflare `__down`) measures **Mbps** and is blended into the score (`0.65` latency + `0.35` throughput)
- **`subs/best`** is a strict quality list: blended score plus a Hysteria2 ranking bonus (`testing.protocol_score_bonus.hysteria2`, default **+15**), then Reality burned-pattern *soft penalties* (yahoo.com SNI / Softlayer `169.40.42.0/24` / shared `pbk`) so those clones cannot dominate when alternatives exist. Quality gate is effective score ≥ `best_score_threshold` (default **70**), hard cap `best_max_publish` (default **30**), diversity caps (max **2** per IPv4 `/24` and max **2** per Reality `pbk` / `(pbk, sni)`). Unused slots are backfilled from lower-score alive nodes that add a new `/24` or `pbk`. Penalties apply to **`best` only** — `subs/all` is unchanged. **`subs/best-hy2`** is alive hysteria2/hy2 only (cap **40**, `/24` diversity on IP hosts). **GitHub Actions probes from abroad — a high score does not mean the path from Iran works.**
- Public remarks include latency (and Mbps when measured) so clients can sort; still **no** source attribution
- Publishes to `subs/` for GitHub Pages
- Telegram: best configs + nightly summary + channel description update
- **Continuous ~6h job**: discovery loop finds new servers; parallel **2‑min health-watch** re-checks the whole healthy list, drops dead, and git-pushes so Pages updates immediately
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
| Best Hysteria2 (base64) | `https://alirezaprogrammermaker.github.io/subs/best-hy2.base64` |
| All (plain) | `https://alirezaprogrammermaker.github.io/subs/all.txt` |
| Best (plain) | `https://alirezaprogrammermaker.github.io/subs/best.txt` |
| Best Hysteria2 (plain) | `https://alirezaprogrammermaker.github.io/subs/best-hy2.txt` |

Raw GitHub alternative:

`https://raw.githubusercontent.com/alirezaprogrammermaker/alirezaprogrammermaker.github.io/main/subs/all.base64`

In **v2rayNG**: Subscriptions → `+` → paste the base64 URL → update.

### Local run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
bash scripts/install-xray.sh   # also installs sing-box for hy2 probes
export PATH="$PWD/bin:$PATH"
export TELEGRAM_DRY_RUN=true   # or set real TELEGRAM_* secrets
python -m v2agg --mode refresh --telegram-dry-run --print-metrics
pytest -q
```

### Quality filter & rollback

`subs/best` is **not** a copy of `subs/all`. Defaults in `config/settings.yaml`:

| Setting | Default | Meaning |
|---------|---------|---------|
| `pipeline.best_score_threshold` | `70` | Minimum *effective* score for the first `best` pass |
| `pipeline.best_max_publish` | `30` | Hard Top-N after sorting by effective score, then latency |
| `pipeline.best_max_per_prefix24` | `2` | Max `best` entries per IPv4 `/24` (hostnames use a host-key instead; no DNS) |
| `pipeline.best_max_per_reality_pbk` | `2` | Max `best` entries per Reality `pbk` and per `(pbk, sni)` pair |
| `pipeline.best_hy2_max_publish` | `40` | Cap for `subs/best-hy2` (alive hysteria2/hy2 only) |
| `testing.protocol_score_bonus.hysteria2` | `15` | Ranking bonus for hy2 in `best` / `best-hy2` (not stored, not applied to `all`) |
| `pipeline.reality_burned_sni` | `yahoo.com` | Reality SNI denylist; soft-penalized in `best` only |
| `pipeline.reality_burned_sni_penalty` | `25` | Subtracted from effective score when Reality SNI matches the denylist |
| `pipeline.reality_burned_prefix24` | `169.40.42.0/24` | Burned IPv4 CIDRs (Softlayer cluster); `best` only |
| `pipeline.reality_burned_prefix_penalty` | `20` | Subtracted when the host sits in a burned prefix |
| `pipeline.reality_shared_pbk_min` / `_penalty` | `4` / `10` | Extra `best` penalty when many peers share the same Reality `pbk` |
| `pipeline.reality_uncommon_sni_max` / `_bonus` | `2` / `5` | Small `best` bonus for Reality SNI that appears at most this often |
| `pipeline.max_healthy_publish` | `150` | Cap for `all` (must stay larger than `best`) |
| `testing.throughput_enabled` | `true` | Mbps probe through the same SOCKS proxy |
| `testing.throughput_bytes` | `262144` | Download size (256KB) |
| `testing.singbox_bin` | `bin/sing-box` | Required for hysteria2/hy2 |

Actions tests from a vantage **outside Iran**. High Mbps on a Reality `/24` cluster can still be dead on Iranian paths — diversity caps keep that cluster to 2 slots, then hy2 bonus + burned-pattern penalties prefer Hysteria2 and uncommon-SNI Reality.

Rollback point before this quality hardening (annotated tag on `main`):

```bash
git checkout main && git reset --hard pre-quality-hardening-2026-09-20
```

Or close/revert the quality PR instead of resetting `main`.

### Cron & continuous 6h + 2‑min watch

| Workflow | Schedule (UTC) | Purpose |
|----------|----------------|---------|
| `refresh.yml` | every 5 hours | continuous discovery + parallel 2‑min healthy re-check (~5h30m) |
| `nightly.yml` | 00:30 | single-pass refresh + nightly summary report |

While the job is alive, newly found working servers are merged into `subs/` and pushed right away; dead ones are removed on the next 2‑minute watch. Cron starts the next job before the previous budget ends for near-continuous coverage.

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

این پروژه لینک‌های اشتراک V2Ray/Xray را از منابع قابل‌پیکربندی جمع می‌کند، با **تست واقعی اتصال** (نه قبول جعلی) فیلتر می‌کند، لیست تمیز را روی **GitHub Pages** منتشر می‌کند و بهترین‌ها را به کانال تلگرام می‌فرستد. لیست `best` حداکثر ۳۰ سرور با امتیاز مؤثر ≥ ۷۰ است، Hysteria2 را بالا می‌برد، و الگوهای Reality سوخته (مثل `yahoo.com` روی `169.40.42.0/24`) را فقط در `best` جریمه می‌کند — از `all` حذف نمی‌شوند. از یک `/24` یا یک کلید Reality بیش از دو مورد برنمی‌دارد. لیست جداگانه `best-hy2` فقط hysteria2 زنده است. تست Actions از خارج ایران است؛ امتیاز بالا به‌معنای کار کردن مسیر ایران نیست. hysteria2 فقط با sing-box تست می‌شود. در خروجی عمومی و پیام‌های تلگرام **هیچ اشاره‌ای به منبع یا روش جمع‌آوری** نمی‌شود.

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

برای مسیر ایران، لیست فقط Hysteria2:

`https://alirezaprogrammermaker.github.io/subs/best-hy2.base64`

در v2rayNG از منوی اشتراک‌ها این آدرس را اضافه و به‌روز کنید.

### ازسرگیری بعد از ۶ ساعت

رانرهای عمومی گیت‌هاب حدود ۶ ساعت زمان دارند. پایپ‌لاین قبل از اتمام زمان، checkpoint ذخیره می‌کند؛ اجرای بعدی کرون از همان‌جا تست را ادامه می‌دهد. فقط فایل‌های `subs/` در گیت commit می‌شوند.

### مجوز

MIT — فایل `LICENSE`.
