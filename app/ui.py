"""Terminal UI layer.

Uses Rich to render the dashboard: session header, live state, event feed,
agent decisions. Keeps all presentation logic here — other modules should
never print() directly.
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
}


def _format_duration(td: timedelta) -> str:
    total = max(int(td.total_seconds()), 0)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class UI:
    """Rich-based terminal renderer for Focus Guardian."""

    def __init__(self) -> None:
        self.console = Console()

    # --- top-level screens ---

    def render_welcome(self) -> None:
        body = (
            "An agent that protects your focus, not just tracks it.\n"
            'Type [cyan]/help[/cyan] for commands, [cyan]/start "goal" 60[/cyan] to begin.'
        )
        self.console.print(Panel.fit(body, title="[bold cyan]Focus Guardian AI v0.1[/]", border_style="cyan"))

    def render_dashboard(self, session, events, context=None) -> None:
        """Redraw the full dashboard with current session + context."""
        if session is None:
            self.console.print(Panel.fit(
                'No active session. Type [cyan]/start "goal" <minutes>[/cyan] to begin.',
                title="Focus Guardian",
                border_style="dim",
            ))
            return

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
            self.render_event_feed(events)

    def render_event_feed(self, events, limit: int = 10) -> None:
        """Last N events with colored severity."""
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

    def render_summary(self, session, events) -> None:
        """Post-session analytics."""
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

    def render_help(self) -> None:
        table = Table(title="Commands", header_style="bold cyan", border_style="dim")
        table.add_column("Command", style="cyan", no_wrap=True)
        table.add_column("Description")
        rows = [
            ('/start "goal" <min>', "Begin a focus session"),
            ("/status", "Show current session state"),
            ("/stop", "End current session"),
            ("/pause", "Pause session timer"),
            ("/resume", "Resume after pause"),
            ("/mode strict|soft", "Switch enforcement mode"),
            ("/help", "Show this help"),
            ("/quit", "Exit app"),
        ]
        for cmd, desc in rows:
            table.add_row(cmd, desc)
        self.console.print(table)

    # --- inline messages ---

    def info(self, message: str) -> None:
        self.console.print(f"[cyan]i[/cyan] {message}")

    def warn(self, message: str) -> None:
        self.console.print(f"[yellow]![/yellow] {message}")

    def error(self, message: str) -> None:
        self.console.print(f"[red]x[/red] {message}")

    def agent_say(self, message: str) -> None:
        """Styled message from the agent itself."""
        self.console.print(f"[magenta]>[/magenta] [italic]{message}[/italic]")
