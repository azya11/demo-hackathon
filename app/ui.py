"""Terminal UI layer.

Uses Rich to render the dashboard: session header, live state, event feed,
agent decisions. Keeps all presentation logic here — other modules should
never print() directly.

Each top-level screen clears the console first so the terminal only shows
the current frame. Inline messages (info/warn/error) never clear — they
layer on top of the last screen until the next command triggers a redraw.
"""

from __future__ import annotations

from datetime import timedelta

from rich.console import Console
from rich.panel import Panel
from rich.table import Table


_STATUS_COLORS = {
    "active": "green",
    "paused": "yellow",
    "idle": "dim",
    "stopped": "red",
    "completed": "blue",
}

_EVENT_COLORS = {
    "session_started": "green",
    "session_resumed": "green",
    "session_paused": "yellow",
    "session_stopped": "red",
    "session_completed": "blue",
    "warning_issued": "yellow",
    "tab_closed": "red",
    "tab_observed": "dim",
    "ai_classified": "magenta",
    "mode_changed": "medium_purple1",
}

_EVENT_FEED_LIMIT = 7


def _format_duration(td: timedelta) -> str:
    total = max(int(td.total_seconds()), 0)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class UI:
    """Rich-based terminal renderer for Focus Guardian."""

    def __init__(self) -> None:
        self.console = Console()

    # --- top-level screens (each clears first) ---

    def render_welcome(self) -> None:
        self.console.clear()
        body = (
            "An agent that protects your focus, not just tracks it.\n"
            'Type [medium_purple1]/help[/medium_purple1] for commands, [medium_purple1]/start "goal" 60[/medium_purple1] to begin.'
        )
        self.console.print(Panel.fit(body, title="[bold medium_purple1]Focus Guardian AI v0.1[/]", border_style="medium_purple1"))

    def render_dashboard(self, session, events, context=None, message: str | None = None) -> None:
        """Clear + show the full dashboard; optionally append an agent message."""
        self.console.clear()
        self._print_header()

        if session is None:
            self.console.print(Panel.fit(
                'No active session. Type [medium_purple1]/start "goal" <minutes>[/medium_purple1] to begin.',
                border_style="dim",
            ))
        else:
            color = _STATUS_COLORS.get(session.status.value, "white")
            lines = [
                f"[bold]Session:[/bold] [{color}]{session.status.value.upper()}[/{color}]",
                f"[bold]Goal:[/bold] {session.goal}",
                f"[bold]Time left:[/bold] {_format_duration(session.time_remaining())}",
                f"[bold]Mode:[/bold] {session.mode.value}",
                f"[bold]Offenses:[/bold] {session.offense_count}",
            ]
            if context is not None:
                lines.append(f"[bold]Current tab:[/bold] {context.title}")
            self.console.print(Panel("\n".join(lines), title="Focus Guardian", border_style=color))
            if events:
                self._render_event_feed(events)

        if message:
            self.console.print()
            self.agent_say(message)

    def render_summary(self, session, events) -> None:
        """Post-session analytics."""
        self.console.clear()
        self._print_header()
        if session.started_at and session.ended_at:
            active_time = (session.ended_at - session.started_at) - session.paused_duration
        else:
            active_time = timedelta(0)
        body = (
            f"[bold]Goal:[/bold] {session.goal}\n"
            f"[bold]Time active:[/bold] {_format_duration(active_time)}\n"
            f"[bold]Offenses:[/bold] {session.offense_count}\n"
            f"[bold]Events logged:[/bold] {len(events)}"
        )
        self.console.print(Panel(body, title="Session Summary", border_style="blue"))

    def render_gamestats(self, sessions: list) -> None:
        self.console.clear()
        self._print_header()
        if not sessions:
            self.console.print(Panel.fit(
                "No game sessions recorded yet. Play the typing game with [medium_purple1]/pause[/medium_purple1].",
                border_style="dim",
            ))
            return

        # All-time bests
        best_wpm = max(s["best_wpm"] for s in sessions)
        best_acc = max(s["best_accuracy"] for s in sessions)
        all_avg_wpm = round(sum(s["avg_wpm"] for s in sessions) / len(sessions), 1)
        all_avg_acc = round(sum(s["avg_accuracy"] for s in sessions) / len(sessions), 1)
        total_rounds = sum(s["rounds"] for s in sessions)

        def wpm_color(v: float) -> str:
            return "green" if v >= 60 else "yellow" if v >= 30 else "red"

        def acc_color(v: float) -> str:
            return "green" if v >= 95 else "yellow" if v >= 80 else "red"

        summary = (
            f"[bold]Sessions played:[/bold] {len(sessions)}\n"
            f"[bold]Total rounds:[/bold]    {total_rounds}\n"
            f"[bold]All-time best WPM:[/bold]      [{wpm_color(best_wpm)}]{best_wpm}[/]\n"
            f"[bold]All-time best accuracy:[/bold] [{acc_color(best_acc)}]{best_acc}%[/]\n"
            f"[bold]Overall avg WPM:[/bold]        [{wpm_color(all_avg_wpm)}]{all_avg_wpm}[/]\n"
            f"[bold]Overall avg accuracy:[/bold]   [{acc_color(all_avg_acc)}]{all_avg_acc}%[/]"
        )
        self.console.print(Panel(summary, title="[bold medium_purple1]Typing Game - All Time[/bold medium_purple1]", border_style="medium_purple1"))
        self.console.print()

        # Per-session history table
        table = Table(title="Session History", header_style="bold medium_purple1", border_style="dim")
        table.add_column("#", style="dim", no_wrap=True)
        table.add_column("Date", no_wrap=True)
        table.add_column("Rounds")
        table.add_column("Avg WPM")
        table.add_column("Best WPM")
        table.add_column("Avg Acc")
        table.add_column("Best Acc")
        table.add_column("Time")

        for i, s in enumerate(sessions[-20:], 1):
            table.add_row(
                str(i),
                s["date"],
                str(s["rounds"]),
                f"[{wpm_color(s['avg_wpm'])}]{s['avg_wpm']}[/]",
                f"[{wpm_color(s['best_wpm'])}]{s['best_wpm']}[/]",
                f"[{acc_color(s['avg_accuracy'])}]{s['avg_accuracy']}%[/]",
                f"[{acc_color(s['best_accuracy'])}]{s['best_accuracy']}%[/]",
                f"{s['total_time']}s",
            )
        self.console.print(table)

    def render_help(self) -> None:
        self.console.clear()
        self._print_header()
        table = Table(title="Commands", header_style="bold medium_purple1", border_style="dim")
        table.add_column("Command", style="medium_purple1", no_wrap=True)
        table.add_column("Description")
        rows = [
            ('/start "goal" <min>', "Begin a focus session"),
            ("/status", "Show current session state"),
            ("/stop", "End current session"),
            ("/pause", "Pause session timer (offers typing game)"),
            ("/resume", "Resume after pause"),
            ("/mode strict|soft", "Switch enforcement mode"),
            ("/gamestats", "Show typing game statistics"),
            ("/help", "Show this help"),
            ("/quit", "Exit app"),
        ]
        for cmd, desc in rows:
            table.add_row(cmd, desc)
        self.console.print(table)

    # --- inline messages (no clear — layer on last screen) ---

    def info(self, message: str) -> None:
        self.console.print(f"[medium_purple1]i[/medium_purple1] {message}")

    def warn(self, message: str) -> None:
        self.console.print(f"[yellow]![/yellow] {message}")

    def error(self, message: str) -> None:
        self.console.print(f"[red]x[/red] {message}")

    def agent_say(self, message: str) -> None:
        """Styled message from the agent itself."""
        self.console.print(f"[magenta]>[/magenta] [italic]{message}[/italic]")

    # --- internals ---

    def _print_header(self) -> None:
        self.console.print("[bold medium_purple1]Focus Guardian AI[/bold medium_purple1] [dim]v0.1[/dim]")
        self.console.print()

    def _render_event_feed(self, events, limit: int = _EVENT_FEED_LIMIT) -> None:
        table = Table(show_header=False, box=None, padding=(0, 1), title="Recent activity", title_style="dim")
        table.add_column(style="dim", no_wrap=True)
        table.add_column()
        for e in events[-limit:]:
            ts = e.created_at.strftime("%H:%M:%S")
            color = _EVENT_COLORS.get(e.type.value, "white")
            label = e.type.value.replace("_", " ")
            detail = e.reason or e.url or ""
            line = f"[{color}]*[/{color}] {label}" + (f" - {detail}" if detail else "")
            table.add_row(ts, line)
        self.console.print(table)
