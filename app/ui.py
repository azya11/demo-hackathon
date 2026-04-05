"""Terminal UI layer — Focus Guardian AI v0.2

Catppuccin Mocha palette, gradient titles, Unicode progress bars,
animated event feed. All presentation logic lives here.
"""

from __future__ import annotations

import time
from datetime import timedelta

from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

# ---------------------------------------------------------------------------
# Catppuccin Mocha palette
# ---------------------------------------------------------------------------
_ROSEWATER = "#f5e0dc"
_FLAMINGO  = "#f2cdcd"
_PINK      = "#f5c2e7"
_MAUVE     = "#cba6f7"
_RED       = "#f38ba8"
_MAROON    = "#eba0ac"
_PEACH     = "#fab387"
_YELLOW    = "#f9e2af"
_GREEN     = "#a6e3a1"
_TEAL      = "#94e2d5"
_SKY       = "#89dceb"
_SAPPHIRE  = "#74c7ec"
_BLUE      = "#89b4fa"
_LAVENDER  = "#b4befe"
_TEXT      = "#cdd6f4"
_SUBTEXT1  = "#bac2de"
_SUBTEXT0  = "#a6adc8"
_OVERLAY2  = "#9399b2"
_OVERLAY1  = "#7f849c"
_OVERLAY0  = "#6c7086"
_SURFACE2  = "#585b70"
_SURFACE1  = "#45475a"
_SURFACE0  = "#313244"
_BASE      = "#1e1e2e"
_MANTLE    = "#181825"
_CRUST     = "#11111b"

# ---------------------------------------------------------------------------
# Status / event theming
# ---------------------------------------------------------------------------
_STATUS_COLORS = {
    "active":    _GREEN,
    "paused":    _YELLOW,
    "idle":      _OVERLAY0,
    "stopped":   _RED,
    "completed": _BLUE,
}

_STATUS_ICONS = {
    "active":    "▶",
    "paused":    "⏸",
    "idle":      "◌",
    "stopped":   "■",
    "completed": "✓",
}

_EVENT_SYMBOLS = {
    "session_started":   ("▶", _GREEN),
    "session_stopped":   ("■", _RED),
    "session_paused":    ("⏸", _YELLOW),
    "session_resumed":   ("▶", _TEAL),
    "session_completed": ("✓", _BLUE),
    "warning_issued":    ("⚠", _YELLOW),
    "tab_closed":        ("✗", _RED),
    "tab_observed":      ("◈", _OVERLAY0),
    "ai_classified":     ("◆", _MAUVE),
    "mode_changed":      ("◎", _LAVENDER),
    "time_adjusted":     ("⏱", _TEAL),
}

_EVENT_FEED_LIMIT = 7

# ---------------------------------------------------------------------------
# Gradient helpers
# ---------------------------------------------------------------------------

def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)


def _gradient_text(text: str, start_hex: str, end_hex: str) -> Text:
    """Return a Rich Text object with per-character RGB gradient."""
    r1, g1, b1 = _hex_to_rgb(start_hex)
    r2, g2, b2 = _hex_to_rgb(end_hex)
    rich_text = Text()
    n = max(len(text) - 1, 1)
    for i, ch in enumerate(text):
        t = i / n
        r = _lerp(r1, r2, t)
        g = _lerp(g1, g2, t)
        b = _lerp(b1, b2, t)
        rich_text.append(ch, style=f"bold #{r:02x}{g:02x}{b:02x}")
    return rich_text


# ---------------------------------------------------------------------------
# Progress bar helper
# ---------------------------------------------------------------------------
FULL  = "█"
EMPTY = "░"
BAR_WIDTH = 28


def _progress_bar(fraction: float) -> Text:
    """Unicode block bar, color shifts green → yellow → red as time runs low."""
    fraction = max(0.0, min(1.0, fraction))
    filled = round(fraction * BAR_WIDTH)
    empty  = BAR_WIDTH - filled
    if fraction > 0.5:
        color = _GREEN
    elif fraction > 0.25:
        color = _YELLOW
    else:
        color = _RED
    bar = Text()
    bar.append(FULL * filled, style=f"bold {color}")
    bar.append(EMPTY * empty, style=_SURFACE2)
    return bar


def _format_duration(td: timedelta) -> str:
    total = max(int(td.total_seconds()), 0)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ---------------------------------------------------------------------------
# UI class
# ---------------------------------------------------------------------------

class UI:
    """Rich-based terminal renderer for Focus Guardian."""

    def __init__(self) -> None:
        self.console = Console()

    def _clear(self) -> None:
        """Clear visible screen and scrollback buffer."""
        self.console.file.write("\033[2J\033[3J\033[H")
        self.console.file.flush()

    # -----------------------------------------------------------------------
    # Top-level screens (each clears first)
    # -----------------------------------------------------------------------

    def render_welcome(self) -> None:
        self._clear()

        title = _gradient_text("  Focus Guardian AI  ", _MAUVE, _BLUE)

        tagline = Text(justify="center")
        tagline.append("An AI agent that ", style=_SUBTEXT0)
        tagline.append("protects", style=f"bold {_MAUVE}")
        tagline.append(" your focus, not just tracks it.", style=_SUBTEXT0)

        hint = Text(justify="center")
        hint.append("/start ", style=f"bold {_MAUVE}")
        hint.append('"goal" <minutes>', style=_TEXT)
        hint.append("  ·  ", style=_OVERLAY0)
        hint.append("/help", style=f"bold {_MAUVE}")
        hint.append(" for all commands", style=_SUBTEXT0)

        body = Text(justify="center")
        body.append_text(tagline)
        body.append("\n\n")
        body.append_text(hint)

        self.console.print()
        self.console.print(
            Align.center(
                Panel(
                    Align.center(body),
                    title=title,
                    border_style=_MAUVE,
                    box=box.ROUNDED,
                    padding=(1, 4),
                )
            )
        )
        self.console.print()

    def render_dashboard(self, session, events, context=None, message: str | None = None) -> None:
        self._clear()
        self._print_header()

        if session is None:
            hint = Text(justify="center")
            hint.append("No active session  ·  ", style=_OVERLAY0)
            hint.append('/start "goal" <minutes>', style=f"{_MAUVE}")
            hint.append(" to begin", style=_OVERLAY0)
            self.console.print(Panel(Align.center(hint), border_style=_SURFACE2, box=box.ROUNDED))
        else:
            self.console.print(self._session_panel(session, context))
            if events:
                self.console.print()
                self._render_event_feed(events)

        if message:
            self.console.print()
            self.agent_say(message)

    def render_live_status(self, get_session, get_events) -> None:
        """Live-updating dashboard that ticks every second. Ctrl+C to exit."""
        self.console.print(
            Text("  Live status · Ctrl+C to return to prompt", style=_OVERLAY0)
        )
        try:
            with Live(
                self._build_status_panel(get_session(), get_events()),
                console=self.console,
                refresh_per_second=2,
                transient=False,
            ) as live:
                while True:
                    time.sleep(0.5)
                    live.update(self._build_status_panel(get_session(), get_events()))
        except KeyboardInterrupt:
            pass

    def _build_status_panel(self, session, events) -> Panel:
        if session is None:
            return Panel.fit(
                Align.center(Text('No active session. /start "goal" <minutes> to begin.', style=_OVERLAY0)),
                border_style=_SURFACE2,
                box=box.ROUNDED,
            )
        return self._session_panel(session, None)

    def render_summary(self, session, events) -> None:
        self._clear()
        self._print_header()

        if session.started_at and session.ended_at:
            active_time = (session.ended_at - session.started_at) - session.paused_duration
        else:
            active_time = timedelta(0)

        planned = session.duration
        efficiency = active_time.total_seconds() / max(planned.total_seconds(), 1)
        efficiency = max(0.0, min(1.0, efficiency))

        bar = _progress_bar(efficiency)
        pct = Text(f"  {int(efficiency * 100)}% focus time used", style=_SUBTEXT0)

        bar_line = Text()
        bar_line.append_text(bar)
        bar_line.append_text(pct)

        title_txt = _gradient_text(" Session Complete ", _BLUE, _TEAL)

        lines = Text()
        lines.append("  Goal       ", style=f"bold {_OVERLAY1}")
        lines.append(session.goal, style=_TEXT)
        lines.append("\n  Time Active ", style=f"bold {_OVERLAY1}")
        lines.append(_format_duration(active_time), style=_TEAL)
        lines.append("\n  Offenses   ", style=f"bold {_OVERLAY1}")
        offenses_color = _GREEN if session.offense_count == 0 else (_YELLOW if session.offense_count < 3 else _RED)
        lines.append(str(session.offense_count), style=f"bold {offenses_color}")
        lines.append("\n  Events     ", style=f"bold {_OVERLAY1}")
        lines.append(str(len(events)), style=_SUBTEXT0)
        lines.append("\n\n  ")
        lines.append_text(bar_line)

        self.console.print(
            Panel(
                lines,
                title=title_txt,
                border_style=_BLUE,
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )

    def render_gamestats(self, sessions: list) -> None:
        """Show typing game history — styled to match the Mocha palette."""
        self._clear()
        self._print_header()
        if not sessions:
            self.console.print(
                Panel(
                    Align.center(Text(
                        "No game sessions recorded yet. Play with /pause.",
                        style=_SUBTEXT0,
                    )),
                    border_style=_SURFACE2,
                    box=box.ROUNDED,
                    padding=(1, 2),
                )
            )
            return

        best_wpm = max(s["best_wpm"] for s in sessions)
        best_acc = max(s["best_accuracy"] for s in sessions)
        all_avg_wpm = round(sum(s["avg_wpm"] for s in sessions) / len(sessions), 1)
        all_avg_acc = round(sum(s["avg_accuracy"] for s in sessions) / len(sessions), 1)
        total_rounds = sum(s["rounds"] for s in sessions)

        def wpm_color(v: float) -> str:
            return _GREEN if v >= 60 else _YELLOW if v >= 30 else _RED

        def acc_color(v: float) -> str:
            return _GREEN if v >= 95 else _YELLOW if v >= 80 else _RED

        summary = Text()
        summary.append("Sessions played       ", style=_SUBTEXT1)
        summary.append(f"{len(sessions)}\n", style=_TEXT)
        summary.append("Total rounds          ", style=_SUBTEXT1)
        summary.append(f"{total_rounds}\n", style=_TEXT)
        summary.append("All-time best WPM     ", style=_SUBTEXT1)
        summary.append(f"{best_wpm}\n", style=wpm_color(best_wpm))
        summary.append("All-time best accuracy ", style=_SUBTEXT1)
        summary.append(f"{best_acc}%\n", style=acc_color(best_acc))
        summary.append("Overall avg WPM       ", style=_SUBTEXT1)
        summary.append(f"{all_avg_wpm}\n", style=wpm_color(all_avg_wpm))
        summary.append("Overall avg accuracy  ", style=_SUBTEXT1)
        summary.append(f"{all_avg_acc}%", style=acc_color(all_avg_acc))

        self.console.print(
            Panel(
                summary,
                title=_gradient_text(" Typing Game — All Time ", _MAUVE, _LAVENDER),
                border_style=_MAUVE,
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
        self.console.print()

        table = Table(
            box=box.ROUNDED,
            border_style=_SURFACE2,
            header_style=f"bold {_MAUVE}",
            show_header=True,
            padding=(0, 1),
        )
        table.add_column("#",        style=_SUBTEXT0, no_wrap=True)
        table.add_column("Date",     style=_TEXT, no_wrap=True)
        table.add_column("Rounds",   style=_TEXT)
        table.add_column("Avg WPM",  style=_TEXT)
        table.add_column("Best WPM", style=_TEXT)
        table.add_column("Avg Acc",  style=_TEXT)
        table.add_column("Best Acc", style=_TEXT)
        table.add_column("Time",     style=_TEXT)

        for i, s in enumerate(sessions[-20:], 1):
            table.add_row(
                str(i),
                s["date"],
                str(s["rounds"]),
                Text(str(s["avg_wpm"]),       style=wpm_color(s["avg_wpm"])),
                Text(str(s["best_wpm"]),      style=wpm_color(s["best_wpm"])),
                Text(f"{s['avg_accuracy']}%",  style=acc_color(s["avg_accuracy"])),
                Text(f"{s['best_accuracy']}%", style=acc_color(s["best_accuracy"])),
                f"{s['total_time']}s",
            )

        self.console.print(
            Panel(
                Align.center(table),
                title=_gradient_text(" Session History ", _MAUVE, _LAVENDER),
                border_style=_MAUVE,
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
        self.console.print()

    def render_help(self) -> None:
        self._clear()
        self._print_header()

        table = Table(
            box=box.ROUNDED,
            border_style=_SURFACE2,
            header_style=f"bold {_MAUVE}",
            show_header=True,
            padding=(0, 2),
        )
        table.add_column("Command", style=f"bold {_MAUVE}", no_wrap=True)
        table.add_column("Description", style=_TEXT)

        rows = [
            ('/start ["goal" <min>]', "Begin a focus session  [dim](default: study 60m)[/dim]"),
            ("/status",             "Show current session state"),
            ("/stop",               "End current session"),
            ("/pause",              "Pause session timer (offers typing game)"),
            ("/resume",             "Resume after pause"),
            ("/settings",           "Open interactive settings (mode, grace, blocks, ...)"),
            ("/gamestats",          "Show typing game statistics"),
            ("/help",               "Show this help"),
            ("/clear",              "Clear screen and redraw"),
            ("/quit",               "Exit app"),
        ]
        for i, (cmd, desc) in enumerate(rows):
            # subtle alternating row shade via end_section
            table.add_row(cmd, desc)

        title_txt = _gradient_text(" Commands ", _MAUVE, _LAVENDER)
        self.console.print(
            Panel(
                Align.center(table),
                title=title_txt,
                border_style=_MAUVE,
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
        self.console.print()

    # -----------------------------------------------------------------------
    # Inline messages (no clear — layer on top)
    # -----------------------------------------------------------------------

    def info(self, message: str) -> None:
        t = Text()
        t.append("  ◈ ", style=f"bold {_BLUE}")
        t.append(message, style=_TEXT)
        self.console.print(t)

    def warn(self, message: str) -> None:
        t = Text()
        t.append("  ⚠ ", style=f"bold {_YELLOW}")
        t.append(message, style=_TEXT)
        self.console.print(t)

    def error(self, message: str) -> None:
        t = Text()
        t.append("  ✗ ", style=f"bold {_RED}")
        t.append(message, style=_TEXT)
        self.console.print(t)

    def agent_say(self, message: str) -> None:
        t = Text()
        t.append("  ◆ ", style=f"bold {_MAUVE}")
        t.append(message, style=f"italic {_SUBTEXT1}")
        self.console.print(t)

    # -----------------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------------

    def _print_header(self) -> None:
        title = _gradient_text("Focus Guardian AI", _MAUVE, _BLUE)
        version = Text(" v0.2", style=_OVERLAY0)
        header = Text()
        header.append_text(title)
        header.append_text(version)
        self.console.print(Align.center(header))
        self.console.print(Rule(style=_SURFACE1))
        self.console.print()

    def _session_panel(self, session, context) -> Panel:
        from datetime import datetime
        status_val = session.status.value
        color = _STATUS_COLORS.get(status_val, _TEXT)
        icon  = _STATUS_ICONS.get(status_val, "·")

        # Progress bar (based on time remaining)
        remaining  = session.time_remaining()
        total_secs = max(session.duration.total_seconds(), 1)
        rem_secs   = remaining.total_seconds()
        fraction   = rem_secs / total_secs
        bar = _progress_bar(fraction)

        # Elapsed time
        if session.started_at is not None:
            elapsed = datetime.now() - session.started_at - session.paused_duration
            if status_val == "paused" and session.pause_started_at:
                elapsed = session.pause_started_at - session.started_at - session.paused_duration
            elapsed_str = _format_duration(elapsed)
            started_str = session.started_at.strftime("%H:%M:%S")
        else:
            elapsed_str = "00:00:00"
            started_str = "—"

        paused_str = _format_duration(session.paused_duration)
        planned_str = _format_duration(session.duration)

        # Status badge
        badge = Text()
        badge.append(f" {icon} ", style=f"bold {color}")
        badge.append(status_val.upper(), style=f"bold {color}")

        # Mode pill
        mode_color = {"hardcore": _RED, "normal": _YELLOW, "chill": _TEAL}.get(session.mode.value, _TEXT)
        mode_badge = Text()
        mode_badge.append(f" {session.mode.value} ", style=f"bold {mode_color}")

        # Build content
        body = Text()
        body.append("  ")
        body.append_text(badge)
        body.append("   ")
        body.append_text(mode_badge)
        body.append("\n\n")

        body.append("  Goal      ", style=f"bold {_OVERLAY1}")
        body.append(session.goal, style=_TEXT)
        body.append("\n  Started   ", style=f"bold {_OVERLAY1}")
        body.append(started_str, style=_SUBTEXT1)
        body.append("\n  Elapsed   ", style=f"bold {_OVERLAY1}")
        body.append(elapsed_str, style=f"bold {_TEAL}")
        body.append("\n  Planned   ", style=f"bold {_OVERLAY1}")
        body.append(planned_str, style=_SUBTEXT0)
        body.append("\n  Paused    ", style=f"bold {_OVERLAY1}")
        body.append(paused_str, style=_YELLOW if session.paused_duration.total_seconds() > 0 else _OVERLAY0)
        body.append("\n  Offenses  ", style=f"bold {_OVERLAY1}")
        off_color = _GREEN if session.offense_count == 0 else (_YELLOW if session.offense_count < 3 else _RED)
        body.append(str(session.offense_count), style=f"bold {off_color}")

        if context is not None:
            body.append("\n  Tab       ", style=f"bold {_OVERLAY1}")
            body.append(context.title, style=_SUBTEXT0)

        panel_title = _gradient_text(" Focus Session ", _MAUVE, _BLUE)
        return Panel(
            body,
            title=panel_title,
            border_style=color,
            box=box.ROUNDED,
            padding=(1, 1),
        )

    def _render_event_feed(self, events, limit: int = _EVENT_FEED_LIMIT) -> None:
        table = Table(
            show_header=False,
            box=None,
            padding=(0, 1),
        )
        table.add_column(style=_OVERLAY0, no_wrap=True, width=10)
        table.add_column(width=4, no_wrap=True)
        table.add_column()

        for e in events[-limit:]:
            ts = e.created_at.strftime("%H:%M:%S")
            sym, sym_color = _EVENT_SYMBOLS.get(e.type.value, ("·", _OVERLAY0))
            label = e.type.value.replace("_", " ")
            detail = e.reason or e.url or ""

            sym_text = Text(sym, style=f"bold {sym_color}")

            line = Text()
            line.append(label, style=_SUBTEXT0)
            if detail:
                line.append("  ", style="")
                line.append(detail, style=_OVERLAY0)

            table.add_row(ts, sym_text, line)

        title_txt = Text("  recent activity", style=_OVERLAY0)
        self.console.print(
            Panel(
                table,
                title=title_txt,
                title_align="left",
                border_style=_SURFACE1,
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
