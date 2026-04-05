"""Agent tool layer.

Every action the agent can take on the world. Kept separate so we can
(a) log every invocation uniformly, (b) swap the browser backend later.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from app.models import Event, EventType
from app.policy import Action


_ROOT = Path(__file__).resolve().parent.parent


def _spawn_popup(message: str) -> None:
    """Open a new terminal window showing a Rich distraction warning."""
    python = _ROOT / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = Path(sys.executable)
    try:
        if sys.platform == "win32":
            subprocess.Popen(
                [str(python), "-m", "app.popup", message],
                cwd=str(_ROOT),
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        else:
            for term in ("gnome-terminal", "xterm", "konsole"):
                try:
                    subprocess.Popen(
                        [term, "--", str(python), "-m", "app.popup", message],
                        cwd=str(_ROOT),
                    )
                    break
                except FileNotFoundError:
                    continue
    except Exception:
        pass


class Tools:
    """The agent's action surface."""

    def __init__(self, ui, event_log: list, detector=None, process_monitor=None) -> None:
        self.ui = ui
        self.events = event_log
        self.detector = detector
        self.process_monitor = process_monitor

    # --- primary actions ---

    def warn_user(self, message: str, session_id: int, url: str = "", domain: str = "") -> None:
        """Push-notify the user in the terminal (soft-mode warning)."""
        self.ui.warn(f"[focus] {message}")
        _spawn_popup(message)
        self._log(EventType.WARNING_ISSUED, session_id, url=url, domain=domain, reason=message)

    def close_tab(self, context, session_id: int, reason: str) -> bool:
        """Close a specific tab. Returns success."""
        # Attach mode: close via CDP HTTP.
        target_id = getattr(context, "target_id", None)
        if target_id and self.detector is not None:
            ok = self.detector.close_tab_cdp(target_id)
            if not ok:
                return False
            self.ui.warn(f"[focus] closed {context.domain} — {reason}")
            self._log(
                EventType.TAB_CLOSED, session_id,
                url=context.url, domain=context.domain,
                action=Action.BLOCK.value, reason=reason,
            )
            return True
        # Launch mode: use the Playwright Page.
        page = getattr(context, "page", None)
        if page is None or isinstance(page, str):
            return False
        try:
            browser_ctx = page.context
            if len(browser_ctx.pages) <= 1:
                try:
                    browser_ctx.new_page()
                except Exception:
                    pass
            page.close()
        except Exception:
            return False
        self.ui.warn(f"[focus] closed {context.domain} — {reason}")
        self._log(
            EventType.TAB_CLOSED,
            session_id,
            url=context.url,
            domain=context.domain,
            action=Action.BLOCK.value,
            reason=reason,
        )
        return True

    def kill_process(self, proc_info, session_id: int, reason: str) -> bool:
        """Terminate a blocked process. Returns success."""
        if self.process_monitor is None:
            return False
        ok = self.process_monitor.kill(proc_info.pid)
        if not ok:
            return False
        self.ui.warn(f"[focus] killed {proc_info.name} (pid {proc_info.pid}) — {reason}")
        self._log(
            EventType.PROCESS_KILLED, session_id,
            domain=proc_info.name,
            action=Action.BLOCK.value, reason=reason,
        )
        return True

    def warn_process(self, proc_info, session_id: int, reason: str) -> None:
        """Soft-mode notification about a running blocked process."""
        message = f"{proc_info.name} is running — {reason}"
        self.ui.warn(f"[focus] {message}")
        _spawn_popup(message)
        self._log(
            EventType.WARNING_ISSUED, session_id,
            domain=proc_info.name, reason=reason,
        )

    def apply_process(self, proc_info, session, reason: str | None = None) -> None:
        """Run the blocked-process action for the current mode, with dedup."""
        from datetime import datetime
        from app.session import SessionMode
        key_id = f"pid:{proc_info.pid}"
        is_new = session.should_count_offense(key_id, proc_info.name)
        if reason is None:
            reason = f"{proc_info.name} is blocked ({session.mode.value})"
        if session.mode == SessionMode.HARDCORE:
            if is_new:
                session.record_offense()
            self.kill_process(proc_info, session.id, reason)
            return
        if session.mode == SessionMode.NORMAL:
            first = session.grace_first_seen.get(proc_info.name)
            now = datetime.now()
            if first is None:
                session.grace_first_seen[proc_info.name] = now
                if is_new:
                    session.record_offense()
                grace_min = max(session.grace_seconds // 60, 0)
                grace_sec = session.grace_seconds % 60
                window = f"{grace_min}m{grace_sec}s" if grace_sec else f"{grace_min}m"
                self.warn_process(
                    proc_info, session.id,
                    f"{reason} — closing in {window} unless you quit it",
                )
                return
            if (now - first).total_seconds() >= session.grace_seconds:
                self.kill_process(proc_info, session.id, f"{reason} — grace expired")
                session.grace_first_seen.pop(proc_info.name, None)
            return
        # chill mode: monitor cumulative time, warn once
        now = datetime.now()
        last = session.chill_last_seen.get(proc_info.name)
        if last is not None:
            delta = now - last
            if delta.total_seconds() < 15:
                session.chill_time[proc_info.name] = (
                    session.chill_time.get(proc_info.name, timedelta(0)) + delta
                )
        session.chill_last_seen[proc_info.name] = now
        if is_new:
            session.record_offense()
            self.warn_process(proc_info, session.id, f"{reason} — chill mode, just watching")

    # --- dispatcher ---

    def apply(self, decision, context, session) -> None:
        """Execute whatever the Decision calls for."""
        from datetime import datetime
        from app.session import SessionMode
        if decision.action == Action.ALLOW:
            return
        tab_id = getattr(context, "target_id", None) or getattr(context, "url", "") or ""
        is_new = session.should_count_offense(tab_id, context.domain)
        if decision.action == Action.WARN:
            # chill mode: monitor cumulative time on blocked domains
            if context.domain:
                now = datetime.now()
                last = session.chill_last_seen.get(context.domain)
                if last is not None:
                    delta = now - last
                    if delta.total_seconds() < 15:
                        session.chill_time[context.domain] = (
                            session.chill_time.get(context.domain, timedelta(0)) + delta
                        )
                session.chill_last_seen[context.domain] = now
            if is_new:
                session.record_offense()
                self.warn_user(decision.reason, session.id, context.url, context.domain)
            return
        if decision.action == Action.BLOCK:
            if session.mode == SessionMode.NORMAL and context.domain:
                first = session.grace_first_seen.get(context.domain)
                now = datetime.now()
                if first is None:
                    session.grace_first_seen[context.domain] = now
                    if is_new:
                        session.record_offense()
                    grace_min = max(session.grace_seconds // 60, 0)
                    grace_sec = session.grace_seconds % 60
                    window = f"{grace_min}m{grace_sec}s" if grace_sec else f"{grace_min}m"
                    self.warn_user(
                        f"{decision.reason} — closing in {window} unless you leave",
                        session.id, context.url, context.domain,
                    )
                    return
                if (now - first).total_seconds() >= session.grace_seconds:
                    self.close_tab(context, session.id, f"{decision.reason} — grace expired")
                    session.grace_first_seen.pop(context.domain, None)
                return
            if is_new:
                session.record_offense()
            self.close_tab(context, session.id, decision.reason)
            return

    # --- internals ---

    def _log(self, event_type: EventType, session_id: int, **fields) -> None:
        self.events.append(Event(session_id=session_id, type=event_type, **fields))
