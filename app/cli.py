"""Command-line interface.

Parses slash-style commands from the user and dispatches them to the
orchestrator. Keeps UI rendering separate (see ui.py).

Commands:
    /start "<goal>" <min> [mode]   Begin a focus session
    /stop                          End current session
    /status                        Show current session state
    /pause                         Pause session timer + enforcement
    /resume                        Resume after pause
    /settings                      Open interactive settings menu
    /help                          List commands
    /clear                         Clear screen and redraw
    /quit                          Exit app
"""

from __future__ import annotations

import os
import shlex
import threading
import time as _time
from dataclasses import dataclass

from prompt_toolkit import PromptSession
from prompt_toolkit.application import Application, get_app
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML, FormattedText
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.shortcuts import print_formatted_text
from prompt_toolkit.styles import Style

def _arrow_select(
    title: str,
    items: list[tuple[str, str]],
    get_inline=None,
    on_cycle=None,
) -> int | None:
    """Display an arrow-navigable menu. Returns selected index or None if cancelled.

    items: list of (name, description) tuples.
    get_inline(name) -> str|None: optional inline value shown next to the name.
    on_cycle(name, direction) -> bool: called on left/right; return True if handled.
    """
    import sys
    if not sys.stdin.isatty() or not items:
        return None

    state = {"idx": 0}

    def _render():
        lines: list[tuple[str, str]] = []
        lines.append(("fg:#cba6f7 bold", f"  {title}\n\n"))
        for i, (name, desc) in enumerate(items):
            inline = get_inline(name) if get_inline else None
            is_sel = i == state["idx"]
            cyclable = on_cycle is not None and inline is not None
            if is_sel:
                lines.append(("fg:#cba6f7 bold", "  \u276f "))
                lines.append(("fg:#cdd6f4 bold", f"{name:<10}"))
            else:
                lines.append(("", "    "))
                lines.append(("fg:#6c7086", f"{name:<10}"))
            if inline is not None:
                if is_sel and cyclable:
                    lines.append(("fg:#6c7086", " \u2039 "))
                    lines.append(("fg:#94e2d5 bold", inline))
                    lines.append(("fg:#6c7086", " \u203a"))
                else:
                    lines.append(("fg:#6c7086", "  "))
                    lines.append(("fg:#94e2d5" if is_sel else "fg:#585b70", inline))
            if is_sel:
                lines.append(("fg:#a6adc8", f"   {desc}\n"))
            else:
                lines.append(("", "\n"))
        return lines

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    @kb.add("c-p")
    def _(event):
        state["idx"] = (state["idx"] - 1) % len(items)

    @kb.add("down")
    @kb.add("j")
    @kb.add("c-n")
    def _(event):
        state["idx"] = (state["idx"] + 1) % len(items)

    @kb.add("left")
    @kb.add("h")
    def _(event):
        if on_cycle is not None:
            on_cycle(items[state["idx"]][0], -1)

    @kb.add("right")
    @kb.add("l")
    def _(event):
        if on_cycle is not None:
            on_cycle(items[state["idx"]][0], +1)

    @kb.add("enter")
    def _(event):
        event.app.exit(result=state["idx"])

    @kb.add("escape", eager=True)
    @kb.add("q")
    @kb.add("c-c")
    @kb.add("c-d")
    def _(event):
        event.app.exit(result=None)

    control = FormattedTextControl(_render, focusable=True, show_cursor=False)
    window = Window(control, height=len(items) + 3, always_hide_cursor=True)
    app = Application(
        layout=Layout(HSplit([window])),
        key_bindings=kb,
        full_screen=False,
        mouse_support=False,
    )
    try:
        return app.run()
    except Exception:
        return None


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
from app.typegame import TypingGame, load_all_stats

_COMMANDS = ["start", "stop", "status", "pause", "resume", "settings", "help", "clear", "quit"]
_MODE_ARGS = ["chill", "normal", "hardcore"]
_ALERT_THRESHOLDS = [60, 30, 10, 5, 1]  # minutes

_COMMAND_META = {
    "start":    "begin a focus session  /start [\"goal\" <min>]",
    "stop":     "end current session",
    "status":   "show current session state",
    "pause":    "pause session timer",
    "resume":   "resume after pause",
    "settings": "view/edit all settings (mode, grace, time, blocks, ...)",
    "help":     "show all commands",
    "clear":    "clear the screen",
    "quit":     "exit app",
    "exit":     "exit app",
}

_MODE_META = {
    "chill":    "monitor only, never close",
    "normal":   "close after grace period",
    "hardcore": "close immediately",
}


class _SlashCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lstrip()
        if text.startswith("/"):
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
            "settings": self._handle_settings,
            "help": self._handle_help,
            "gamestats": self._handle_gamestats,
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
        if len(parts) == 0:
            goal = "study"
            minutes = 60
        elif len(parts) == 1:
            # could be just a goal, or just a number — if it parses as int, treat as minutes
            try:
                minutes = int(parts[0])
                goal = "study"
            except ValueError:
                goal = parts[0]
                minutes = 60
        else:
            goal = parts[0]
            try:
                minutes = int(parts[1])
            except ValueError:
                raise ValueError("minutes must be an integer")
        if minutes <= 0:
            raise ValueError("minutes must be positive")
        mode = self._parse_mode(parts[2]) if len(parts) > 2 else self.orchestrator.default_mode
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
        self.ui.info("Want to play the typing game while on break? [y/N]")
        try:
            answer = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer == "y":
            TypingGame().run()
            self._refresh("Welcome back! Session still paused.")

    def _handle_resume(self, args: str) -> None:
        self.orchestrator.resume_session()
        self._refresh("Session resumed.")

    def _handle_mode(self, args: str) -> None:
        mode = self._parse_mode(args.strip())
        s = self.orchestrator.session
        if s is not None and s.is_active():
            self.orchestrator.set_mode(mode)
        else:
            self.orchestrator.set_default_mode(mode)
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

    def _handle_pblock(self, args: str) -> None:
        name = args.strip()
        if not name:
            raise ValueError("usage: /pblock <process.exe>")
        n = self.orchestrator.add_process_block(name)
        self._refresh(f"Process blocked: {n}.")

    def _handle_pallow(self, args: str) -> None:
        name = args.strip()
        if not name:
            raise ValueError("usage: /pallow <process.exe>")
        n = self.orchestrator.add_process_allow(name)
        self._refresh(f"Process allowed: {n}.")

    def _handle_pblocks(self, args: str) -> None:
        pm = self.orchestrator.process_monitor
        if pm is None:
            self.ui.warn("process monitor not available (install psutil)")
            return
        blocked = pm.list_blocked()
        allowed = pm.list_allowed()
        self.ui.info(f"p-blocked ({len(blocked)}): {', '.join(blocked) or '(none)'}")
        self.ui.info(f"p-allowed ({len(allowed)}): {', '.join(allowed) or '(none)'}")

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

    def _handle_settings(self, args: str) -> None:
        # One-shot form: /settings <sub> <args...>
        parts = args.strip().split(None, 1)
        if parts:
            sub = parts[0].lower()
            rest = parts[1] if len(parts) > 1 else ""
            self._settings_dispatch(sub, rest)
            return
        # Interactive form: /settings with no args → menu loop.
        self._settings_menu()

    def _settings_dispatch(self, sub: str, rest: str) -> None:
        dispatch = {
            "mode":    self._handle_mode,
            "time":    self._handle_time,
            "block":   self._handle_block,
            "allow":   self._handle_allow,
            "blocks":  self._handle_blocks,
            "pblock":  self._handle_pblock,
            "pallow":  self._handle_pallow,
            "pblocks": self._handle_pblocks,
        }
        if sub == "grace":
            self._settings_set_grace(rest)
            return
        if sub not in dispatch:
            raise ValueError(
                "options: mode|time|block|allow|blocks|pblock|pallow|pblocks|grace"
            )
        dispatch[sub](rest)

    def _settings_set_grace(self, raw: str) -> None:
        raw = raw.strip()
        if not raw:
            self.ui.info(f"grace: {self.orchestrator.grace_seconds}s (normal mode)")
            return
        try:
            mins = float(raw)
        except ValueError:
            raise ValueError("usage: grace <minutes>")
        if mins < 0:
            raise ValueError("grace must be >= 0")
        self.orchestrator.set_grace(int(mins * 60))
        self.ui.agent_say(f"Grace period set to {mins}m.")

    def _settings_menu(self) -> None:
        items = [
            ("theme",          "color theme (←/→ to switch)"),
            ("mode",           "enforcement mode (←/→ to switch)"),
            ("grace",          "normal-mode grace period (←/→ to switch)"),
            ("coach",          "AI focus coach (←/→ on/off)"),
            ("coach_interval", "coach check-in interval (←/→ to switch)"),
            ("time",           "adjust session time (+20 | -10 | 45)"),
            ("block",          "block a site"),
            ("allow",          "allow a site"),
            ("blocks",         "show blocked/allowed sites"),
            ("pblock",         "block a process"),
            ("pallow",         "allow a process"),
            ("pblocks",        "show blocked/allowed processes"),
        ]
        mode_values = ["chill", "normal", "hardcore"]
        grace_values = [2, 5, 10, 15]  # minutes
        coach_interval_values = [2, 5, 10, 30, 60]  # minutes

        import app.themes as _themes

        def _get_inline(name: str) -> str | None:
            o = self.orchestrator
            s = o.session
            if name == "theme":
                return _themes.current.name
            if name == "mode":
                return (s.mode.value if s else o.default_mode.value)
            if name == "grace":
                return f"{o.grace_seconds // 60}m"
            if name == "coach":
                return "on" if o.coach_enabled else "off"
            if name == "coach_interval":
                return f"{o.coach_interval_minutes}m"
            return None

        def _on_cycle(name: str, direction: int) -> None:
            if name == "theme":
                idx = next((i for i, t in enumerate(_themes.THEMES) if t.name == _themes.current.name), 0)
                _themes.current = _themes.THEMES[(idx + direction) % len(_themes.THEMES)]
                return
            o = self.orchestrator
            if name == "mode":
                s = o.session
                cur = (s.mode.value if s else o.default_mode.value)
                try:
                    i = mode_values.index(cur)
                except ValueError:
                    i = 0
                new_val = mode_values[(i + direction) % len(mode_values)]
                try:
                    new_mode = SessionMode(new_val)
                except ValueError:
                    return
                if s is not None and s.is_active():
                    try:
                        o.set_mode(new_mode)
                    except Exception:
                        pass
                else:
                    o.set_default_mode(new_mode)
                return
            if name == "grace":
                cur_min = max(o.grace_seconds // 60, 0)
                # snap to nearest preset, then cycle
                try:
                    i = grace_values.index(cur_min)
                except ValueError:
                    # not on a preset — pick the closest
                    i = min(
                        range(len(grace_values)),
                        key=lambda k: abs(grace_values[k] - cur_min),
                    )
                new_min = grace_values[(i + direction) % len(grace_values)]
                o.set_grace(new_min * 60)
                return
            if name == "coach":
                o.coach_enabled = not o.coach_enabled
                return
            if name == "coach_interval":
                try:
                    i = coach_interval_values.index(o.coach_interval_minutes)
                except ValueError:
                    i = 2  # default to 10m
                o.coach_interval_minutes = coach_interval_values[(i + direction) % len(coach_interval_values)]
                return

        while True:
            self.ui._clear()
            idx = _arrow_select(
                "Settings  (↑/↓ move · ←/→ cycle · Enter select · Esc exit)",
                items,
                get_inline=_get_inline,
                on_cycle=_on_cycle,
            )
            if idx is None:
                self._settings_save_all()
                self._refresh()
                return
            name = items[idx][0]
            # Cycled settings — Enter confirms & exits.
            if name in ("theme", "mode", "grace", "coach", "coach_interval"):
                self._settings_save_all()
                self._refresh("Settings saved.")
                return
            # Display-only actions: show the list and wait for Enter.
            if name in ("blocks", "pblocks"):
                try:
                    self._settings_dispatch(name, "")
                except Exception as e:
                    self.ui.error(str(e))
                try:
                    input("  (press Enter to continue) ")
                except (EOFError, KeyboardInterrupt):
                    pass
                continue
            arg = self._settings_prompt_for(name)
            if arg is None:
                continue
            try:
                self._settings_dispatch(name, arg)
            except Exception as e:
                self.ui.error(str(e))

    def _pick_theme(self) -> None:
        """Arrow-select theme picker with live color preview."""
        import app.themes as _themes
        themes = _themes.THEMES

        # Build items: each theme's name shown in its own accent color
        def _render_themed(items, state):
            """Custom render that colors each row with its theme's accent."""
            lines = []
            lines.append(("fg:#cba6f7 bold", "  Themes  (↑/↓ browse · Enter apply · Esc back)\n\n"))
            for i, (name, desc) in enumerate(items):
                th = themes[i]
                is_sel = i == state["idx"]
                if is_sel:
                    lines.append((f"bold {th.accent}", f"  \u276f {name:<22}"))
                    lines.append((th.dim,              f"  {desc}\n"))
                else:
                    lines.append((th.dim,              f"    {name:<22}  {desc}\n"))
            lines.append(("", "\n"))
            return lines

        # Use a custom _arrow_select-like loop with themed rendering
        from prompt_toolkit import Application
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import Layout
        from prompt_toolkit.layout.containers import HSplit, Window
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.formatted_text import FormattedText

        items = [(t.name, t.description) for t in themes]
        cur_name = _themes.current.name
        state = {"idx": next((i for i, t in enumerate(themes) if t.name == cur_name), 0)}

        def _render():
            return _render_themed(items, state)

        kb = KeyBindings()

        @kb.add("up")
        @kb.add("k")
        def _up(event):
            state["idx"] = (state["idx"] - 1) % len(themes)
            event.app.invalidate()

        @kb.add("down")
        @kb.add("j")
        def _down(event):
            state["idx"] = (state["idx"] + 1) % len(themes)
            event.app.invalidate()

        @kb.add("enter")
        def _enter(event):
            event.app.exit(result=state["idx"])

        @kb.add("escape", eager=True)
        @kb.add("q")
        @kb.add("c-c")
        def _cancel(event):
            event.app.exit(result=None)

        control = FormattedTextControl(_render, focusable=True, show_cursor=False)
        window = Window(control, height=len(themes) + 5, always_hide_cursor=True)
        app = Application(
            layout=Layout(HSplit([window])),
            key_bindings=kb,
            full_screen=False,
            mouse_support=False,
        )
        try:
            result = app.run()
        except Exception:
            result = None

        if result is not None:
            _themes.current = themes[result]
            self.ui.agent_say(f"Theme set to {_themes.current.name}.")

    def _settings_save_all(self) -> None:
        o = self.orchestrator
        try:
            o._save_settings()
            o._save_sites()
            o._save_processes()
        except Exception as e:
            self.ui.error(f"failed to save settings: {e}")

    def _settings_prompt_for(self, name: str) -> str | None:
        prompts = {
            "mode":    "new mode (chill|normal|hardcore): ",
            "grace":   "grace period in minutes: ",
            "time":    "time change (+20 | -10 | 45): ",
            "block":   "domain to block: ",
            "allow":   "domain to allow: ",
            "pblock":  "process name (e.g. spotify.exe): ",
            "pallow":  "process name to allow: ",
        }
        if name in ("blocks", "pblocks"):
            return ""  # no arg needed
        try:
            val = input(prompts.get(name, f"{name}: ")).strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if not val:
            self.ui.info("(skipped)")
            return None
        return val

    def _render_settings(self) -> None:
        o = self.orchestrator
        s = o.session
        self.ui.info(f"mode:    {s.mode.value if s else o.default_mode.value} (default {o.default_mode.value})")
        self.ui.info(f"grace:   {o.grace_seconds}s (normal mode)")
        if s is not None:
            rem = int(s.time_remaining().total_seconds() // 60)
            self.ui.info(f"time:    {rem}m remaining of {int(s.duration.total_seconds()//60)}m")
        else:
            self.ui.info("time:    no active session")
        blocked = o.policy.list_blocked()
        allowed = o.policy.list_allowed()
        self.ui.info(f"sites blocked ({len(blocked)}): {', '.join(blocked) or '(none)'}")
        self.ui.info(f"sites allowed ({len(allowed)}): {', '.join(allowed) or '(none)'}")
        pm = o.process_monitor
        if pm is not None:
            self.ui.info(f"procs blocked ({len(pm.list_blocked())}): {', '.join(pm.list_blocked()) or '(none)'}")
            self.ui.info(f"procs allowed ({len(pm.list_allowed())}): {', '.join(pm.list_allowed()) or '(none)'}")

    def _handle_help(self, args: str) -> None:
        self.ui.render_help()

    def _handle_gamestats(self, args: str) -> None:
        self.ui.render_gamestats(load_all_stats())
        input("\nPress Enter to return...")
        self._refresh()

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
        import app.themes as _themes
        from prompt_toolkit.formatted_text import FormattedText
        th = _themes.current
        DIM = f"fg:{th.dim}"
        MED = f"fg:{th.subtext}"
        s = self.orchestrator.session

        if s is None or s.status.value in ("stopped", "completed"):
            return FormattedText([
                (f"fg:{th.accent}",  "  ◆  Focus Guardian"),
                (DIM,                "  │  no active session  │  "),
                (MED,                '/start "goal" <minutes>'),
                (DIM,                "  to begin"),
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

        dur  = max(s.duration.total_seconds(), 1)
        frac = max(0.0, min(1.0, total_secs / dur))
        filled = round(frac * 20)
        bar = "#" * filled + "-" * (20 - filled)
        bar_color = f"fg:{th.active if frac > 0.5 else (th.warning if frac > 0.25 else th.error)}"

        icons     = {"active": "▶", "paused": "⏸", "stopped": "■", "completed": "✓", "idle": "○"}
        st_colors = {"active": th.active, "paused": th.warning, "stopped": th.error, "completed": th.complete, "idle": th.dim}
        icon      = icons.get(s.status.value, "●")
        st_color  = f"fg:{st_colors.get(s.status.value, th.text)}"
        _mode_map = {"hardcore": th.error, "normal": th.warning, "chill": th.info, "strict": th.error, "soft": th.info}
        mode_color = f"fg:{_mode_map.get(s.mode.value, th.text)}"
        off_color  = f"fg:{th.active if s.offense_count == 0 else (th.warning if s.offense_count < 3 else th.error)}"
        goal = s.goal if len(s.goal) <= 28 else s.goal[:26] + "..."
        pct  = f"{int(frac * 100):3d}%"

        return FormattedText([
            (f"fg:{th.accent}", "  ◆  "),
            (st_color,          f"{icon} {s.status.value.upper()}"),
            (DIM,               "  │  "),
            (f"fg:{th.text}",   f'"{goal}"'),
            (DIM,               "  │  "),
            (bar_color,         bar),
            (DIM,               f" {pct}  │  "),
            (f"fg:{th.info}",   f"⏱ {time_str} left"),
            (DIM,               "  │  elapsed "),
            (MED,               elapsed_str),
            (DIM,               "  │  "),
            (mode_color,        s.mode.value),
            (DIM,               "  │  ⚠ "),
            (off_color,         str(s.offense_count)),
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
            raise ValueError("usage: /mode chill|normal|hardcore")
        try:
            return SessionMode(raw)
        except ValueError:
            raise ValueError(f"mode must be 'chill', 'normal', or 'hardcore' (got '{raw}')")
