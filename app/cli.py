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
from prompt_toolkit.formatted_text import HTML, FormattedText
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.shortcuts import print_formatted_text
from prompt_toolkit.styles import Style

class _SlashLexer(Lexer):
    def lex_document(self, document):
        text = document.text

        def get_line(lineno):
            s = text.lstrip()
            if not s.startswith("/"):
                return [("", text)]
            body = s[1:]
            # split on first whitespace but keep the rest (including trailing space)
            space_idx = next((i for i, c in enumerate(body) if c in " \t"), None)
            if space_idx is None:
                cmd, rest = body.lower(), ""
            else:
                cmd, rest = body[:space_idx].lower(), body[space_idx:]
            leading = text[: len(text) - len(s)]
            if cmd in set(_COMMANDS):
                return [("", leading), ("fg:#cba6f7 bold", "/" + cmd), ("", rest)]
            return [("", text)]

        return get_line


_kb = KeyBindings()

@_kb.add("backspace")
def _backspace_and_complete(event):
    event.current_buffer.delete_before_cursor()
    if event.current_buffer.text.lstrip().startswith("/"):
        event.current_buffer.start_completion(select_first=False)


_COMPLETION_STYLE = Style.from_dict({
    "completion-menu":                         "bg:#1e1e2e",
    "completion-menu.completion":              "bg:#1e1e2e fg:#cdd6f4",
    "completion-menu.completion.current":      "bg:#313244 fg:#cba6f7 bold",
    "completion-menu.meta.completion":         "bg:#1e1e2e fg:#6c7086",
    "completion-menu.meta.completion.current": "bg:#313244 fg:#a6adc8",
    "scrollbar.background":                    "bg:#313244",
    "scrollbar.button":                        "bg:#cba6f7",
    "bottom-toolbar":                          "bg:#181825 fg:#6c7086 noreverse",
})

from app.models import EventType
from app.session import SessionMode

_COMMANDS = ["start", "stop", "status", "pause", "resume", "mode", "time", "help", "clear", "quit"]
_MODE_ARGS = ["strict", "soft"]
_ALERT_THRESHOLDS = [60, 30, 10, 5, 1]  # minutes

_COMMAND_META = {
    "start":  "begin a focus session  /start \"goal\" <min>",
    "stop":   "end current session",
    "status": "show current session state",
    "pause":  "pause session timer",
    "resume": "resume after pause",
    "mode":   "switch enforcement mode  strict|soft",
    "time":   "adjust time  +20 | -10 | 45",
    "help":   "show all commands",
    "clear":  "clear the screen",
    "quit":   "exit app",
    "exit":   "exit app",
}

_MODE_META = {
    "strict": "warn + close tab",
    "soft":   "warn only",
}


class _SlashCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lstrip()
        if text.startswith("/mode "):
            typed = text[len("/mode "):]
            for m in _MODE_ARGS:
                if m.startswith(typed):
                    yield Completion(
                        "/mode " + m,
                        start_position=-len(text),
                        display=FormattedText([("bold", "/mode "), ("", m)]),
                        display_meta=FormattedText([("fg:#6c7086", _MODE_META.get(m, ""))]),
                    )
        elif text.startswith("/"):
            typed = text[1:]
            if " " in typed:  # already past the command name
                return
            matches = [cmd for cmd in _COMMANDS if cmd.startswith(typed)]
            if len(matches) == 1 and matches[0] == typed:
                return  # fully typed exact match — no popup
            for cmd in matches:
                yield Completion(
                    "/" + cmd,
                    start_position=-len(text),
                    display=FormattedText([("fg:#cba6f7 bold", "/"), ("fg:#cdd6f4", cmd)]),
                    display_meta=FormattedText([("fg:#6c7086", _COMMAND_META.get(cmd, ""))]),
                )


@dataclass
class Command:
    """Parsed command: name + raw args string."""
    name: str
    args: str


class CLI:
    """Reads input, parses commands, dispatches to orchestrator."""

    PROMPT = "> "

    def __init__(self, orchestrator, ui) -> None:
        self.orchestrator = orchestrator
        self.ui = ui
        self._running = False
        self._fired_alerts: set[int] = set()
        import sys
        def _should_complete():
            try:
                text = get_app().current_buffer.text.lstrip()
                if not text.startswith("/"):
                    return False
                typed = text[1:]
                if " " in typed:
                    return False
                matches = [c for c in _COMMANDS if c.startswith(typed)]
                if not matches or (len(matches) == 1 and matches[0] == typed):
                    return False
                return True
            except Exception:
                return False
        self._session = PromptSession(completer=_SlashCompleter(), complete_while_typing=Condition(_should_complete), style=_COMPLETION_STYLE, key_bindings=_kb, lexer=_SlashLexer()) if sys.stdin.isatty() else None
        self._start_ticker()
        self._handlers = {
            "start": self._handle_start,
            "stop": self._handle_stop,
            "status": self._handle_status,
            "pause": self._handle_pause,
            "resume": self._handle_resume,
            "mode": self._handle_mode,
            "time": self._handle_time,
            "help": self._handle_help,
            "clear": self._handle_clear,
            "quit": self._handle_quit,
            "exit": self._handle_quit,
            "q": self._handle_quit,
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
            self.ui.console.print()

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
        self._refresh(f'Session started. Goal: "{goal}". Time: {minutes}m. Mode: {mode.value}.')

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
            word = "added" if delta > 0 else "removed"
            label = f"{word} {abs(delta)} minute{'s' if abs(delta) != 1 else ''}"
            self.orchestrator.adjust_time(delta, label)
            self._fired_alerts.clear()
            self._prefill_alerts()
            self.ui.agent_say(label + ".")
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
            s.duration = current_elapsed + timedelta(minutes=new_mins)
            self.orchestrator._log(EventType.TIME_ADJUSTED, reason=f"set to {new_mins}m from now")
            self._fired_alerts.clear()
            self._prefill_alerts()
            self.ui.agent_say(f"Time set to {new_mins} minutes from now.")

    def _handle_help(self, args: str) -> None:
        self.ui.render_help()

    def _handle_clear(self, args: str) -> None:
        self.ui._clear()

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

    def _toolbar(self):
        from prompt_toolkit.formatted_text import FormattedText
        DIM  = "fg:#585b70"
        MED  = "fg:#a6adc8"
        s = self.orchestrator.session

        if s is None or s.status.value in ("stopped", "completed"):
            return FormattedText([
                ("fg:#cba6f7",  "  ◆  Focus Guardian"),
                (DIM,           "  ─────────────────────────────────────────────"),
                ("",            "\n"),
                (DIM,           "  no active session  ·  "),
                (MED,           '/start "goal" <minutes>'),
                (DIM,           "  to begin"),
            ])

        # time remaining
        total_secs = max(int(s.time_remaining().total_seconds()), 0)
        h, rem = divmod(total_secs, 3600)
        m, sec = divmod(rem, 60)
        time_str = f"{h:02d}:{m:02d}:{sec:02d}"

        # elapsed
        if s.started_at is not None:
            from datetime import datetime
            elapsed_secs = max(int((datetime.now() - s.started_at - s.paused_duration).total_seconds()), 0)
            if s.status.value == "paused" and s.pause_started_at:
                elapsed_secs = max(int((s.pause_started_at - s.started_at - s.paused_duration).total_seconds()), 0)
            eh, er = divmod(elapsed_secs, 3600)
            em, es = divmod(er, 60)
            elapsed_str = f"{eh:02d}:{em:02d}:{es:02d}"
        else:
            elapsed_str = "00:00:00"

        # progress bar (24 wide)
        dur  = max(s.duration.total_seconds(), 1)
        frac = max(0.0, min(1.0, total_secs / dur))
        filled = round(frac * 24)
        bar = "█" * filled + "░" * (24 - filled)
        if frac > 0.5:
            bar_color = "fg:#a6e3a1"
        elif frac > 0.25:
            bar_color = "fg:#f9e2af"
        else:
            bar_color = "fg:#f38ba8"

        icons  = {"active": "▶", "paused": "⏸", "stopped": "■", "completed": "✓", "idle": "◌"}
        colors = {"active": "fg:#a6e3a1", "paused": "fg:#f9e2af", "stopped": "fg:#f38ba8", "completed": "fg:#89b4fa", "idle": "fg:#585b70"}
        icon     = icons.get(s.status.value, "·")
        st_color = colors.get(s.status.value, "fg:#cdd6f4")
        mode_color = "fg:#f38ba8" if s.mode.value == "strict" else "fg:#94e2d5"
        off_color  = "fg:#a6e3a1" if s.offense_count == 0 else ("fg:#f9e2af" if s.offense_count < 3 else "fg:#f38ba8")
        goal = s.goal if len(s.goal) <= 36 else s.goal[:34] + "…"

        return FormattedText([
            # ── line 1 ──────────────────────────────────────────
            ("fg:#cba6f7",  "  ◆  Focus Guardian"),
            (DIM,           "  │  "),
            (st_color,      f"{icon}  {s.status.value.upper()}"),
            (DIM,           "  │  "),
            ("fg:#cdd6f4",  f'"{goal}"'),
            (DIM,           "  │  "),
            (mode_color,    s.mode.value),
            (DIM,           "  │  "),
            (off_color,     f"⚠  {s.offense_count} offense{'s' if s.offense_count != 1 else ''}"),
            ("",            "\n"),
            # ── line 2 ──────────────────────────────────────────
            (DIM,           "  "),
            (bar_color,     bar),
            (DIM,           f"  {int(frac * 100):3d}%  │  "),
            ("fg:#94e2d5",  f"⏱  {time_str} left"),
            (DIM,           "  │  elapsed  "),
            (MED,           elapsed_str),
        ])

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
