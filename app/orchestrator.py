"""Agent orchestrator — session state holder and tick loop.

Owns the Session, the event log, and the background thread that polls the
Playwright browser every `tick_seconds`. For every open tab, it runs the
Policy; on ambiguity it consults the AI. Tools execute the resulting Decision.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import time
from urllib.parse import urlparse

from app.models import Event, EventType
from app.policy import Action, Policy
from app.session import Session, SessionMode, SessionStatus


_CHROME_PATHS = [
    # macOS
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    # Windows
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    # Linux
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
]


def _find_browser_executable() -> str | None:
    for p in _CHROME_PATHS:
        if p and os.path.exists(p):
            return p
    # PATH lookup as fallback.
    for name in ("google-chrome", "chromium-browser", "chromium", "chrome", "chrome.exe", "msedge", "msedge.exe"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _port_open(cdp_url: str, timeout: float = 0.5) -> bool:
    parsed = urlparse(cdp_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 9222
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _spawn_chrome_with_debug(cdp_url: str, ui, restore_urls: list[str] | None = None) -> subprocess.Popen | None:
    """Launch Chrome/Edge with --remote-debugging-port. Returns the process or None.

    If `restore_urls` is provided, each URL is appended as a positional arg so
    Chrome opens them as tabs on startup (reliable path — avoids /json/new,
    which newer Chrome rejects for DNS-rebinding protection)."""
    exe = _find_browser_executable()
    if not exe:
        ui.error("could not find Chrome — install Chrome or start it manually")
        return None
    parsed = urlparse(cdp_url)
    port = parsed.port or 9222
    tmp = os.environ.get("TEMP") or os.environ.get("TMPDIR") or os.getcwd()
    profile_dir = os.path.join(tmp, "chrome-focus")
    args = [
        exe,
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if restore_urls:
        args.extend(restore_urls)
    try:
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        ui.error(f"failed to launch browser: {e}")
        return None
    # Poll the port until Chrome is ready (up to 10s).
    for _ in range(40):
        if _port_open(cdp_url, timeout=0.25):
            return proc
        time.sleep(0.25)
    ui.error("Chrome started but debug port never came up")
    return proc


class Orchestrator:
    """Coordinates session lifecycle, the tick loop, and enforcement."""

    def __init__(
        self,
        ui,
        policy: Policy,
        tick_seconds: float = 2.0,
        detector=None,
        tools=None,
        ai=None,
        browser_start_url: str = "about:blank",
        browser_headless: bool = False,
        browser_mode: str = "launch",
        cdp_url: str = "http://localhost:9222",
        process_monitor=None,
        grace_seconds: int = 120,
        default_mode: SessionMode = SessionMode.NORMAL,
        configs_dir=None,
    ) -> None:
        self.ui = ui
        self.policy = policy
        self.detector = detector
        self.tools = tools
        self.ai = ai
        self.tick_seconds = tick_seconds
        self.browser_start_url = browser_start_url
        self.browser_headless = browser_headless
        self.browser_mode = browser_mode
        self.cdp_url = cdp_url
        self.process_monitor = process_monitor
        self.grace_seconds = grace_seconds
        self.default_mode = default_mode
        self.configs_dir = configs_dir
        self.session: Session | None = None
        self.events: list[Event] = []
        self._thread: threading.Thread | None = None
        self._stop_flag = threading.Event()
        self._browser_launched = False
        self._chrome_process: subprocess.Popen | None = None
        self._tick_count = 0
        self._ai_circuit_notified = False
        self._tabs_restored = False
        self._last_tabs_save_tick = -1

    # --- session lifecycle ---

    def start_session(self, goal: str, duration_minutes: int, mode: SessionMode) -> Session:
        if self.session is not None and self.session.is_active():
            raise RuntimeError("a session is already active - /stop it first")
        self.session = Session(
            goal=goal, duration_minutes=duration_minutes, mode=mode,
            grace_seconds=self.grace_seconds,
        )
        self.session.start()
        self._ai_circuit_notified = False
        if self.ai is not None:
            self.ai.reset_cache()
            self.ui.info(self.ai.status_line())
        else:
            self.ui.warn("AI judge not configured — rules-only enforcement")
        self._log(EventType.SESSION_STARTED, reason=f'"{goal}" for {duration_minutes}m ({mode.value})')
        self._start_tick_loop()
        return self.session

    def stop_session(self) -> Session:
        self._require_session()
        assert self.session is not None
        self._stop_tick_loop()
        self.session.stop()
        self._log(EventType.SESSION_STOPPED)
        return self.session

    def pause_session(self) -> None:
        self._require_session()
        assert self.session is not None
        self.session.pause()
        self._log(EventType.SESSION_PAUSED)

    def resume_session(self) -> None:
        self._require_session()
        assert self.session is not None
        self.session.resume()
        self._log(EventType.SESSION_RESUMED)

    def adjust_time(self, minutes: int, label: str) -> None:
        self._require_session()
        assert self.session is not None
        self.session.adjust_time(minutes)
        self._log(EventType.TIME_ADJUSTED, reason=label)

    def set_grace(self, seconds: int) -> None:
        self.grace_seconds = seconds
        if self.session is not None:
            self.session.grace_seconds = seconds
        self._log(EventType.MODE_CHANGED, reason=f"grace set to {seconds}s")
        self._save_settings()

    def set_mode(self, mode: SessionMode) -> None:
        self._require_session()
        assert self.session is not None
        self.session.mode = mode
        # Also update default so the choice persists to next run.
        self.default_mode = mode
        self._log(EventType.MODE_CHANGED, reason=f"mode set to {mode.value}")
        self._save_settings()

    def set_default_mode(self, mode: SessionMode) -> None:
        self.default_mode = mode
        self._save_settings()

    # --- block/allow passthrough ---

    def add_block(self, domain: str) -> str:
        d = self.policy.add_block(domain)
        self._log(EventType.MODE_CHANGED, reason=f"blocked {d}")
        self._save_sites()
        return d

    def add_allow(self, domain: str) -> str:
        d = self.policy.add_allow(domain)
        self._log(EventType.MODE_CHANGED, reason=f"allowed {d}")
        self._save_sites()
        return d

    def add_process_block(self, name: str) -> str:
        if self.process_monitor is None:
            raise RuntimeError("process monitor not available (install psutil)")
        n = self.process_monitor.add_block(name)
        self._log(EventType.MODE_CHANGED, reason=f"p-blocked {n}")
        self._save_processes()
        return n

    def add_process_allow(self, name: str) -> str:
        if self.process_monitor is None:
            raise RuntimeError("process monitor not available (install psutil)")
        n = self.process_monitor.add_allow(name)
        self._log(EventType.MODE_CHANGED, reason=f"p-allowed {n}")
        self._save_processes()
        return n

    # --- persistence ---

    def _save_settings(self) -> None:
        if self.configs_dir is None:
            return
        path = self.configs_dir / "settings.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except Exception:
            data = {}
        data["default_mode"] = self.default_mode.value
        data["normal_mode_grace_minutes"] = round(self.grace_seconds / 60, 2)
        self._atomic_write(path, json.dumps(data, indent=2) + "\n")

    def _save_sites(self) -> None:
        if self.configs_dir is None:
            return
        data = {
            "blocklist": self.policy.list_blocked(),
            "allowlist": self.policy.list_allowed(),
        }
        self._atomic_write(
            self.configs_dir / "blocked_sites.json",
            json.dumps(data, indent=2) + "\n",
        )

    def _save_processes(self) -> None:
        if self.configs_dir is None or self.process_monitor is None:
            return
        data = {
            "blocklist": self.process_monitor.list_blocked(),
            "allowlist": self.process_monitor.list_allowed(),
        }
        self._atomic_write(
            self.configs_dir / "blocked_processes.json",
            json.dumps(data, indent=2) + "\n",
        )

    def _tabs_file(self):
        if self.configs_dir is None:
            return None
        return self.configs_dir / "last_tabs.json"

    def _save_open_tabs(self) -> None:
        """Persist the currently open tab URLs to configs/last_tabs.json."""
        path = self._tabs_file()
        if path is None or self.detector is None:
            return
        try:
            tabs = self.detector.list_tabs()
        except Exception:
            return
        urls: list[str] = []
        seen: set[str] = set()
        for ctx in tabs:
            u = (ctx.url or "").strip()
            if not u or u in seen:
                continue
            if u.startswith(("about:", "chrome://", "edge://", "devtools://", "chrome-extension://")):
                continue
            seen.add(u)
            urls.append(u)
        self._atomic_write(path, json.dumps({"tabs": urls}, indent=2) + "\n")

    def _load_saved_tab_urls(self) -> list[str]:
        """Read URLs from configs/last_tabs.json, de-duped and filtered."""
        path = self._tabs_file()
        if path is None or not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        urls = data.get("tabs") or []
        out: list[str] = []
        seen: set[str] = set()
        for u in urls:
            u = (u or "").strip()
            if not u or u in seen:
                continue
            if u.startswith(("about:", "chrome://", "edge://", "devtools://", "chrome-extension://")):
                continue
            seen.add(u)
            out.append(u)
        return out

    def _restore_open_tabs(self) -> None:
        """Reopen tabs saved from the previous run. Skips URLs already open."""
        path = self._tabs_file()
        if path is None or self.detector is None or not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        urls = data.get("tabs") or []
        if not urls:
            return
        try:
            already = {(ctx.url or "").strip() for ctx in self.detector.list_tabs()}
        except Exception:
            already = set()
        opened = 0
        for url in urls:
            if not url or url in already:
                continue
            if self.detector.open_tab(url):
                opened += 1
        if opened:
            self.ui.info(f"restored {opened} tab(s) from last session")

    @staticmethod
    def _atomic_write(path, content: str) -> None:
        try:
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(content, encoding="utf-8")
            os.replace(tmp, path)
        except Exception:
            pass

    # --- state queries ---

    def recent_events(self, limit: int = 20) -> list[Event]:
        return self.events[-limit:]

    # --- tick loop ---

    def _start_tick_loop(self) -> None:
        if self.tools is None:
            return
        if self.detector is None and self.process_monitor is None:
            return
        self._stop_flag.clear()
        self._tick_count = 0
        self._thread = threading.Thread(target=self._tick_loop, name="focus-tick", daemon=True)
        self._thread.start()

    def _stop_tick_loop(self) -> None:
        self._stop_flag.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        if self._browser_launched and self.detector is not None:
            try:
                self.detector.close()
            except Exception:
                pass
            self._browser_launched = False

    def _tick_loop(self) -> None:
        """Runs in background thread. Owns all Playwright interactions."""
        try:
            if self.browser_mode == "attach":
                if not _port_open(self.cdp_url):
                    self.ui.info("no Chrome debug port detected — starting Chrome with debug flag")
                    saved_urls = self._load_saved_tab_urls()
                    spawned = _spawn_chrome_with_debug(self.cdp_url, self.ui, restore_urls=saved_urls)
                    if spawned:
                        self._chrome_process = spawned
                    if saved_urls:
                        self.ui.info(f"restoring {len(saved_urls)} tab(s) from last session")
                    # Chrome opens the URLs on spawn, so mark restore as done.
                    self._tabs_restored = True
                self.detector.attach(self.cdp_url)
                self._browser_launched = True
                self.ui.info(f"attached to Chrome at {self.cdp_url} — monitoring all your tabs")
            else:
                self.detector.launch(start_url=self.browser_start_url, headless=self.browser_headless)
                self._browser_launched = True
                self.ui.info("browser ready — navigate inside THIS Chromium window to be monitored")
        except Exception as e:
            msg = str(e)
            self.ui.error(f"browser setup failed: {msg}")
            if self.browser_mode == "attach":
                import sys
                if sys.platform == "darwin":
                    self.ui.error(
                        'start Chrome with: '
                        '"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" '
                        '--remote-debugging-port=9222 --user-data-dir=/tmp/chrome-focus'
                    )
                elif sys.platform == "win32":
                    self.ui.error(
                        'start Chrome with: chrome.exe --remote-debugging-port=9222 '
                        '--user-data-dir="%TEMP%\\chrome-focus"'
                    )
                else:
                    self.ui.error(
                        'start Chrome with: google-chrome --remote-debugging-port=9222 '
                        '--user-data-dir=/tmp/chrome-focus'
                    )
            elif "Executable doesn" in msg or "playwright install" in msg.lower():
                self.ui.error("run: playwright install chromium")
            return

        # Restore tabs from the previous session, once per tick-loop start.
        if not self._tabs_restored:
            try:
                self._restore_open_tabs()
            except Exception as e:
                self.ui.warn(f"tab restore failed: {e}")
            self._tabs_restored = True

        while not self._stop_flag.is_set():
            try:
                self._tick()
            except Exception as e:
                self.ui.error(f"tick error: {e}")
            # Throttled snapshot of open tabs — roughly every ~10s.
            self._tick_count += 1
            save_every = max(1, int(10 / max(self.tick_seconds, 0.5)))
            if self._tick_count - self._last_tabs_save_tick >= save_every:
                try:
                    self._save_open_tabs()
                    self._last_tabs_save_tick = self._tick_count
                except Exception:
                    pass
            self._stop_flag.wait(self.tick_seconds)

        # Final save on loop exit so the freshest state is persisted.
        try:
            self._save_open_tabs()
        except Exception:
            pass

    def _tick(self) -> None:
        session = self.session
        if session is None or session.status != SessionStatus.ACTIVE:
            return
        ai_available = (
            self.ai is not None and self.ai.enabled and self.ai._error_count < 3
        )
        if (
            self.ai is not None
            and self.ai.enabled
            and self.ai._error_count >= 3
            and not self._ai_circuit_notified
        ):
            self.ui.error(
                f"AI circuit-broken after 3 errors — last: {self.ai._last_error}"
            )
            self._ai_circuit_notified = True
        # Rules-based process enforcement first (no AI, no network).
        if self.process_monitor is not None and self.process_monitor.available:
            for proc in self.process_monitor.scan_blocked():
                self.tools.apply_process(proc, session)
        # Tabs get AI priority — they're the primary focus of the agent.
        if self.detector is not None:
            tabs = self.detector.list_tabs()
        else:
            tabs = []
        for ctx in tabs:
            if ctx.domain:
                self._log(EventType.TAB_OBSERVED, url=ctx.url, domain=ctx.domain)
            decision = self.policy.decide(ctx, session)
            # Re-check ai_available each iteration — circuit can trip mid-tick.
            ai_up = (
                self.ai is not None and self.ai.enabled and self.ai._error_count < 3
            )
            # Ambiguous → ask AI (rules-first: AI only when rules don't match).
            if decision.needs_ai and ai_up:
                was_cached = f"tab::{ctx.url}" in self.ai._cache
                ai_decision = self.ai.classify_tab(ctx, session.goal, [])
                # Honor current mode — downgrade BLOCK to WARN in chill mode.
                if ai_decision.action == Action.BLOCK and session.mode == SessionMode.CHILL:
                    ai_decision.action = Action.WARN
                decision = ai_decision
                if not was_cached:
                    self.ui.info(
                        f"AI {decision.action.value.upper()} "
                        f"{ctx.domain or '(blank)'} — {decision.reason}"
                    )
                self._log(
                    EventType.AI_CLASSIFIED,
                    url=ctx.url,
                    domain=ctx.domain,
                    action=decision.action.value,
                    reason=decision.reason,
                )
            if decision.action == Action.ALLOW:
                continue
            self.tools.apply(decision, ctx, session)

        # Agentic process judgment — runs LAST, throttled, so it never
        # starves the tab classifier of quota.
        if (
            self.process_monitor is not None
            and self.process_monitor.available
            and self.ai is not None
            and self.ai.enabled
            and self.ai._error_count < 3
        ):
            self._ai_judge_processes(session, budget=2)

    def _ai_judge_processes(self, session, budget: int) -> None:
        """Ask AI about up to `budget` never-seen process names per tick."""
        from app.session import SessionMode
        candidates = self.process_monitor.scan_candidates()
        by_name: dict[str, list] = {}
        for proc in candidates:
            by_name.setdefault(proc.name, []).append(proc)
        spent = 0
        for name, procs in by_name.items():
            cached = f"proc::{name}" in self.ai._cache
            if not cached:
                if spent >= budget:
                    continue
                spent += 1
            ai_decision = self.ai.classify_process(name, session.goal)
            if ai_decision.action != Action.BLOCK:
                continue
            self._log(
                EventType.AI_CLASSIFIED,
                domain=name,
                action=ai_decision.action.value,
                reason=ai_decision.reason,
            )
            if session.mode == SessionMode.CHILL:
                self.tools.apply_process(procs[0], session, reason=ai_decision.reason)
                continue
            for match in procs:
                self.tools.apply_process(match, session, reason=ai_decision.reason)

    # --- internals ---

    def _require_session(self) -> None:
        if self.session is None:
            raise RuntimeError("no session - start one with /start")

    def _log(self, event_type: EventType, **fields) -> None:
        session_id = self.session.id if self.session is not None else 0
        self.events.append(Event(session_id=session_id, type=event_type, **fields))
