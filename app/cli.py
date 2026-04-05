"""Command-line interface.

Parses slash-style commands from the user and dispatches them to the
orchestrator. Keeps UI rendering separate (see ui.py).

Commands:
    /start "<goal>" <min> [mode]   Begin a focus session
    /stop                          End current session
    /status                        Show current session state
    /pause                         Pause session timer + enforcement
    /resume                        Resume after pause
    /mode strict|soft              Switch enforcement mode
    /help                          List commands
    /clear                         Clear screen and redraw
    /quit                          Exit app
"""

from __future__ import annotations

import shlex
import threading
import time as _time
from dataclasses import dataclass

from prompt_toolkit import PromptSession
from prompt_toolkit.application import get_app
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import print_formatted_text

from app.session import SessionMode

_COMMANDS = ["start", "stop", "status", "pause", "resume", "mode", "time", "block", "allow", "blocks", "help", "clear", "quit", "exit"]
_MODE_ARGS = ["strict", "soft"]
_ALERT_THRESHOLDS = [60, 30, 10, 5, 1]  # minutes


class _SlashCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lstrip()
        if text.startswith("/mode "):
            typed = text[len("/mode "):]
            for m in _MODE_ARGS:
                if m.startswith(typed):
                    yield Completion("/mode " + m, start_position=-len(text))
        elif text.startswith("/"):
            typed = text[1:]
            for cmd in _COMMANDS:
                if cmd.startswith(typed):
                    yield Completion("/" + cmd, start_position=-len(text))


@dataclass
class Command:
    """Parsed command: name + raw args string."""
    name: str
    args: str


class CLI:
    """Reads input, parses commands, dispatches to orchestrator."""

    PROMPT = "\n> "

    def __init__(self, orchestrator, ui) -> None:
        self.orchestrator = orchestrator
        self.ui = ui
        self._running = False
        self._fired_alerts: set[int] = set()
        import sys
        self._session = PromptSession(completer=_SlashCompleter(), complete_while_typing=True) if sys.stdin.isatty() else None
        self._start_ticker()
        self._handlers = {
            "start": self._handle_start,
            "stop": self._handle_stop,
            "status": self._handle_status,
            "pause": self._handle_pause,
            "resume": self._handle_resume,
            "mode": self._handle_mode,
            "time": self._handle_time,
            "block": self._handle_block,
            "allow": self._handle_allow,
            "blocks": self._handle_blocks,
            "help": self._handle_help,
            "clear": self._handle_clear,
            "quit": self._handle_quit,
            "exit": self._handle_quit,
        }

    def run(self) -> None:
        """Main REPL loop: read line → parse → dispatch → render."""
        self.ui.render_welcome()
        self._running = True
        while self._running:
            try:
                line = self._session.prompt(self.PROMPT, bottom_toolbar=self._toolbar).strip() if self._session else input(self.PROMPT).strip()
            except (EOFError, KeyboardInterrupt):
                self.ui.info("bye")
                break
            if not line:
                continue
            cmd = self._parse_command(line)
            if cmd is None:
                self.ui.error("commands start with /, try /help")
                continue
            handler = self._handlers.get(cmd.name)
            if handler is None:
                self.ui.error(f"unknown command: /{cmd.name} (try /help)")
                continue
            try:
                handler(cmd.args)
            except Exception as e:
                self.ui.error(str(e))

    def _parse_command(self, line: str) -> Command | None:
        """Split '/cmd rest of line' → Command(name, args)."""
        if not line.startswith("/"):
            return None
        body = line[1:].strip()
        if not body:
            return None
        parts = body.split(None, 1)
        name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        return Command(name=name, args=args)

    # --- command handlers ---

    def _handle_start(self, args: str) -> None:
        parts = shlex.split(args) if args else []
        if len(parts) < 2:
            raise ValueError('usage: /start "<goal>" <minutes> [mode]')
        goal = parts[0]
        try:
            minutes = int(parts[1])
        except ValueError:
            raise ValueError("minutes must be an integer")
        if minutes <= 0:
            raise ValueError("minutes must be positive")
        mode = self._parse_mode(parts[2]) if len(parts) > 2 else SessionMode.STRICT
        self.orchestrator.start_session(goal, minutes, mode)
        self._fired_alerts.clear()
        self._prefill_alerts()
        self.ui.agent_say(f'Session started. Goal: "{goal}". Time: {minutes}m. Mode: {mode.value}.')

    def _handle_stop(self, args: str) -> None:
        session = self.orchestrator.stop_session()
        self.ui.render_summary(session, self.orchestrator.events)

    def _handle_status(self, args: str) -> None:
        self._refresh()

    def _handle_pause(self, args: str) -> None:
        self.orchestrator.pause_session()
        self._refresh("Session paused.")

    def _handle_resume(self, args: str) -> None:
        self.orchestrator.resume_session()
        self._refresh("Session resumed.")

    def _handle_mode(self, args: str) -> None:
        mode = self._parse_mode(args.strip())
        self.orchestrator.set_mode(mode)
        self._refresh(f"Mode set to {mode.value}.")

    def _handle_block(self, args: str) -> None:
        domain = args.strip()
        if not domain:
            raise ValueError("usage: /block <domain>")
        d = self.orchestrator.add_block(domain)
        self._refresh(f"Blocked {d}.")

    def _handle_allow(self, args: str) -> None:
        domain = args.strip()
        if not domain:
            raise ValueError("usage: /allow <domain>")
        d = self.orchestrator.add_allow(domain)
        self._refresh(f"Allowed {d}.")

    def _handle_blocks(self, args: str) -> None:
        blocked = self.orchestrator.policy.list_blocked()
        allowed = self.orchestrator.policy.list_allowed()
        self.ui.info(f"blocked ({len(blocked)}): {', '.join(blocked) or '(none)'}")
        self.ui.info(f"allowed ({len(allowed)}): {', '.join(allowed) or '(none)'}")

    def _handle_time(self, args: str) -> None:
        s = self.orchestrator.session
        if s is None or not s.is_active():
            raise ValueError("no active session")
        raw = args.strip()
        if not raw:
            raise ValueError("usage: /time +20 | /time -10 | /time 45")
        if raw.startswith(("+", "-")):
            try:
                delta = int(raw)
            except ValueError:
                raise ValueError("usage: /time +20 | /time -10 | /time 45")
            s.adjust_time(delta)
            self._fired_alerts.clear()
            self._prefill_alerts()
            word = "added" if delta > 0 else "removed"
            self.ui.agent_say(f"{word} {abs(delta)} minute{'s' if abs(delta) != 1 else ''}.")
        else:
            try:
                new_mins = int(raw)
            except ValueError:
                raise ValueError("usage: /time +20 | /time -10 | /time 45")
            if new_mins <= 0:
                raise ValueError("minutes must be positive")
            from datetime import timedelta
            current_elapsed = s.duration - s.time_remaining()
            s.duration = current_elapsed + timedelta(minutes=new_mins)
            self._fired_alerts.clear()
            self._prefill_alerts()
            self.ui.agent_say(f"Time set to {new_mins} minutes from now.")

    def _handle_help(self, args: str) -> None:
        self.ui.render_help()

    def _handle_clear(self, args: str) -> None:
        self.ui.console.clear()

    def _handle_quit(self, args: str) -> None:
        self.ui.info("bye")
        self._running = False

    # --- helpers ---

    def _start_ticker(self) -> None:
        """Background thread: repaints toolbar and fires time alerts."""
        def _tick():
            while True:
                _time.sleep(1)
                try:
                    get_app().invalidate()
                except Exception:
                    pass
                self._check_alerts()
        t = threading.Thread(target=_tick, daemon=True)
        t.start()

    def _prefill_alerts(self) -> None:
        """Pre-fire all thresholds already above current time so they don't trigger."""
        s = self.orchestrator.session
        if s is None:
            return
        mins_left = s.time_remaining().total_seconds() / 60
        for threshold in _ALERT_THRESHOLDS:
            if threshold > mins_left:
                self._fired_alerts.add(threshold)

    def _check_alerts(self) -> None:
        s = self.orchestrator.session
        if s is None or not s.is_active():
            return
        mins_left = s.time_remaining().total_seconds() / 60
        for threshold in _ALERT_THRESHOLDS:
            if mins_left <= threshold and threshold not in self._fired_alerts:
                self._fired_alerts.add(threshold)
                label = f"{threshold} minute{'s' if threshold != 1 else ''}"
                try:
                    print_formatted_text(HTML(f"\n<yellow>  ! {label} remaining in your session!</yellow>"))
                except Exception:
                    pass

    def _toolbar(self) -> str:
        s = self.orchestrator.session
        if s is None or s.status.value in ("stopped", "completed"):
            return " Focus Guardian  ·  No active session  ·  /start \"goal\" <minutes> to begin"
        total = max(int(s.time_remaining().total_seconds()), 0)
        h, rem = divmod(total, 3600)
        m, sec = divmod(rem, 60)
        time_str = f"{h:02d}:{m:02d}:{sec:02d}"
        status = s.status.value.upper()
        return (
            f" Focus Guardian  ·  {status}  ·  {s.goal}\n"
            f" Time left: {time_str}  ·  Mode: {s.mode.value}  ·  Offenses: {s.offense_count}"
        )

    def _refresh(self, message: str | None = None) -> None:
        """Redraw the dashboard (clears previous frame)."""
        self.ui.render_dashboard(
            self.orchestrator.session,
            self.orchestrator.recent_events(),
            message=message,
        )

    @staticmethod
    def _parse_mode(raw: str) -> SessionMode:
        raw = raw.strip().lower()
        if not raw:
            raise ValueError("usage: /mode strict|soft")
        try:
            return SessionMode(raw)
        except ValueError:
            raise ValueError(f"mode must be 'strict' or 'soft' (got '{raw}')")
