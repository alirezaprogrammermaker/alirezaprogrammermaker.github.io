#!/usr/bin/env python3
"""
Qwen CLI v3.1 — Professional Command-Line Interface for chat.qwen.ai

Features:
  - Multi-account with persistent browser profiles (cookies + localStorage)
  - Smart session reuse (no re-login every run)
  - Multi-turn: -p "msg1" -p "msg2" ... (sequential in same chat)
  - Prompt file: -P flow.txt (--- separated)
  - Continue: -c resumes last chat, --chat-id <id> opens specific chat
  - Interactive chat selection: /open (no number) shows numbered list
  - Mode selection: chat, web, image, video, research, webdev, slides, art, learning, travel
  - Think mode: auto / think / fast
  - Model selection & display (fixed: no more "Unknown")
  - Image download from responses
  - Export conversation to markdown
  - Stop generation (Ctrl+C / /stop)
  - File upload
  - Pipe/stdin support
  - Optimized speed: minimal delays, fast response detection
"""

import os
import asyncio
import json
import shutil
import sys
import time
import base64
import re
from pathlib import Path
from typing import Optional
from datetime import datetime

try:
    import click
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich.table import Table
    from rich import box
except ImportError:
    print("Missing dependencies. Install: pip install rich click")
    sys.exit(1)

try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("Missing playwright. Install: pip install playwright && playwright install chromium")
    sys.exit(1)

# ─── Force UTF-8 on stdout/stderr (Windows fix) ─────────────────────────────
# On Windows, Python's default sys.stdout encoding is cp1252 ("charmap"),
# which CANNOT encode non-Latin characters. Rich's Console may bypass this,
# but plain `print()` calls and the readline-based `add` command still
# crash on Persian text. Reconfigure to UTF-8 BEFORE any other import.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

# ─── Constants ───────────────────────────────────────────────────────────────

APP_NAME = "qwen-cli"


def _resolve_config_dir() -> Path:
    """Canonical location for accounts + browser profiles.

    Order:
      1. QWEN_CLI_CONFIG_DIR env var (set by the ReelForge server).
      2. <project>/data — qwen_cli.py lives in <project>/tools/, so when it
         is part of a ReelForge installation the data lives with the project
         (single storage layer, ready for a future SQLite migration).
      3. Legacy standalone fallback: ~/.config/qwen-cli
    """
    env_dir = os.environ.get("QWEN_CLI_CONFIG_DIR")
    if env_dir:
        return Path(env_dir)
    project_data = Path(__file__).resolve().parent.parent / "data"
    if project_data.is_dir():
        return project_data
    return Path.home() / ".config" / APP_NAME


def _migrate_legacy_config(target: Path) -> None:
    """One-time move of a legacy ~/.config/qwen-cli install into the project
    data dir. Copies accounts.json, moves the profiles dir (browser
    sessions), so nothing is duplicated and no session is lost."""
    legacy = Path.home() / ".config" / APP_NAME
    if not legacy.exists() or legacy.resolve() == target.resolve():
        return
    target.mkdir(parents=True, exist_ok=True)
    legacy_accounts = legacy / "accounts.json"
    target_accounts = target / "accounts.json"
    if legacy_accounts.exists() and not target_accounts.exists():
        shutil.copy2(legacy_accounts, target_accounts)
    legacy_profiles = legacy / "profiles"
    target_profiles = target / "profiles"
    if legacy_profiles.exists() and not target_profiles.exists():
        try:
            shutil.move(str(legacy_profiles), str(target_profiles))
        except OSError:
            pass  # profiles re-create on next login — not fatal


CONFIG_DIR = _resolve_config_dir()
_migrate_legacy_config(CONFIG_DIR)
PROFILES_DIR = CONFIG_DIR / "profiles"
CONFIG_FILE = CONFIG_DIR / "accounts.json"

QWEN_CHAT_URL = "https://chat.qwen.ai/"
QWEN_AUTH_URL = "https://chat.qwen.ai/auth"

DEFAULT_TIMEOUT = 60_000
LOGIN_TIMEOUT = 90_000  # auth page can be slow behind filters/proxies
RESPONSE_TIMEOUT = 300_000  # 5 min for research/image gen

# Response detection tuning
# The stability check itself now runs inside the page (via wait_for_function),
# so POLL_INTERVAL is the in-browser polling granularity, not a Python-side
# sleep — this is what actually made the old loop slow (3-4 CDP round trips
# every 800ms for the whole duration of a response).
POLL_INTERVAL = 100       # ms between in-browser polls
STABLE_MS = 650           # ms of unchanged text required before we call it done
SEND_VERIFY_TIMEOUT = 2500  # ms to wait for the user message to land after Enter
PRE_SEND_WAIT = 30        # ms after fill, before Enter
POST_CLICK_WAIT = 220     # ms after mode/model/think click
AUTH_HYDRATE_WAIT = 700   # ms after opening /auth before looking for inputs
POST_LOGIN_SETTLE = 1200  # ms after leaving /auth before requiring chat UI

# UI button/action text to strip from extracted responses
RESPONSE_NOISE = [
    "Copy", "Good response", "Bad response", "Share", "Regenerate", "More actions",
    "\u06a9\u067e\u06cc", "\u067e\u0627\u0633\u062e \u062e\u0648\u0628", "\u067e\u0627\u0633\u062e \u0628\u062f",
    "\u0627\u0634\u062a\u0631\u0627\u06a9\u200c\u06af\u0630\u0627\u0631\u06cc", "\u0628\u0627\u0632\u062a\u0648\u0644\u06cc\u062f",
    "\u0639\u0645\u0644\u06cc\u0627\u062a \u0628\u06cc\u0634\u062a\u0631", "\u062a\u0641\u06a9\u0631 \u062a\u06a9\u0645\u06cc\u0644 \u0634\u062f",
    "\u0631\u062f \u0634\u062f\u0646",
    # Feedback popup text
    "\u0627\u06cc\u0646 \u0628\u0627\u0632\u062e\u0648\u0631\u062f",
    "\u06a9\u062f\u0627\u0645 \u067e\u0627\u0633\u062e",
    "\u067e\u0627\u0633\u062e 1", "\u067e\u0627\u0633\u062e 2",
    "\u0627\u0631\u0632\u06cc\u0627\u0628\u06cc \u0648 \u0628\u0647\u0628\u0648\u062f",
]

# Mode name mapping: CLI name → UI label aliases (EN + FA). Browser locale is
# often en-US even for FA accounts; matching only Persian broke --mode image.
MODE_MAP = {
    "chat":     None,  # default
    "web":      ["Web search", "\u062c\u0633\u062a\u062c\u0648\u06cc \u0648\u0628"],
    "image":    ["Create Image", "\u0627\u06cc\u062c\u0627\u062f \u062a\u0635\u0648\u06cc\u0631"],
    "video":    ["Create Video", "\u0627\u06cc\u062c\u0627\u062f \u0648\u06cc\u062f\u06cc\u0648"],
    "research": ["Deep Research", "\u062a\u062d\u0642\u06cc\u0642 \u0639\u0645\u06cc\u0642"],
    "webdev":   ["Web Dev", "\u062a\u0648\u0633\u0639\u0647 \u0648\u0628"],
    "slides":   ["Slides", "\u0627\u0633\u0644\u0627\u06cc\u062f\u0647\u0627"],
    "upload":   ["Upload attachment", "\u0622\u067e\u0644\u0648\u062f \u067e\u06cc\u0648\u0633\u062a"],
    "art":      ["Artifacts", "\u0622\u062b\u0627\u0631"],
    "learning": ["Learn", "\u06cc\u0627\u062f\u06af\u06cc\u0631\u06cc"],
    "travel":   ["Travel Planner", "\u0628\u0631\u0646\u0627\u0645\u0647\u200c\u0631\u06cc\u0632 \u0633\u0641\u0631"],
}

# Think mode mapping: CLI name → UI label aliases (EN + FA)
THINK_MAP = {
    "auto":  ["Auto", "\u062e\u0648\u062f\u06a9\u0627\u0631"],
    "think": ["Thinking", "\u062a\u0641\u06a9\u0631"],
    "fast":  ["Fast", "\u0633\u0631\u06cc\u0639"],
}

MODE_BUTTON_SELECTORS = [
    '[aria-label="Select Mode"]',
    '[aria-label="\u0627\u0646\u062a\u062e\u0627\u0628 \u062d\u0627\u0644\u062a"]',  # انتخاب حالت
]

THINK_LABELS_ALL = {label for labels in THINK_MAP.values() for label in labels}

console = Console()


# ─── Config Management ──────────────────────────────────────────────────────

def ensure_dirs():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)


def load_accounts() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError) as exc:
            # NEVER silently return {} here — callers merge their change into
            # this dict and save it back, which would wipe every saved
            # account. Surface the problem instead so destructive commands
            # can refuse to run.
            raise RuntimeError(
                f"cannot read accounts file {CONFIG_FILE}: {exc}. "
                f"Fix or delete the file manually before adding/removing accounts."
            ) from exc
    return {}


def save_accounts(accounts: dict):
    ensure_dirs()
    # Atomic write: a crash or concurrent reader mid-write must never leave
    # a truncated accounts file behind.
    tmp = CONFIG_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(accounts, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CONFIG_FILE)


def sanitize_name(name: str) -> str:
    return re.sub(r"[\s/\\]+", "_", name).lower()


def get_profile_path(account_name: str) -> Path:
    return PROFILES_DIR / sanitize_name(account_name)


# ─── Browser Manager ─────────────────────────────────────────────────────────

class QwenClient:
    """Manages browser session and interaction with qwen.ai."""

    def __init__(self, account_name: str, headless: bool = True):
        self.account_name = account_name
        self.headless = headless
        self.playwright = None
        self.context = None
        self.page = None
        self._stop_requested = False
        # Why the last login() call failed — "auth_page" (bad credentials),
        # "network: ..." or "error: ...". Used by the verify command.
        self.last_login_error: Optional[str] = None
        # Real upstream chat UUID (URL often stays /c/guest; API carries chat_id).
        self._last_chat_id: str = ""

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.close()

    # ── Lifecycle ──────────────────────────────────────────────────────────

    @staticmethod
    def _looks_like_chat_id(cid: str) -> bool:
        return bool(
            cid
            and re.fullmatch(r"[0-9a-fA-F-]{16,}", cid)
            and cid.lower() not in {"guest", "new"}
        )

    def _remember_chat_id(self, cid: str) -> None:
        if self._looks_like_chat_id(cid):
            self._last_chat_id = cid

    def _on_network_response(self, response) -> None:
        """Capture chat_id from Qwen API traffic (URL bar may stay /c/guest)."""
        try:
            url = response.url or ""
            m = re.search(r"[?&]chat_id=([0-9a-fA-F-]{16,})", url)
            if m:
                self._remember_chat_id(m.group(1))
        except Exception:
            pass

    async def start(self):
        ensure_dirs()
        profile_path = get_profile_path(self.account_name)
        profile_path.mkdir(parents=True, exist_ok=True)

        self.playwright = await async_playwright().start()
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_path),
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
            viewport={"width": 1280, "height": 720},
            locale="en-US",
            ignore_default_args=["--enable-automation"],
        )
        pages = self.context.pages
        self.page = pages[0] if pages else await self.context.new_page()
        self.page.set_default_timeout(DEFAULT_TIMEOUT)
        self.page.on("response", self._on_network_response)

    async def close(self):
        if self.context:
            try:
                await self.context.close()
            except Exception:
                pass
            self.context = None
        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception:
                pass
            self.playwright = None
        self.page = None

    # ── Login / Session ────────────────────────────────────────────────────

    async def _goto_resilient(
        self,
        url: str,
        *,
        wait_until: str = "domcontentloaded",
        timeout: int = DEFAULT_TIMEOUT,
        retries: int = 2,
    ) -> None:
        """Navigate with one retry on transient network errors."""
        last_err: Exception | None = None
        for attempt in range(retries):
            try:
                await self.page.goto(url, wait_until=wait_until, timeout=timeout)
                return
            except Exception as e:
                last_err = e
                err = str(e).lower()
                transient = any(
                    tok in err
                    for tok in (
                        "timeout",
                        "timed out",
                        "err_connection",
                        "net::err_",
                        "econnrefused",
                        "econnreset",
                    )
                )
                if transient and attempt < retries - 1:
                    console.print(
                        f"  [yellow]Network error, retrying ({attempt + 2}/{retries})...[/yellow]"
                    )
                    await self.page.wait_for_timeout(2000)
                    continue
                raise
        if last_err:
            raise last_err

    async def is_logged_in(self) -> bool:
        """Check if the session is logged in. Polls up to 15s for slow hydration.

        Guest mode also shows the composer textarea + Log in/Sign up — textarea
        alone must NOT count as logged in (that was treating guest as logged-in
        and then Enter-to-send hung for minutes).
        """
        check_js = r"""() => {
            const visible = (el) => !!(el && el.offsetParent !== null);
            const btns = Array.from(document.querySelectorAll('button, a'));
            const hasAuthCta = btns.some(b => {
                const t = (b.textContent || '').trim();
                return visible(b) && (t === 'Log in' || t === 'Sign in' || t === 'Sign up'
                    || t === 'ورود' || t === 'ثبت نام');
            });
            if (hasAuthCta) return 'no';
            const menu = document.querySelector('button.user-menu-btn');
            if (visible(menu)) return 'yes';
            if (document.querySelector('a.chat-item-drag-link, a[aria-label="chat-item"]')) return 'yes';
            // Avatar / account chip used by newer Qwen Studio UI
            if (document.querySelector('[class*="user-info"], [class*="avatar"][class*="user"]')) return 'yes';
            return 'pending';
        }"""
        try:
            # Fast path: already on chat with hydrated UI — skip navigation.
            url = self.page.url if self.page else ""
            if url.startswith(QWEN_CHAT_URL) and "/auth" not in url:
                quick = await self.page.evaluate(check_js)
                if quick == "yes":
                    return True
                if quick == "no":
                    return False

            await self._goto_resilient(QWEN_CHAT_URL, timeout=DEFAULT_TIMEOUT)
            deadline = time.time() + 8
            while time.time() < deadline:
                if "/auth" in self.page.url:
                    return False
                result = await self.page.evaluate(check_js)
                if result == "yes":
                    return True
                if result == "no":
                    return False
                await self.page.wait_for_timeout(200)
            return False
        except Exception:
            return False

    async def login(self, email: str, password: str) -> bool:
        """Login with email/password. Returns True on success."""
        try:
            self.last_login_error = None
            console.print("  [dim]Navigating to login...[/dim]")
            await self._goto_resilient(QWEN_AUTH_URL, timeout=LOGIN_TIMEOUT)
            await self.page.wait_for_timeout(AUTH_HYDRATE_WAIT)

            if "/auth" not in self.page.url:
                try:
                    await self.page.wait_for_selector("textarea.message-input-textarea", timeout=10000)
                    console.print("  [green]Already logged in![/green]")
                    return True
                except PlaywrightTimeout:
                    pass

            try:
                email_input = await self.page.wait_for_selector(
                    "input[placeholder='Enter Your Email']", timeout=15000
                )
            except PlaywrightTimeout:
                # A valid saved session can bounce us off the auth page
                # mid-flow — that means we are already logged in.
                if "/auth" not in self.page.url:
                    console.print("  [green]Session active (redirected to chat).[/green]")
                    return True
                console.print("  [red]Email input not found.[/red]")
                self.last_login_error = "error: login page did not load"
                return False
            if not email_input:
                console.print("  [red]Email input not found.[/red]")
                self.last_login_error = "error: login page did not load"
                return False
            await email_input.fill(email)

            password_input = await self.page.wait_for_selector(
                "input[placeholder='Enter Your Password']", timeout=5000
            )
            await password_input.fill(password)
            sign_in_btn = await self.page.wait_for_selector(
                "button:has-text('Sign in')", timeout=5000
            )
            # Wait until the button is enabled (empty fields leave it disabled).
            try:
                await self.page.wait_for_function(
                    """(el) => el && !el.disabled && el.getAttribute('aria-disabled') !== 'true'""",
                    arg=sign_in_btn,
                    timeout=5000,
                )
            except PlaywrightTimeout:
                pass
            # Splash overlays on /auth and post-login intercept Playwright clicks.
            await self._dismiss_popups()
            try:
                await sign_in_btn.click(timeout=5000)
            except Exception:
                await self._dismiss_popups()
                await self.page.evaluate("""() => {
                    const btn = Array.from(document.querySelectorAll('button'))
                        .find(b => (b.textContent || '').trim() === 'Sign in');
                    if (btn) btn.click();
                }""")

            console.print("  [dim]Waiting for login...[/dim]")
            try:
                await self.page.wait_for_url(lambda u: "/auth" not in u, timeout=30000)
            except PlaywrightTimeout:
                pass

            await self.page.wait_for_timeout(POST_LOGIN_SETTLE)
            if "/auth" in self.page.url:
                console.print("  [red]Login failed — still on auth page.[/red]")
                self.last_login_error = "auth_page"
                return False

            try:
                await self.page.wait_for_selector("textarea.message-input-textarea", timeout=12000)
            except PlaywrightTimeout:
                console.print("  [yellow]Chat UI did not fully load.[/yellow]")

            console.print("  [green]Login successful![/green]")
            return True
        except Exception as e:
            console.print(f"  [red]Login error: {e}[/red]")
            lowered = str(e).lower()
            if "err_" in lowered or "timeout" in lowered or "net::" in lowered:
                self.last_login_error = f"network: {e}"
            else:
                self.last_login_error = f"error: {e}"
            return False

    # ── Model ──────────────────────────────────────────────────────────────

    async def get_current_model(self) -> str:
        """Get the currently selected model name (fixed: uses .wms-trigger)."""
        try:
            model = await self.page.evaluate(r"""() => {
                const t = document.querySelector('.wms-trigger__text')?.textContent?.trim();
                if (t && t.length < 60) return t;
                const w = document.querySelector('.wms-trigger')?.textContent?.trim();
                if (w && w.length < 60) return w;
                const labels = document.querySelectorAll('.qwen-chat-v2-dropdown-menu-select-label');
                for (const el of labels) {
                    const txt = (el.textContent || '').trim();
                    if (txt.length < 40 && /^Qwen/i.test(txt)) return txt;
                }
                return '';
            }""")
            return model or "Unknown"
        except Exception:
            return "Unknown"

    async def select_model(self, model: Optional[str] = None):
        """Select a model or list available models."""
        try:
            trigger = await self.page.query_selector(".wms-trigger") or \
                      await self.page.query_selector('[aria-label="Select Model"]')
            if not trigger:
                console.print("  [yellow]Model selector not found.[/yellow]")
                return

            await trigger.evaluate("el => el.click()")
            try:
                await self.page.wait_for_selector("[role=option]", timeout=3000)
            except PlaywrightTimeout:
                pass

            if model:
                clicked = await self.page.evaluate("""(target) => {
                    const opts = document.querySelectorAll('[role=option]');
                    for (const o of opts) {
                        const t = (o.textContent || '').trim();
                        if (t.toLowerCase().includes(target.toLowerCase())) {
                            o.click();
                            return t;
                        }
                    }
                    return null;
                }""", model)
                if clicked:
                    console.print(f"  [green]Selected: {clicked}[/green]")
                else:
                    console.print(f"  [yellow]Model '{model}' not found.[/yellow]")
            else:
                current = await self.get_current_model()
                console.print(f"  [green]Current model: {current}[/green]")
                try:
                    await self.page.wait_for_selector('[role=listbox]', timeout=3000)
                except PlaywrightTimeout:
                    pass
                await self.page.wait_for_timeout(800)
                models = await self.page.evaluate(r"""() => {
                    return Array.from(document.querySelectorAll('[role=option]')).map(o => {
                        const t = (o.textContent || '').trim();
                        const m = t.match(/^[A-Za-z][\w.-]+/);
                        return m ? m[0] : t.substring(0, 30);
                    });
                }""")
                if models:
                    console.print("  [dim]Available:[/dim]")
                    for m in models:
                        mark = " [bold]<--[/bold]" if m.lower() in current.lower() else ""
                        console.print(f"    - {m}{mark}")

            await self.page.keyboard.press("Escape")
            await self.page.wait_for_timeout(300)
        except Exception as e:
            console.print(f"  [yellow]Model error: {e}[/yellow]")
            try: await self.page.keyboard.press("Escape")
            except Exception: pass

    # ── Mode Selection ────────────────────────────────────────────────────

    async def set_mode(self, mode_name: str):
        """Set qwen.ai mode (web, image, video, research, webdev, slides, ...)."""
        if mode_name not in MODE_MAP:
            console.print(f"  [yellow]Unknown mode: {mode_name}[/yellow]")
            console.print(f"  [dim]Available: {', '.join(k for k in MODE_MAP if k != 'chat')}[/dim]")
            return
        aliases = MODE_MAP[mode_name]
        if aliases is None:
            await self.new_chat()
            console.print("  [dim]Mode reset to default (chat).[/dim]")
            return
        try:
            await self._dismiss_popups()
            mode_btn = None
            for sel in MODE_BUTTON_SELECTORS:
                mode_btn = await self.page.query_selector(sel)
                if mode_btn:
                    break
            if not mode_btn:
                console.print("  [yellow]Mode selector not found.[/yellow]")
                return

            # Coordinate click is more reliable than ElementHandle.click here —
            # Ant Design overlays / splash often swallow Playwright's actionability click.
            box = await mode_btn.bounding_box()
            if box:
                await self.page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            else:
                await mode_btn.evaluate("el => el.click()")
            try:
                await self.page.wait_for_selector(
                    ".qwen-chat-v2-dropdown-menu-item.mode-select-common-item, "
                    ".qwen-chat-v2-dropdown-menu-item",
                    timeout=4000,
                )
            except PlaywrightTimeout:
                pass

            # Modes under the "More" submenu need an extra open step.
            needs_more = mode_name in ("slides", "art", "learning", "travel")
            if needs_more:
                await self.page.evaluate("""() => {
                    const items = document.querySelectorAll('.qwen-chat-v2-dropdown-menu-item');
                    for (const item of items) {
                        const t = (item.textContent || '').trim();
                        if (t === 'More' || t.startsWith('More') || t.includes('بیشتر')) {
                            item.dispatchEvent(new MouseEvent('mouseenter', {bubbles:true}));
                            item.click();
                            return true;
                        }
                    }
                    return false;
                }""")
                await self.page.wait_for_timeout(250)

            clicked = await self.page.evaluate("""(aliases) => {
                const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                const items = Array.from(document.querySelectorAll(
                    '.qwen-chat-v2-dropdown-menu-item'
                )).filter(el => !el.classList.contains('qwen-chat-v2-dropdown-menu-item-disabled'));
                for (const alias of aliases) {
                    const target = norm(alias);
                    for (const item of items) {
                        const label = item.querySelector('.qwen-chat-v2-dropdown-menu-item-label');
                        const t = norm(label ? label.textContent : item.textContent);
                        if (!t) continue;
                        if (t === target || t.startsWith(target) || target.startsWith(t) || t.includes(target)) {
                            item.click();
                            return (label ? label.textContent : item.textContent || '').trim().substring(0, 40);
                        }
                    }
                }
                return null;
            }""", aliases)
            if clicked:
                console.print(f"  [green]Mode: {mode_name} ({clicked})[/green]")
                await self.page.wait_for_timeout(POST_CLICK_WAIT)
                model = await self.get_current_model()
                if model != "Unknown":
                    console.print(f"  [dim]Model: {model}[/dim]")
            else:
                console.print(f"  [yellow]Mode '{mode_name}' not in menu.[/yellow]")
            await self.page.keyboard.press("Escape")
            await self.page.wait_for_timeout(150)
        except Exception as e:
            console.print(f"  [yellow]Mode error: {e}[/yellow]")
            try: await self.page.keyboard.press("Escape")
            except Exception: pass

    # ── Think Mode ────────────────────────────────────────────────────────

    async def set_think_mode(self, mode: str = "auto"):
        """Set think/reasoning mode: auto, think, or fast."""
        if mode not in THINK_MAP:
            console.print(f"  [yellow]Unknown think mode: {mode}[/yellow]")
            console.print(f"  [dim]Available: {', '.join(THINK_MAP.keys())}[/dim]")
            return
        targets = THINK_MAP[mode]
        try:
            await self._dismiss_popups()
            # Find the correct think dropdown by its label content (EN + FA)
            think_dropdown = await self.page.evaluate("""(allLabels) => {
                const selects = document.querySelectorAll('.qwen-chat-v2-dropdown-menu-select');
                const set = new Set(allLabels);
                for (const s of selects) {
                    const label = s.querySelector('.qwen-chat-v2-dropdown-menu-select-label');
                    if (label) {
                        const t = label.textContent.trim();
                        if (set.has(t)) {
                            return {index: Array.from(selects).indexOf(s), current: t};
                        }
                    }
                }
                return null;
            }""", list(THINK_LABELS_ALL))
            if not think_dropdown:
                console.print("  [yellow]Think mode selector not found.[/yellow]")
                return
            if think_dropdown["current"] in targets:
                console.print(f"  [dim]Think mode already: {mode}[/dim]")
                return

            # Click the correct think dropdown using the index we found
            dropdowns = await self.page.query_selector_all(".qwen-chat-v2-dropdown-menu-select")
            idx = think_dropdown["index"]
            if idx >= len(dropdowns):
                return
            try:
                await dropdowns[idx].click(timeout=3000)
            except Exception:
                await dropdowns[idx].evaluate("el => el.click()")
            try:
                await self.page.wait_for_selector(".qwen-chat-v2-dropdown-menu-item", timeout=2000)
            except PlaywrightTimeout:
                pass

            clicked = await self.page.evaluate("""(targets) => {
                const items = document.querySelectorAll('.qwen-chat-v2-dropdown-menu-item');
                const set = new Set(targets);
                for (const i of items) {
                    const t = (i.textContent||'').trim();
                    if (set.has(t)) { i.click(); return t; }
                }
                return null;
            }""", targets)
            if clicked:
                console.print(f"  [green]Think mode: {mode} ({clicked})[/green]")
            else:
                console.print(f"  [yellow]Could not set think mode to '{mode}'.[/yellow]")

            await self.page.wait_for_timeout(200)
            await self.page.keyboard.press("Escape")
            await self.page.wait_for_timeout(200)
        except Exception as e:
            console.print(f"  [yellow]Think mode error: {e}[/yellow]")
            try: await self.page.keyboard.press("Escape")
            except Exception: pass

    # ── File Upload ───────────────────────────────────────────────────────

    async def upload_file(self, file_path: str):
        try:
            inp = await self.page.query_selector("input[type='file']")
            if not inp:
                console.print("  [yellow]File input not found.[/yellow]")
                return
            await inp.set_input_files(str(Path(file_path).resolve()))
            console.print(f"  [green]Uploaded: {Path(file_path).name}[/green]")
        except Exception as e:
            console.print(f"  [yellow]Upload failed: {e}[/yellow]")

    # ── Chat Actions ──────────────────────────────────────────────────────

    async def _dismiss_popups(self):
        # Splash overlay intercepts clicks (seen on en-US headless sessions).
        try:
            await self.page.evaluate(r"""() => {
                const splash = document.querySelector('#splash-screen, #splash-main-container');
                if (splash) splash.remove();
                document.querySelectorAll('[id*=splash]').forEach(el => {
                    try { el.remove(); } catch (e) {}
                });
                // Skeleton overlays can block the composer after /c/<id> navigation.
                document.querySelectorAll('.chat-detail-skeleton').forEach(el => {
                    try { el.remove(); } catch (e) {}
                });
                // "Which response do you prefer?" / studio feedback overlays
                const blockers = Array.from(document.querySelectorAll('button, [role=button]'));
                for (const b of blockers) {
                    const t = (b.textContent || '').trim();
                    if (t === 'Skip' || t === 'Close' || t === '×' || t === '✕') {
                        try { b.click(); } catch (e) {}
                    }
                }
            }""")
        except Exception:
            pass
        try:
            await self.page.wait_for_selector(
                ".chat-detail-skeleton", state="hidden", timeout=2000
            )
        except Exception:
            pass
        for _ in range(3):
            try:
                popup = await self.page.query_selector(
                    "[class*=modal] [class*=close], [class*=dialog] [class*=close], "
                    "[class*=popover] [class*=close], [class*=feedback] [class*=close]"
                )
                if popup:
                    try:
                        visible = await popup.is_visible()
                        if visible:
                            await popup.click(timeout=3000)
                            await self.page.wait_for_timeout(250)
                            continue
                    except Exception:
                        pass
                mask = await self.page.query_selector("[class*=mask]")
                if mask:
                    try:
                        if await mask.is_visible():
                            await self.page.keyboard.press("Escape")
                            await self.page.wait_for_timeout(250)
                            continue
                    except Exception:
                        pass
                break
            except Exception:
                break

    async def new_chat(self):
        """Start a new chat."""
        try:
            await self._dismiss_popups()
            for sel in [
                '[aria-label="New Chat"]',
                "button:has-text('New Chat')",
                "button:has-text('New chat')",
                "button:has-text('\u06af\u0641\u062a\u06af\u0648\u06cc \u062c\u062f\u06cc\u062f')",
                "a[href='/']",
            ]:
                btn = await self.page.query_selector(sel)
                if btn:
                    try:
                        if await btn.is_visible():
                            try:
                                await btn.click(timeout=3000)
                            except Exception:
                                await btn.evaluate("el => el.click()")
                            try:
                                await self.page.wait_for_selector("textarea.message-input-textarea", timeout=5000)
                            except PlaywrightTimeout:
                                pass
                            console.print("  [dim]New chat started.[/dim]")
                            return
                    except Exception:
                        pass
            await self.page.goto(QWEN_CHAT_URL, wait_until="domcontentloaded")
            try:
                await self.page.wait_for_selector("textarea.message-input-textarea", timeout=8000)
            except PlaywrightTimeout:
                pass
            console.print("  [dim]Navigated to new chat.[/dim]")
        except Exception as e:
            console.print(f"  [yellow]New chat error: {e}[/yellow]")

    async def get_chat_history(self, limit: int = 20) -> list:
        """Get recent chat history. Returns [{title, id}, ...]."""
        try:
            return await self.page.evaluate("""(limit) => {
                const items = document.querySelectorAll(
                    'a.chat-item-drag-link, a[aria-label="chat-item"]'
                );
                const result = [];
                const seen = new Set();
                for (let i = 0; i < items.length && result.length < limit; i++) {
                    const title = items[i].textContent?.trim() || 'Untitled';
                    const href = items[i].getAttribute('href') || '';
                    const idMatch = href.match(/\\/c\\/([\\w-]+)/);
                    const id = idMatch ? idMatch[1] : '';
                    const key = id || (href + '|' + title);
                    if (seen.has(key)) continue;
                    seen.add(key);
                    result.push({ title, id });
                }
                return result;
            }""", limit)
        except Exception:
            return []

    async def open_chat(self, index: int):
        """Open a chat from history by 1-based index."""
        try:
            items = await self.page.query_selector_all(
                'a.chat-item-drag-link, a[aria-label="chat-item"]'
            )
            uniq = []
            seen = set()
            for el in items:
                href = await el.get_attribute("href") or ""
                key = href or id(el)
                if key in seen:
                    continue
                seen.add(key)
                uniq.append(el)
            items = uniq
            if index < 1 or index > len(items):
                console.print(f"  [yellow]Invalid index. History has {len(items)} chats (1-{len(items)}).[/yellow]")
                return
            target = items[index - 1]
            title = await target.text_content()
            console.print(f"  [dim]Opening: {title.strip()}[/dim]")
            await target.click()
            try:
                await self.page.wait_for_selector("textarea.message-input-textarea", timeout=6000)
            except PlaywrightTimeout:
                pass
            console.print("  [green]Chat opened.[/green]")
        except Exception as e:
            console.print(f"  [yellow]Could not open chat: {e}[/yellow]")

    async def get_current_chat_id(self) -> str:
        """Get the upstream chat UUID.

        Prefer network-captured chat_id (completions?chat_id=...), then URL /c/<uuid>.
        Ignores placeholder segments like /c/guest.
        """
        if self._looks_like_chat_id(self._last_chat_id):
            return self._last_chat_id
        try:
            url = self.page.url
            m = url.split('/c/')
            if len(m) > 1:
                cid = m[1].split('/')[0].split('?')[0].strip()
                if self._looks_like_chat_id(cid):
                    self._last_chat_id = cid
                    return cid
            return ''
        except Exception:
            return ''

    async def wait_for_chat_id(self, timeout_ms: int = 8000) -> str:
        """Poll until a real chat UUID appears (network capture or URL)."""
        deadline = time.time() + (timeout_ms / 1000)
        while time.time() < deadline:
            cid = await self.get_current_chat_id()
            if cid:
                return cid
            await self.page.wait_for_timeout(250)
        return await self.get_current_chat_id()

    async def open_chat_by_id(self, chat_id: str):
        """Open a specific chat by its ID (navigates to /c/<id>)."""
        if not self._looks_like_chat_id(chat_id):
            console.print(f"  [yellow]Invalid chat id: {chat_id!r}[/yellow]")
            return
        try:
            url = f"{QWEN_CHAT_URL}c/{chat_id}"
            console.print(f"  [dim]Navigating to /c/{chat_id}...[/dim]")
            await self.page.goto(url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT)
            await self._dismiss_popups()
            try:
                await self.page.wait_for_selector("textarea.message-input-textarea", timeout=10000)
                console.print("  [green]Chat opened.[/green]")
            except PlaywrightTimeout:
                console.print("  [yellow]Page loaded but textarea not found.[/yellow]")
            self._remember_chat_id(chat_id)
        except Exception as e:
            console.print(f"  [yellow]Could not open chat: {e}[/yellow]")

    async def stop_generation(self) -> bool:
        """Click stop button. Returns True if stopped."""
        try:
            btn = await self.page.query_selector(
                "button:has-text('Stop generation'), button:has-text('Stop'), "
                "button:has-text('\u062a\u0648\u0642\u0641')"
            )
            if btn:
                try:
                    if await btn.is_visible():
                        await btn.click()
                        await self.page.wait_for_timeout(1000)
                        console.print("  [yellow]Generation stopped.[/yellow]")
                        return True
                except Exception:
                    pass
            return False
        except Exception:
            return False

    # ── Message Sending ───────────────────────────────────────────────────

    async def _click_send_button(self) -> bool:
        """Click the composer Send control (Enter is unreliable on guest/studio UI)."""
        try:
            clicked = await self.page.evaluate(r"""() => {
                const visible = (el) => !!(el && el.offsetParent !== null);
                const nodes = Array.from(document.querySelectorAll('button, [role=button]'));
                const score = (el) => {
                    const al = (el.getAttribute('aria-label') || '').toLowerCase();
                    const t = (el.textContent || '').trim().toLowerCase();
                    if (al === 'send' || al.includes('send message')) return 3;
                    if (t === 'send' || t === 'ارسال') return 2;
                    if (al.includes('send')) return 1;
                    return 0;
                };
                let best = null, bestScore = 0;
                for (const el of nodes) {
                    if (!visible(el) || el.disabled) continue;
                    const s = score(el);
                    if (s > bestScore) { best = el; bestScore = s; }
                }
                if (!best) return null;
                best.click();
                return best.getAttribute('aria-label') || (best.textContent || '').trim() || 'send';
            }""")
            return bool(clicked)
        except Exception:
            return False

    async def send_message(self, message: str) -> str:
        """Send a message and wait for the response. Supports Ctrl+C to stop."""
        if not self.page:
            raise RuntimeError("Browser not started")
        if "/auth" in self.page.url:
            await self.page.goto(QWEN_CHAT_URL, wait_until="domcontentloaded")
            await self.page.wait_for_timeout(1500)

        textarea = await self.page.wait_for_selector(
            "textarea.message-input-textarea", timeout=15000
        )
        if not textarea:
            raise RuntimeError("Chat input not found")

        await self._dismiss_popups()
        try:
            await textarea.click(timeout=3000)
        except Exception:
            await self._dismiss_popups()
            await textarea.click(timeout=3000, force=True)
        await self.page.wait_for_timeout(PRE_SEND_WAIT)
        await textarea.fill(message)
        await self.page.wait_for_timeout(PRE_SEND_WAIT)

        msg_count = await self._count_messages()
        user_count_before = len(await self.page.query_selector_all(".qwen-chat-message-user"))

        # Prefer Send button — Enter often does nothing on current Qwen Studio UI.
        console.print("  [dim]Sending...[/dim]")
        clicked = await self._click_send_button()
        if not clicked:
            await textarea.press("Enter")

        sent = await self._wait_user_message(user_count_before)
        if not sent:
            # Fast fallback: Enter then Send (no full-page reload — that cost minutes).
            console.print("  [yellow]Retry send...[/yellow]")
            await self._dismiss_popups()
            try:
                await textarea.click(timeout=2000, force=True)
            except Exception:
                textarea = await self.page.wait_for_selector(
                    "textarea.message-input-textarea", timeout=8000
                )
                await textarea.click(timeout=2000, force=True)
            await textarea.fill(message)
            await textarea.press("Enter")
            await self._click_send_button()
            sent = await self._wait_user_message(user_count_before)
            if not sent:
                raise RuntimeError("Message failed to send (user bubble never appeared)")

        return await self._wait_for_response(msg_count)

    async def _wait_user_message(self, count_before: int) -> bool:
        try:
            await self.page.wait_for_function(
                "(n) => document.querySelectorAll('.qwen-chat-message-user').length > n",
                arg=count_before, timeout=SEND_VERIFY_TIMEOUT, polling=100,
            )
            return True
        except PlaywrightTimeout:
            return False

    async def _count_messages(self) -> int:
        try:
            return len(await self.page.query_selector_all(".qwen-chat-message-assistant"))
        except Exception:
            return 0

    # JS predicate for _wait_for_response: state lives on `window` so it
    # survives across the repeated in-browser polling calls that
    # wait_for_function makes without round-tripping to Python each time.
    _RESPONSE_DONE_JS = r"""
        ({countBefore, stableMs}) => {
            const state = (window.__qwenPoll && window.__qwenPoll.countBefore === countBefore)
                ? window.__qwenPoll
                : (window.__qwenPoll = { countBefore, lastText: '', lastChangeAt: Date.now(), stopGoneAt: null });
            const msgs = document.querySelectorAll('.qwen-chat-message-assistant');
            if (msgs.length <= countBefore) return false;
            const last = msgs[msgs.length - 1];
            const md = last.querySelector('.custom-qwen-markdown');
            const text = (md ? md.innerText : last.innerText || '').trim();
            if (!text) return false;
            const now = Date.now();
            if (text !== state.lastText) {
                state.lastText = text;
                state.lastChangeAt = now;
            }
            const stopBtn = Array.from(document.querySelectorAll('button')).some(b => {
                const t = (b.textContent || '').trim();
                return t.includes('Stop generation') || t === 'Stop' || t.includes('\u062a\u0648\u0642\u0641');
            });
            if (!stopBtn) {
                if (state.stopGoneAt === null) state.stopGoneAt = now;
                if (now - state.stopGoneAt >= 250) return true;
            } else {
                state.stopGoneAt = null;
            }
            return (now - state.lastChangeAt) >= stableMs;
        }
    """

    async def _wait_for_response(self, count_before: int) -> str:
        """Wait for the assistant's reply to finish streaming.

        The stability/completion check runs entirely inside the page via
        wait_for_function (polling every POLL_INTERVAL ms in-browser) instead
        of round-tripping to Python for every tick. We chunk the wait so
        Ctrl+C (/stop) is still checked periodically.
        """
        start = time.time()
        timeout_s = RESPONSE_TIMEOUT / 1000
        self._stop_requested = False
        chunk_ms = 4000

        while time.time() - start < timeout_s:
            if self._stop_requested:
                await self.stop_generation()
                break
            remaining_ms = int((timeout_s - (time.time() - start)) * 1000)
            wait_ms = max(200, min(chunk_ms, remaining_ms))
            try:
                await self.page.wait_for_function(
                    self._RESPONSE_DONE_JS,
                    arg={"countBefore": count_before, "stableMs": STABLE_MS},
                    timeout=wait_ms,
                    polling=POLL_INTERVAL,
                )
                break  # condition satisfied
            except PlaywrightTimeout:
                continue
            except Exception:
                break  # page navigated or context lost — fall through to extraction

        console_printed_timeout = time.time() - start >= timeout_s
        if console_printed_timeout:
            console.print("  [yellow]Response timeout.[/yellow]")
        await self._dismiss_feedback()
        messages = await self.page.query_selector_all(".qwen-chat-message-assistant")
        if len(messages) > count_before:
            text = await self._extract_response_text(messages[-1])
            if text:
                return text
        if console_printed_timeout:
            raise TimeoutError("Response timeout: no assistant message received")
        return "[Timeout: No response received]"

    async def _dismiss_feedback(self):
        """Dismiss feedback popups by pressing Escape."""
        try:
            for _ in range(2):
                await self.page.keyboard.press("Escape")
                await self.page.wait_for_timeout(200)
        except Exception:
            pass

    async def _extract_response_text(self, element) -> str:
        try:
            md = await element.query_selector(".custom-qwen-markdown")
            if md:
                return (await md.inner_text()).strip()
            text = await element.inner_text()
            for phrase in RESPONSE_NOISE:
                text = text.replace(phrase, "")
            # Remove lines that are mostly noise (feedback popup remnants)
            lines = [l for l in text.split('\n') if l.strip() and len(l.strip()) > 2]
            return '\n'.join(lines).strip()
        except Exception:
            return "[Error extracting response]"

    # ── Image Download ────────────────────────────────────────────────────

    async def download_generated_images(self, output_dir: str = ".") -> list:
        """Download images from the last assistant message. Returns saved paths."""
        saved = []
        try:
            messages = await self.page.query_selector_all(".qwen-chat-message-assistant")
            if not messages:
                console.print("  [yellow]No assistant messages.[/yellow]")
                return saved
            # The 128px loading spinner also renders as <img>; wait until a
            # full-size, fully-loaded image replaces it (up to ~60s).
            real_images = []
            deadline = time.time() + 60
            while time.time() < deadline:
                images = await messages[-1].query_selector_all("img")
                real_images = []
                for img in images:
                    try:
                        meta = await img.evaluate(
                            "el => ({w: el.naturalWidth, h: el.naturalHeight, "
                            "complete: el.complete, src: el.src})"
                        )
                    except Exception:
                        continue
                    if meta.get("complete") and meta.get("w", 0) >= 256 \
                       and (meta.get("src") or "").startswith("http"):
                        real_images.append(img)
                if real_images:
                    break
                await self.page.wait_for_timeout(400)
            if not real_images:
                if images:
                    console.print("  [yellow]Only placeholder/loading images found.[/yellow]")
                else:
                    console.print("  [yellow]No images in last response.[/yellow]")
                return saved
            images = real_images

            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)

            for i, img in enumerate(images):
                # Images are lazy-loaded: the src ATTRIBUTE may be empty while
                # only the src PROPERTY is set by JS — read the property.
                try:
                    src = await img.evaluate("el => el.src")
                except Exception:
                    src = await img.get_attribute("src")
                if not src or src.startswith(("data:", "blob:")) or not src.startswith("http"):
                    continue
                try:
                    result = await self.page.evaluate("""async (url) => {
                        try {
                            const r = await fetch(url);
                            const b = await r.blob();
                            const rd = new FileReader();
                            return new Promise(res => { rd.onload = () => res(rd.result); rd.readAsDataURL(b); });
                        } catch(e) { return null; }
                    }""", src)
                    if result and result.startswith("data:image"):
                        header, data = result.split(",", 1)
                        ext = "png"
                        for e in ["jpeg", "jpg", "webp", "gif"]:
                            if e in header:
                                ext = e if e != "jpeg" else "jpg"
                                break
                        fname = f"qwen_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{i+1}.{ext}"
                        fpath = out / fname
                        fpath.write_bytes(base64.b64decode(data))
                        saved.append(str(fpath))
                        console.print(f"  [green]Saved: {fname}[/green]")
                    else:
                        # In-page fetch can fail (CORS) — fall back to the
                        # browser context's request (same cookies, no CORS).
                        resp = await self.context.request.get(src)
                        if resp.ok:
                            body = await resp.body()
                            ext = "png"
                            ctype = resp.headers.get("content-type", "")
                            for e in ["jpeg", "jpg", "webp", "gif"]:
                                if e in ctype:
                                    ext = e if e != "jpeg" else "jpg"
                                    break
                            fname = f"qwen_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{i+1}.{ext}"
                            fpath = out / fname
                            fpath.write_bytes(body)
                            saved.append(str(fpath))
                            console.print(f"  [green]Saved: {fname}[/green]")
                        else:
                            console.print(f"  [yellow]Image {i+1}: HTTP {resp.status}[/yellow]")
                except Exception as e:
                    console.print(f"  [yellow]Image {i+1} failed: {e}[/yellow]")

            if not saved:
                console.print("  [yellow]No downloadable images (blob/data URLs).[/yellow]")
        except Exception as e:
            console.print(f"  [yellow]Download error: {e}[/yellow]")
        return saved

    async def download_generated_videos(self, output_dir: str = ".") -> list:
        """Download <video> sources from the last assistant message."""
        saved = []
        try:
            messages = await self.page.query_selector_all(".qwen-chat-message-assistant")
            if not messages:
                return saved
            deadline = time.time() + 90
            videos = []
            while time.time() < deadline:
                videos = await messages[-1].query_selector_all("video, video source")
                ready = []
                for el in videos:
                    try:
                        src = await el.evaluate("el => el.currentSrc || el.src || el.getAttribute('src')")
                    except Exception:
                        src = await el.get_attribute("src")
                    if src and src.startswith("http"):
                        ready.append(src)
                if ready:
                    break
                await self.page.wait_for_timeout(500)
            if not ready:
                console.print("  [yellow]No video sources in last response.[/yellow]")
                return saved

            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)
            for i, src in enumerate(dict.fromkeys(ready)):
                try:
                    resp = await self.context.request.get(src)
                    if not resp.ok:
                        console.print(f"  [yellow]Video {i+1}: HTTP {resp.status}[/yellow]")
                        continue
                    body = await resp.body()
                    ctype = resp.headers.get("content-type", "")
                    ext = "mp4"
                    for e in ("webm", "mov", "mkv", "mp4"):
                        if e in ctype or src.lower().endswith(f".{e}"):
                            ext = e
                            break
                    fname = f"qwen_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{i+1}.{ext}"
                    fpath = out / fname
                    fpath.write_bytes(body)
                    saved.append(str(fpath))
                    console.print(f"  [green]Saved: {fname}[/green]")
                except Exception as e:
                    console.print(f"  [yellow]Video {i+1} failed: {e}[/yellow]")
        except Exception as e:
            console.print(f"  [yellow]Video download error: {e}[/yellow]")
        return saved

    # ── Export ─────────────────────────────────────────────────────────────

    async def export_chat(self, filepath: str):
        """Export current conversation to markdown (preserves interleaved order)."""
        try:
            messages = await self.page.evaluate("""() => {
                const result = [];
                const allMsgs = document.querySelectorAll('.qwen-chat-message-user, .qwen-chat-message-assistant');
                for (const msg of allMsgs) {
                    const isUser = msg.classList.contains('qwen-chat-message-user');
                    const md = msg.querySelector('.custom-qwen-markdown');
                    result.push({role: isUser ? 'user' : 'assistant', text: md ? md.innerText : msg.innerText});
                }
                return result;
            }""")
            if not messages:
                console.print("  [yellow]No messages to export.[/yellow]")
                return
            out = Path(filepath)
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                f.write(f"# Qwen Chat Export\n*Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n")
                for msg in messages:
                    label = "## You" if msg["role"] == "user" else "## Qwen"
                    f.write(f"{label}\n\n{msg['text'].strip()}\n\n---\n\n")
            console.print(f"  [green]Exported to: {filepath}[/green]")
        except Exception as e:
            console.print(f"  [yellow]Export failed: {e}[/yellow]")

    # ── Delete Chat ───────────────────────────────────────────────────────

    async def delete_chat(self, index: int):
        try:
            items = await self.page.query_selector_all(
                'a.chat-item-drag-link, a[aria-label="chat-item"]'
            )
            if index < 1 or index > len(items):
                console.print(f"  [yellow]Invalid index. History has {len(items)} chats.[/yellow]")
                return
            target = items[index - 1]
            title = await target.text_content()
            parent = await target.evaluate_handle("el => el.parentElement")
            menu_btn = await parent.query_selector("button.chat-item-drag-web-default-btn")
            if not menu_btn:
                menu_btn = await target.evaluate_handle("""el => {
                    const p = el.parentElement;
                    for (const b of p.querySelectorAll('button')) {
                        if (b.getAttribute('aria-label') === 'Chat Menu') return b;
                    }
                    return null;
                }""")
            if menu_btn:
                await menu_btn.click()
                await self.page.wait_for_timeout(800)
                delete_opt = await self.page.query_selector(
                    "[class*=dropdown-menu-item]:has-text('Delete'), "
                    "[class*=dropdown-menu-item]:has-text('\u062d\u0630\u0641')"
                )
                if delete_opt:
                    await delete_opt.click()
                    await self.page.wait_for_timeout(1000)
                    console.print(f"  [green]Deleted: {title.strip()}[/green]")
                else:
                    console.print("  [yellow]Delete option not found.[/yellow]")
                    await self.page.keyboard.press("Escape")
            else:
                console.print("  [yellow]Chat menu button not found.[/yellow]")
        except Exception as e:
            console.print(f"  [yellow]Delete failed: {e}[/yellow]")


# ─── CLI Commands ────────────────────────────────────────────────────────────

@click.group()
@click.version_option(version="3.1.1", prog_name="qwen-cli")
def cli():
    """Qwen CLI v3.1.1 — Command-line interface for chat.qwen.ai"""
    pass


@cli.command()
@click.option("--email", "-e", prompt=True, help="Account email")
@click.option("--password", "-p", prompt=True, hide_input=True, help="Account password")
@click.option("--name", "-n", default=None, help="Account name (default: email prefix)")
@click.option("--yes", "-y", is_flag=True, default=False,
              help="Overwrite an existing account without asking (non-interactive use).")
def add(email: str, password: str, name: Optional[str], yes: bool):
    """Add a new qwen.ai account."""
    accounts = load_accounts()
    account_name = name or email.split("@")[0]
    if account_name in accounts and not yes:
        if not click.confirm(f"Account '{account_name}' exists. Overwrite?", default=False):
            return
    accounts[account_name] = {
        "email": email, "password": password,
        "added_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_accounts(accounts)
    console.print(f"[green]Account '{account_name}' added.[/green]")
    console.print(f"[dim]Use: qwen-cli chat -a {account_name} -p \"your prompt\"[/dim]")


@cli.command()
@click.option("--email", "-e", required=True, help="Account email")
@click.option("--password", "-p", required=True, help="Account password")
@click.option("--name", "-n", default=None, help="Account name (default: email prefix)")
@click.option("--headless/--no-headless", default=True, help="Browser mode")
def verify(email: str, password: str, name: Optional[str], headless: bool):
    """Attempt a REAL login without saving anything; prints a JSON result.

    Used by the ReelForge settings UI so wrong credentials are caught at
    add-time instead of at first AI use. Exits 0 on success, 3 on failure.
    """
    # Keep Rich diagnostics off stdout so callers can parse a single JSON line.
    console.file = sys.stderr
    account_name = name or email.split("@")[0]

    async def _run() -> dict:
        async with QwenClient(account_name, headless=headless) as client:
            ok = await client.login(email, password)
            detail = client.last_login_error
            return {"success": ok, "detail": detail}

    try:
        result = asyncio.run(_run())
    except Exception as e:
        result = {"success": False, "detail": f"error: {e}"}

    if not result["success"]:
        detail = result.get("detail") or "unknown"
        if detail == "auth_page":
            reason = "bad_credentials"
        elif isinstance(detail, str) and detail.startswith("network:"):
            reason = "network"
        else:
            reason = "unknown"
        print(json.dumps({
            "success": False,
            "reason": reason,
            "detail": detail,
        }))
        sys.exit(3)

    print(json.dumps({"success": True, "reason": None, "detail": None}))


@cli.command(name="list")
def list_accounts():
    """List all saved accounts."""
    accounts = load_accounts()
    if not accounts:
        console.print("[yellow]No accounts yet.[/yellow]")
        console.print("Use [cyan]qwen-cli add[/cyan] to add one.")
        return
    table = Table(title="Saved Accounts", box=box.ROUNDED)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Email", style="white")
    table.add_column("Added", style="dim")
    table.add_column("Profile", style="green")
    for name, info in accounts.items():
        has = "[green]Yes[/green]" if get_profile_path(name).exists() else "[dim]No[/dim]"
        table.add_row(name, info["email"], info.get("added_at", "N/A"), has)
    console.print(table)


@cli.command()
@click.argument("name", required=False)
def remove(name: Optional[str]):
    """Remove a saved account and its browser profile."""
    accounts = load_accounts()
    if not accounts:
        console.print("[yellow]No accounts to remove.[/yellow]")
        return
    if not name:
        names = list(accounts.keys())
        for i, n in enumerate(names, 1):
            console.print(f"  [cyan]{i}[/cyan]. {n} ({accounts[n]['email']})")
        choice = click.prompt("Select number", type=int)
        if 1 <= choice <= len(names):
            name = names[choice - 1]
        else:
            console.print("[red]Invalid selection.[/red]")
            return
    if name not in accounts:
        console.print(f"[red]Account '{name}' not found.[/red]")
        return
    if click.confirm(f"Remove '{name}' ({accounts[name]['email']}) and profile?", default=False):
        p = get_profile_path(name)
        if p.exists(): shutil.rmtree(p)
        del accounts[name]
        save_accounts(accounts)
        console.print(f"[green]Account '{name}' removed.[/green]")


@cli.command()
@click.option("--account", "-a", default=None, help="Account name or email substring")
@click.option("--headless/--no-headless", default=True, help="Browser mode (default: headless)")
@click.option("--model", "-m", default=None, help="Model name (e.g. Qwen3.8-Max)")
@click.option("--mode", default=None, type=click.Choice(list(MODE_MAP.keys())),
              help="Mode: web, image, video, research, webdev, slides, ...")
@click.option("--think", "-t", default=None, type=click.Choice(list(THINK_MAP.keys())),
              help="Think mode: auto, think, fast")
@click.option("--new", "-n", is_flag=True, help="Start a new chat")
@click.option("--prompt", "-p", multiple=True, help="Prompt(s) — use multiple -p for multi-turn")
@click.option("--prompt-file", "-P", default=None, help="File with prompts (separated by ---)")
@click.option("--continue", "-c", "continue_chat", is_flag=True, help="Resume last chat")
@click.option("--chat-id", default=None, help="Open a specific chat by ID")
@click.option("--file", "-f", default=None, help="Upload a file before sending")
@click.option("--list-models", "-l", is_flag=True, help="List available models")
@click.option("--history", is_flag=True, help="Show chat history with IDs")
@click.option("--open-chat", default=None, type=int, help="Open chat #N from history")
@click.option("--export", default=None, help="Export chat to markdown file")
@click.option("--download", "-d", default=None, help="Download generated images to directory")
@click.option("--raw", is_flag=True, help="Output raw text (no markdown rendering)")
@click.option("--wait", "-w", default=0, type=int, help="Extra seconds to wait between prompts")
def chat(account, headless, model, mode, think, new, prompt, prompt_file,
         continue_chat, chat_id, file, list_models, history, open_chat,
         export, download, raw, wait):
    """Start a chat session with Qwen AI.

    Multi-turn:  qwen-cli chat -a ACC -p "context" -p "task" -p "style"
    Prompt file: qwen-cli chat -a ACC -P flow.txt
    Continue:    qwen-cli chat -a ACC -c -p "next question"
    By chat ID:  qwen-cli chat -a ACC --chat-id abc123 -p "continue"
    History:     qwen-cli chat -a ACC --history
    Pipe:        echo "prompt" | qwen-cli chat -a ACC --raw

    Prompt file format:
      First prompt here.
      ---
      Second prompt here.
      ---
      Third prompt here.
    """
    accounts = load_accounts()
    if not accounts:
        console.print("[red]No accounts found. Use 'qwen-cli add' first.[/red]")
        sys.exit(1)

    # Resolve account
    if account:
        if account not in accounts:
            match = next((n for n, i in accounts.items() if account.lower() in i["email"].lower()), None)
            if match:
                console.print(f"[dim]Resolved '{account}' -> '{match}'[/dim]")
                account = match
            else:
                console.print(f"[red]Account '{account}' not found.[/red]")
                for n, i in accounts.items():
                    console.print(f"  [cyan]{n}[/cyan] ({i['email']})")
                sys.exit(1)
    else:
        if len(accounts) == 1:
            account = list(accounts.keys())[0]
        else:
            console.print("[bold]Select account:[/bold]")
            names = list(accounts.keys())
            for i, n in enumerate(names, 1):
                console.print(f"  [cyan]{i}[/cyan]. {n} ({accounts[n]['email']})")
            choice = click.prompt("Number", type=int)
            if 1 <= choice <= len(names):
                account = names[choice - 1]
            else:
                sys.exit(1)

    acc = accounts[account]
    email, password = acc["email"], acc["password"]

    # Stdin pipe
    single_prompt = prompt[0] if len(prompt) == 1 else None
    has_prompts = len(prompt) > 0 or prompt_file is not None
    if not has_prompts and not list_models and not history and open_chat is None \
       and not continue_chat and not chat_id and not sys.stdin.isatty():
        try:
            import msvcrt
            if msvcrt.kbhit(): single_prompt = sys.stdin.read().strip()
        except ImportError:
            try:
                import fcntl
                fd = sys.stdin.fileno()
                fl = fcntl.fcntl(fd, fcntl.F_GETFL)
                fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
                try: single_prompt = sys.stdin.read().strip()
                except (IOError, OSError): pass
                finally: fcntl.fcntl(fd, fcntl.F_SETFL, fl)
            except (ImportError, OSError): pass

    # Load prompts from file
    file_prompts = []
    if prompt_file:
        pf = Path(prompt_file)
        if not pf.exists():
            console.print(f"[red]File not found: {prompt_file}[/red]")
            sys.exit(1)
        content = pf.read_text(encoding="utf-8")
        file_prompts = [p.strip() for p in content.split("---") if p.strip()]

    all_prompts = file_prompts + list(prompt)

    asyncio.run(_run_chat(
        account, email, password, headless, model, mode, think, new,
        all_prompts, file, list_models, history, open_chat, chat_id,
        export, download, raw, continue_chat, wait, single_prompt,
    ))


async def _run_chat(
    account_name, email, password, headless, model, mode, think,
    new_chat, all_prompts, upload_file, list_models, show_history,
    open_chat_idx, chat_id, export_path, download_dir, raw,
    continue_chat, wait_between, single_prompt,
):
    extra = []
    if mode: extra.append(f"Mode: {mode}")
    if think: extra.append(f"Think: {think}")
    extra_str = " | ".join(extra) if extra else "Chat"
    console.print(Panel(
        f"[bold]Account:[/bold] {account_name} ({email})\n"
        f"[bold]Session:[/bold] {extra_str}\n"
        f"[bold]Browser:[/bold] {'Headless' if headless else 'Visible'}",
        title="Qwen CLI v3.1.1",
        border_style="cyan",
    ))

    async with QwenClient(account_name, headless=headless) as client:
        # ── Login ─────────────────────────────────────────────────────────
        with console.status("[bold cyan]Checking session...[/bold cyan]"):
            logged_in = await client.is_logged_in()
        if not logged_in:
            console.print("[yellow]Not logged in. Logging in...[/yellow]")
            if not await client.login(email, password):
                console.print("[red]Login failed.[/red]")
                sys.exit(1)
        else:
            console.print("[green]Session active[/green]")

        # Ensure we're on chat page
        if "/auth" in client.page.url:
            await client.page.goto(QWEN_CHAT_URL, wait_until="domcontentloaded")
            await client.page.wait_for_timeout(1200)

        try:
            await client.page.wait_for_selector("textarea.message-input-textarea", timeout=15000)
        except PlaywrightTimeout:
            console.print("[red]Chat page failed to load.[/red]")
            sys.exit(1)

        await client._dismiss_popups()

        # ── Model display ─────────────────────────────────────────────────
        current_model = await client.get_current_model()
        console.print(f"[dim]Model: {current_model}[/dim]")

        # ── List models ───────────────────────────────────────────────────
        if list_models:
            await client.select_model(None)
            return

        # ── Show history (with IDs) ────────────────────────────────────────
        if show_history:
            # Wait for sidebar to load
            console.print("[dim]Loading history...[/dim]")
            try:
                await client.page.wait_for_selector(
                    'a.chat-item-drag-link, a[aria-label="chat-item"]', timeout=10000
                )
            except PlaywrightTimeout:
                pass
            history = await client.get_chat_history(20)
            if not history:
                console.print("[yellow]No chat history.[/yellow]")
            else:
                current_id = await client.get_current_chat_id()
                table = Table(title="Chat History", box=box.ROUNDED)
                table.add_column("#", style="dim", width=4)
                table.add_column("Title", style="white", max_width=45)
                table.add_column("Chat ID", style="cyan", max_width=20)
                table.add_column("Cur", style="green", width=4)
                for i, item in enumerate(history, 1):
                    is_current = "[green]<[/green]" if item.get("id") == current_id else ""
                    chat_id_short = item.get("id", "")[:16] + ("..." if len(item.get("id", "")) > 16 else "")
                    table.add_row(str(i), item["title"][:45], chat_id_short, is_current)
                console.print(table)
                console.print("[dim]Use: --open-chat <N>  |  --chat-id <UUID>  |  /open <N>  |  /open id:<UUID>[/dim]")
            return

        # ── Open specific chat by ID ──────────────────────────────────────
        if chat_id:
            await client.open_chat_by_id(chat_id)
            if export_path and not all_prompts and not single_prompt:
                await client.export_chat(export_path)
                return
            # Fall through to send prompts if -p was given

        # ── Open chat by index ─────────────────────────────────────────────
        if open_chat_idx is not None and not chat_id:
            await client.open_chat(open_chat_idx)
            if export_path and not all_prompts and not single_prompt:
                await client.export_chat(export_path)
                return

        # ── Continue last chat ────────────────────────────────────────────
        if continue_chat:
            console.print("[bold cyan]Resuming last chat...[/bold cyan]")
            # Wait for sidebar to load
            try:
                await client.page.wait_for_selector(
                    'a.chat-item-drag-link, a[aria-label="chat-item"]', timeout=10000
                )
            except PlaywrightTimeout:
                pass
            items = await client.page.query_selector_all(
                'a.chat-item-drag-link, a[aria-label="chat-item"]'
            )
            if items:
                title = await items[0].text_content()
                console.print(f"  [dim]Opening: {title.strip()}[/dim]")
                await items[0].click()
                try:
                    await client.page.wait_for_selector("textarea.message-input-textarea", timeout=6000)
                except PlaywrightTimeout:
                    pass
                console.print("  [green]Last chat resumed.[/green]")
            else:
                console.print("  [yellow]No history — starting fresh.[/yellow]")

        # ── New chat BEFORE mode/model (mode is wiped by a fresh chat) ──
        if new_chat and not continue_chat and not chat_id and open_chat_idx is None:
            await client.new_chat()
            await client._dismiss_popups()

        # ── Mode / Model / Think (skip when resuming an existing chat) ──
        if mode and not chat_id and open_chat_idx is None and not continue_chat:
            await client.set_mode(mode)
            await client.page.wait_for_timeout(250)
        if model and not chat_id and open_chat_idx is None and not continue_chat:
            await client.select_model(model)
            await client.page.wait_for_timeout(200)
        if think and not chat_id and open_chat_idx is None and not continue_chat:
            await client.set_think_mode(think)

        # ── File upload ───────────────────────────────────────────────────
        if upload_file:
            await client.upload_file(upload_file)

        # ── Multi-prompt / single-prompt (non-interactive) ────────────────
        prompts_to_send = []
        if single_prompt and not all_prompts:
            prompts_to_send = [single_prompt]
        elif all_prompts:
            prompts_to_send = all_prompts

        if prompts_to_send:
            total = len(prompts_to_send)
            for idx, p in enumerate(prompts_to_send, 1):
                if total > 1:
                    console.print(f"\n[bold blue]\u2501\u2501\u2501 Step {idx}/{total} \u2501\u2501\u2501[/bold blue]")
                    console.print(f"[dim]{p[:100]}{'...' if len(p)>100 else ''}[/dim]")

                try:
                    with console.status("[bold green]Waiting for response...[/bold green]"):
                        response = await client.send_message(p)
                except KeyboardInterrupt:
                    client._stop_requested = True
                    console.print("\n  [yellow]Stopping...[/yellow]")
                    await client.stop_generation()
                    sys.exit(130)
                except Exception as e:
                    console.print(f"[red]Error on step {idx}: {e}[/red]")
                    sys.exit(1)

                if raw:
                    console.print(response)
                else:
                    console.print(f"\n[bold green]Qwen:[/bold green]")
                    console.print(Markdown(response))
                    console.print()

                if download_dir:
                    await client.download_generated_images(download_dir)
                    await client.download_generated_videos(download_dir)

                if idx < total and wait_between > 0:
                    console.print(f"  [dim]Waiting {wait_between}s...[/dim]")
                    await client.page.wait_for_timeout(wait_between * 1000)

            # Machine-readable chat id for pollers (stderr keeps --raw stdout clean).
            try:
                cid = await client.wait_for_chat_id()
                if cid:
                    print(f"CHAT_ID:{cid}", file=sys.stderr, flush=True)
            except Exception:
                pass

            if export_path:
                await client.export_chat(export_path)
            return

        # ── Interactive loop ──────────────────────────────────────────────
        console.print("\n[dim]Commands: /new /mode /model /think /history /open /continue /export /download /stop /clear /quit /help[/dim]\n")

        while True:
            try:
                user_input = Prompt.ask("[bold cyan]You[/bold cyan]")
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Goodbye![/dim]")
                break

            if not user_input.strip():
                continue

            if user_input.startswith("/"):
                parts = user_input.strip().split(None, 1)
                cmd = parts[0].lower()
                arg = parts[1] if len(parts) > 1 else None

                if cmd in ("/quit", "/exit", "/q"):
                    console.print("[dim]Goodbye![/dim]")
                    break
                elif cmd == "/new":
                    await client.new_chat()
                elif cmd == "/mode":
                    if arg:
                        await client.set_mode(arg)
                    else:
                        console.print(f"  [dim]Usage: /mode <{'|'.join(k for k in MODE_MAP if k != 'chat')}>[/dim]")
                elif cmd == "/model":
                    await client.select_model(arg)
                elif cmd == "/think":
                    m = arg if arg in THINK_MAP else "auto"
                    await client.set_think_mode(m)
                elif cmd == "/history":
                    hist = await client.get_chat_history(20)
                    if not hist:
                        console.print("  [yellow]No history.[/yellow]")
                    else:
                        current_id = await client.get_current_chat_id()
                        table = Table(box=box.SIMPLE)
                        table.add_column("#", style="dim", width=4)
                        table.add_column("Title", style="white", max_width=42)
                        table.add_column("Chat ID", style="cyan", max_width=18)
                        table.add_column("Cur", style="green", width=4)
                        for i, item in enumerate(hist, 1):
                            cur = "[green]<[/green]" if item.get("id") == current_id else ""
                            cid = item.get("id", "")[:14] + ("..." if len(item.get("id", "")) > 14 else "")
                            table.add_row(str(i), item["title"][:42], cid, cur)
                        console.print(table)
                        console.print("  [dim]/open <N>  |  /open id:<UUID>  |  /continue[/dim]")
                elif cmd == "/open":
                    if not arg:
                        hist = await client.get_chat_history(20)
                        if not hist:
                            console.print("  [yellow]No history.[/yellow]")
                        else:
                            current_id = await client.get_current_chat_id()
                            table = Table(box=box.SIMPLE)
                            table.add_column("#", style="dim", width=4)
                            table.add_column("Title", max_width=42)
                            table.add_column("Chat ID", style="cyan", max_width=18)
                            table.add_column("Cur", style="green", width=4)
                            for i, item in enumerate(hist, 1):
                                cur = "[green]<[/green]" if item.get("id") == current_id else ""
                                cid = item.get("id", "")[:14] + ("..." if len(item.get("id", "")) > 14 else "")
                                table.add_row(str(i), item["title"][:42], cid, cur)
                            console.print(table)
                            console.print("  [dim]/open <N>  |  /open id:<UUID>[/dim]")
                    elif arg.startswith("id:"):
                        # Open by chat ID
                        cid = arg[3:].strip()
                        await client.open_chat_by_id(cid)
                    elif arg.isdigit():
                        await client.open_chat(int(arg))
                    else:
                        console.print("  [dim]Usage: /open <number> or /open id:<chat_id>[/dim]")
                elif cmd == "/continue":
                    items = await client.page.query_selector_all(
                        'a.chat-item-drag-link, a[aria-label="chat-item"]'
                    )
                    if items:
                        title = await items[0].text_content()
                        console.print(f"  [dim]Resuming: {title.strip()}[/dim]")
                        await items[0].click()
                        try:
                            await client.page.wait_for_selector("textarea.message-input-textarea", timeout=6000)
                        except PlaywrightTimeout:
                            pass
                        console.print("  [green]Resumed.[/green]")
                    else:
                        console.print("  [yellow]No history.[/yellow]")
                elif cmd == "/export":
                    path = arg or f"qwen_chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
                    await client.export_chat(path)
                elif cmd == "/download":
                    await client.download_generated_images(arg or ".")
                elif cmd == "/stop":
                    client._stop_requested = True
                    console.print("  [yellow]Stopping...[/yellow]")
                elif cmd == "/clear":
                    console.clear()
                elif cmd == "/help":
                    console.print(Panel(
                        "[bold]/new[/bold]              - New chat\n"
                        "[bold]/continue[/bold]         - Resume last chat\n"
                        "[bold]/mode <name>[/bold]      - Set mode (web, image, video, ...)\n"
                        "[bold]/model [name][/bold]     - Change or list models\n"
                        "[bold]/think <mode>[/bold]     - Think mode: auto, think, fast\n"
                        "[bold]/history[/bold]          - Show chat history with IDs\n"
                        "[bold]/open <N>[/bold]          - Open chat #N\n"
                        "[bold]/open id:<ID>[/bold]    - Open chat by ID\n"
                        "[bold]/export [path][/bold]    - Export to markdown\n"
                        "[bold]/download [dir][/bold]   - Download generated images\n"
                        "[bold]/stop[/bold]            - Stop generation\n"
                        "[bold]/clear[/bold]            - Clear terminal\n"
                        "[bold]/quit[/bold]            - Exit",
                        title="Commands", border_style="blue",
                    ))
                else:
                    console.print(f"[yellow]Unknown: {cmd}. Type /help[/yellow]")
                continue

            # Send message
            try:
                with console.status("[bold green]Waiting for response...[/bold green]"):
                    response = await client.send_message(user_input)
                if raw:
                    console.print(response)
                else:
                    console.print(f"\n[bold green]Qwen:[/bold green]")
                    console.print(Markdown(response))
                    console.print()
                if download_dir:
                    await client.download_generated_images(download_dir)
                    await client.download_generated_videos(download_dir)
            except KeyboardInterrupt:
                client._stop_requested = True
                console.print("\n  [yellow]Stopping...[/yellow]")
                await client.stop_generation()
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
                console.print("[dim]Try /new or /quit[/dim]")



if __name__ == "__main__":
    cli()
