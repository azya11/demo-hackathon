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
    /quit                          Exit app
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass

from app.session import SessionMode


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
        self._handlers = {
            "start": self._handle_start,
            "stop": self._handle_stop,
            "status": self._handle_status,
            "pause": self._handle_pause,
            "resume": self._handle_resume,
            "mode": self._handle_mode,
            "help": self._handle_help,
            "quit": self._handle_quit,
            "exit": self._handle_quit,
        }

    def run(self) -> None:
        """Main REPL loop: read line → parse → dispatch → render."""
        self.ui.render_welcome()
        self._running = True
        while self._running:
            try:
                line = input(self.PROMPT).strip()
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
        self.ui.agent_say(f'Session started. Goal: "{goal}". Time: {minutes}m. Mode: {mode.value}.')
        self.ui.render_dashboard(self.orchestrator.session, self.orchestrator.recent_events())

    def _handle_stop(self, args: str) -> None:
        session = self.orchestrator.stop_session()
        self.ui.agent_say("Session stopped.")
        self.ui.render_summary(session, self.orchestrator.events)

    def _handle_status(self, args: str) -> None:
        self.ui.render_dashboard(self.orchestrator.session, self.orchestrator.recent_events())

    def _handle_pause(self, args: str) -> None:
        self.orchestrator.pause_session()
        self.ui.agent_say("Session paused.")

    def _handle_resume(self, args: str) -> None:
        self.orchestrator.resume_session()
        self.ui.agent_say("Session resumed.")

    def _handle_mode(self, args: str) -> None:
        mode = self._parse_mode(args.strip())
        self.orchestrator.set_mode(mode)
        self.ui.agent_say(f"Mode set to {mode.value}.")

    def _handle_help(self, args: str) -> None:
        self.ui.render_help()

    def _handle_quit(self, args: str) -> None:
        self.ui.info("bye")
        self._running = False

    @staticmethod
    def _parse_mode(raw: str) -> SessionMode:
        raw = raw.strip().lower()
        if not raw:
            raise ValueError("usage: /mode strict|soft")
        try:
            return SessionMode(raw)
        except ValueError:
            raise ValueError(f"mode must be 'strict' or 'soft' (got '{raw}')")
