"""Terminal UI layer — Focus Guardian AI v0.2

Uses the active theme from app.themes for all colors.
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

import app.themes as _themes

_STATUS_ICONS = {
    "active":    "▶",
    "paused":    "⏸",
    "idle":      "◌",
    "stopped":   "■",
    "completed": "✓",
}

_EVENT_FEED_LIMIT = 7


def _t():
    """Shorthand: return the currently active theme."""
    return _themes.current

# ---------------------------------------------------------------------------
# Gradient + progress helpers
# ---------------------------------------------------------------------------

def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)


def _gradient_text(text: str, start_hex: str, end_hex: str) -> Text:
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


def _progress_bar(fraction: float) -> Text:
    fraction = max(0.0, min(1.0, fraction))
    filled = round(fraction * 28)
    empty  = 28 - filled
    th = _t()
    color = th.active if fraction > 0.5 else (th.warning if fraction > 0.25 else th.error)
    bar = Text()
    bar.append("█" * filled, style=f"bold {color}")
    bar.append("░" * empty,  style=th.surface)
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

        title = _gradient_text("  Focus Guardian AI  ", _t().accent, _t().complete)

        tagline = Text(justify="center")
        tagline.append("An AI agent that ", style=_t().subtext)
        tagline.append("protects", style=f"bold {_t().accent}")
        tagline.append(" your focus, not just tracks it.", style=_t().subtext)

        hint = Text(justify="center")
        hint.append("/start ", style=f"bold {_t().accent}")
        hint.append('"goal" <minutes>', style=_t().text)
        hint.append("  ·  ", style=_t().dim)
        hint.append("/help", style=f"bold {_t().accent}")
        hint.append(" for all commands", style=_t().subtext)

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
                    border_style=_t().accent,
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
            hint.append("No active session  ·  ", style=_t().dim)
            hint.append('/start "goal" <minutes>', style=_t().accent)
            hint.append(" to begin", style=_t().dim)
            self.console.print(Panel(Align.center(hint), border_style=_t().surface, box=box.ROUNDED))
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
            Text("  Live status · Ctrl+C to return to prompt", style=_t().dim)
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
                Align.center(Text('No active session. /start "goal" <minutes> to begin.', style=_t().dim)),
                border_style=_t().surface,
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
        pct = Text(f"  {int(efficiency * 100)}% focus time used", style=_t().subtext)

        bar_line = Text()
        bar_line.append_text(bar)
        bar_line.append_text(pct)

        title_txt = _gradient_text(" Session Complete ", _t().complete, _t().info)

        lines = Text()
        lines.append("  Goal       ", style=f"bold {_t().dim}")
        lines.append(session.goal, style=_t().text)
        lines.append("\n  Time Active ", style=f"bold {_t().dim}")
        lines.append(_format_duration(active_time), style=_t().info)
        lines.append("\n  Offenses   ", style=f"bold {_t().dim}")
        offenses_color = _t().active if session.offense_count == 0 else (_t().warning if session.offense_count < 3 else _t().error)
        lines.append(str(session.offense_count), style=f"bold {offenses_color}")
        lines.append("\n  Events     ", style=f"bold {_t().dim}")
        lines.append(str(len(events)), style=_t().subtext)
        lines.append("\n\n  ")
        lines.append_text(bar_line)

        self.console.print(
            Panel(
                lines,
                title=title_txt,
                border_style=_t().complete,
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
                        style=_t().subtext,
                    )),
                    border_style=_t().surface,
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
            return _t().active if v >= 60 else _t().warning if v >= 30 else _t().error

        def acc_color(v: float) -> str:
            return _t().active if v >= 95 else _t().warning if v >= 80 else _t().error

        summary = Text()
        summary.append("Sessions played       ", style=_t().subtext)
        summary.append(f"{len(sessions)}\n", style=_t().text)
        summary.append("Total rounds          ", style=_t().subtext)
        summary.append(f"{total_rounds}\n", style=_t().text)
        summary.append("All-time best WPM     ", style=_t().subtext)
        summary.append(f"{best_wpm}\n", style=wpm_color(best_wpm))
        summary.append("All-time best accuracy ", style=_t().subtext)
        summary.append(f"{best_acc}%\n", style=acc_color(best_acc))
        summary.append("Overall avg WPM       ", style=_t().subtext)
        summary.append(f"{all_avg_wpm}\n", style=wpm_color(all_avg_wpm))
        summary.append("Overall avg accuracy  ", style=_t().subtext)
        summary.append(f"{all_avg_acc}%", style=acc_color(all_avg_acc))

        self.console.print(
            Panel(
                summary,
                title=_gradient_text(" Typing Game — All Time ", _t().accent, _t().accent2),
                border_style=_t().accent,
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
        self.console.print()

        table = Table(
            box=box.ROUNDED,
            border_style=_t().surface,
            header_style=f"bold {_t().accent}",
            show_header=True,
            padding=(0, 1),
        )
        table.add_column("#",        style=_t().subtext, no_wrap=True)
        table.add_column("Date",     style=_t().text, no_wrap=True)
        table.add_column("Rounds",   style=_t().text)
        table.add_column("Avg WPM",  style=_t().text)
        table.add_column("Best WPM", style=_t().text)
        table.add_column("Avg Acc",  style=_t().text)
        table.add_column("Best Acc", style=_t().text)
        table.add_column("Time",     style=_t().text)

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
                title=_gradient_text(" Session History ", _t().accent, _t().accent2),
                border_style=_t().accent,
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
            border_style=_t().surface,
            header_style=f"bold {_t().accent}",
            show_header=True,
            padding=(0, 2),
        )
        table.add_column("Command", style=f"bold {_t().accent}", no_wrap=True)
        table.add_column("Description", style=_t().text)

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

        title_txt = _gradient_text(" Commands ", _t().accent, _t().accent2)
        self.console.print(
            Panel(
                Align.center(table),
                title=title_txt,
                border_style=_t().accent,
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
        t.append("  ◈ ", style=f"bold {_t().complete}")
        t.append(message, style=_t().text)
        self.console.print(t)

    def warn(self, message: str) -> None:
        t = Text()
        t.append("  ⚠ ", style=f"bold {_t().warning}")
        t.append(message, style=_t().text)
        self.console.print(t)

    def error(self, message: str) -> None:
        t = Text()
        t.append("  ✗ ", style=f"bold {_t().error}")
        t.append(message, style=_t().text)
        self.console.print(t)

    def agent_say(self, message: str) -> None:
        t = Text()
        t.append("  ◆ ", style=f"bold {_t().accent}")
        t.append(message, style=f"italic {_t().subtext}")
        self.console.print(t)

    # -----------------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------------

    def _print_header(self) -> None:
        title = _gradient_text("Focus Guardian AI", _t().accent, _t().complete)
        version = Text(" v0.2", style=_t().dim)
        header = Text()
        header.append_text(title)
        header.append_text(version)
        self.console.print(Align.center(header))
        self.console.print(Rule(style=_t().surface))
        self.console.print()

    def _session_panel(self, session, context) -> Panel:
        status_val = session.status.value
        status_colors = {'active': _t().active, 'paused': _t().warning, 'idle': _t().dim, 'stopped': _t().error, 'completed': _t().complete}
        color = status_colors.get(status_val, _t().text)
        icon  = _STATUS_ICONS.get(status_val, "·")

        # Status badge
        badge = Text()
        badge.append(f" {icon} ", style=f"bold {color}")
        badge.append(status_val.upper(), style=f"bold {color}")

        # Mode pill
        mode_color = {"hardcore": _t().error, "normal": _t().warning, "chill": _t().info, "strict": _t().error, "soft": _t().info}.get(session.mode.value, _t().text)
        mode_badge = Text()
        mode_badge.append(f" {session.mode.value} ", style=f"bold {mode_color}")

        # Offense rating
        off_color = _t().active if session.offense_count == 0 else (_t().warning if session.offense_count < 3 else _t().error)
        off_label = "clean" if session.offense_count == 0 else ("watch it" if session.offense_count < 3 else "struggling")

        # Session number (id)
        session_num = f"#{session.id}"

        # Pause count
        times_paused = int(session.paused_duration.total_seconds() > 0)  # basic: paused at all?

        body = Text()
        body.append("  ")
        body.append_text(badge)
        body.append("   ")
        body.append_text(mode_badge)
        body.append("\n\n")

        body.append("  Goal        ", style=f"bold {_t().dim}")
        body.append(session.goal, style=f"bold {_t().text}")
        body.append("\n  Session     ", style=f"bold {_t().dim}")
        body.append(session_num, style=_t().subtext)
        body.append("\n  Offenses    ", style=f"bold {_t().dim}")
        body.append(f"{session.offense_count}  ", style=f"bold {off_color}")
        body.append(off_label, style=off_color)
        body.append("\n  Theme       ", style=f"bold {_t().dim}")
        import app.themes as _themes
        body.append(_themes.current.name, style=_t().accent)
        body.append("\n  Enforcement ", style=f"bold {_t().dim}")
        body.append(session.mode.value, style=f"bold {mode_color}")

        if context is not None:
            body.append("\n  Active tab  ", style=f"bold {_t().dim}")
            body.append(context.title, style=_t().subtext)

        panel_title = _gradient_text(" Focus Session ", _t().accent, _t().complete)
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
        table.add_column(style=_t().dim, no_wrap=True, width=10)
        table.add_column(width=4, no_wrap=True)
        table.add_column()

        for e in events[-limit:]:
            ts = e.created_at.strftime("%H:%M:%S")
            event_symbols = {
            "session_started":   ("▶", _t().active),
            "session_stopped":   ("■", _t().error),
            "session_paused":    ("⏸", _t().warning),
            "session_resumed":   ("▶", _t().info),
            "session_completed": ("✓", _t().complete),
            "warning_issued":    ("⚠", _t().warning),
            "tab_closed":        ("✗", _t().error),
            "tab_observed":      ("◈", _t().dim),
            "ai_classified":     ("◆", _t().accent),
            "mode_changed":      ("◎", _t().accent2),
            "time_adjusted":     ("⏱", _t().info),
        }
            sym, sym_color = event_symbols.get(e.type.value, ("·", _t().dim))
            label = e.type.value.replace("_", " ")
            detail = e.reason or e.url or ""

            sym_text = Text(sym, style=f"bold {sym_color}")

            line = Text()
            line.append(label, style=_t().subtext)
            if detail:
                line.append("  ", style="")
                line.append(detail, style=_t().dim)

            table.add_row(ts, sym_text, line)

        title_txt = Text("  recent activity", style=_t().dim)
        self.console.print(
            Panel(
                table,
                title=title_txt,
                title_align="left",
                border_style=_t().surface,
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
