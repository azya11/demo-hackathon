"""Seed a demo session for rehearsals and screenshots.

Usage:
    python -m scripts.demo_seed

Creates a fake session with a plausible event timeline so the UI has
something to render without running the full detector loop.
"""

from __future__ import annotations


def seed() -> None:
    # TODO: open Storage(data/sessions.db)
    # TODO: insert session: goal="Study OS for 60 min", mode=strict
    # TODO: insert events: tab_observed (canvas), tab_observed (youtube lecture),
    #       warning_issued, tab_closed
    raise NotImplementedError


if __name__ == "__main__":
    seed()
