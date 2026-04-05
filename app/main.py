"""Entry point.

Wires UI + Orchestrator + CLI and starts the REPL.

Phase 1: no storage, detector, policy, tools, or AI yet — just the
session lifecycle loop.
"""

from __future__ import annotations

from app.cli import CLI
from app.orchestrator import Orchestrator
from app.ui import UI


def main() -> None:
    ui = UI()
    orchestrator = Orchestrator(ui=ui)
    cli = CLI(orchestrator=orchestrator, ui=ui)
    cli.run()


if __name__ == "__main__":
    main()
