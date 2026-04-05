"""Agent orchestrator — session state holder and tick loop.

Owns the Session, the event log, and the background thread that polls the
Playwright browser every `tick_seconds`. For every open tab, it runs the
Policy; on ambiguity it consults the AI. Tools execute the resulting Decision.
"""

from __future__ import annotations

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
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def _find_browser_executable() -> str | None:
    for p in _CHROME_PATHS:
        if p and os.path.exists(p):
            return p
    # PATH lookup as fallback.
    for name in ("chrome", "chrome.exe", "msedge", "msedge.exe"):
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


def _spawn_chrome_with_debug(cdp_url: str, ui) -> subprocess.Popen | None:
    """Launch Chrome/Edge with --remote-debugging-port. Returns the process or None."""
    exe = _find_browser_executable()
    if not exe:
        ui.error("could not find chrome.exe or msedge.exe — install Chrome or start it manually")
        return None
    parsed = urlparse(cdp_url)
    port = parsed.port or 9222
    profile_dir = os.path.join(os.environ.get("TEMP", os.getcwd()), "chrome-focus")
    args = [
        exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
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
        self.session: Session | None = None
        self.events: list[Event] = []
        self._thread: threading.Thread | None = None
        self._stop_flag = threading.Event()
        self._browser_launched = False
        self._chrome_process: subprocess.Popen | None = None
        self._tick_count = 0

    # --- session lifecycle ---

    def start_session(self, goal: str, duration_minutes: int, mode: SessionMode) -> Session:
        if self.session is not None and self.session.is_active():
            raise RuntimeError("a session is already active - /stop it first")
        self.session = Session(goal=goal, duration_minutes=duration_minutes, mode=mode)
        self.session.start()
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

    def set_mode(self, mode: SessionMode) -> None:
        self._require_session()
        assert self.session is not None
        self.session.mode = mode
        self._log(EventType.MODE_CHANGED, reason=f"mode set to {mode.value}")

    # --- block/allow passthrough ---

    def add_block(self, domain: str) -> str:
        d = self.policy.add_block(domain)
        self._log(EventType.MODE_CHANGED, reason=f"blocked {d}")
        return d

    def add_allow(self, domain: str) -> str:
        d = self.policy.add_allow(domain)
        self._log(EventType.MODE_CHANGED, reason=f"allowed {d}")
        return d

    def add_process_block(self, name: str) -> str:
        if self.process_monitor is None:
            raise RuntimeError("process monitor not available (install psutil)")
        n = self.process_monitor.add_block(name)
        self._log(EventType.MODE_CHANGED, reason=f"p-blocked {n}")
        return n

    def add_process_allow(self, name: str) -> str:
        if self.process_monitor is None:
            raise RuntimeError("process monitor not available (install psutil)")
        n = self.process_monitor.add_allow(name)
        self._log(EventType.MODE_CHANGED, reason=f"p-allowed {n}")
        return n

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
                    spawned = _spawn_chrome_with_debug(self.cdp_url, self.ui)
                    if spawned:
                        self._chrome_process = spawned
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
                self.ui.error(
                    'start Chrome with: chrome.exe --remote-debugging-port=9222 '
                    '--user-data-dir="%TEMP%\\chrome-focus"'
                )
            elif "Executable doesn" in msg or "playwright install" in msg.lower():
                self.ui.error("run: playwright install chromium")
            return

        while not self._stop_flag.is_set():
            try:
                self._tick()
            except Exception as e:
                self.ui.error(f"tick error: {e}")
            self._stop_flag.wait(self.tick_seconds)

    def _tick(self) -> None:
        session = self.session
        if session is None or session.status != SessionStatus.ACTIVE:
            return
        # Process scan first — fast, local, no network.
        if self.process_monitor is not None and self.process_monitor.available:
            for proc in self.process_monitor.scan_blocked():
                self.tools.apply_process(proc, session)
        if self.detector is None:
            return
        tabs = self.detector.list_tabs()
        for ctx in tabs:
            if ctx.domain:
                self._log(EventType.TAB_OBSERVED, url=ctx.url, domain=ctx.domain)
            decision = self.policy.decide(ctx, session)
            # Ambiguous → ask AI (rules-first: AI only when rules don't match).
            ai_available = self.ai is not None and self.ai.enabled and self.ai._error_count < 3
            if decision.needs_ai and ai_available:
                ai_decision = self.ai.classify_tab(ctx, session.goal, [])
                # Honor current mode — downgrade BLOCK to WARN in soft mode.
                if ai_decision.action == Action.BLOCK and session.mode == SessionMode.SOFT:
                    ai_decision.action = Action.WARN
                decision = ai_decision
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

    # --- internals ---

    def _require_session(self) -> None:
        if self.session is None:
            raise RuntimeError("no session - start one with /start")

    def _log(self, event_type: EventType, **fields) -> None:
        session_id = self.session.id if self.session is not None else 0
        self.events.append(Event(session_id=session_id, type=event_type, **fields))
