"""Pop-up distraction notification — runs in a new terminal window.

Spawned by tools.py whenever a soft-mode warning fires.
Accepts the warning message as a single CLI argument.
Auto-closes after a 5-second countdown.
"""

from __future__ import annotations

import sys
import time

from rich.console import Console
from rich.panel import Panel
from rich.text import Text


_AUTO_CLOSE_SECONDS = 5


def main() -> None:
    message = sys.argv[1] if len(sys.argv) > 1 else "You seem distracted — stay focused!"
    console = Console()

    console.print()
    console.print(Panel(
        Text(message, justify="center", style="bold yellow"),
        title="[bold red] Focus Guardian [/bold red]",
        subtitle="[dim]soft mode warning[/dim]",
        border_style="red",
        padding=(1, 4),
    ))
    console.print()

    for i in range(_AUTO_CLOSE_SECONDS, 0, -1):
        console.print(f"  [dim]Closing in {i}s...[/dim]", end="\r")
        time.sleep(1)

    console.print()


if __name__ == "__main__":
    main()
