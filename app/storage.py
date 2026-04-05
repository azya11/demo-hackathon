"""Persistence layer — SQLite.

Tables:
    sessions(id, goal, mode, started_at, ended_at, duration_min, status)
    events(id, session_id, type, url, domain, action, reason, created_at)

Keep queries here; other modules never touch SQL directly.
"""

from __future__ import annotations

from pathlib import Path


class Storage:
    """SQLite-backed persistence for sessions and events."""

    def __init__(self, db_path: Path) -> None:
        # TODO: open connection, create tables if missing
        raise NotImplementedError

    # --- schema ---

    def _ensure_schema(self) -> None: raise NotImplementedError

    # --- sessions ---

    def save_session(self, session) -> int: raise NotImplementedError
    def update_session(self, session) -> None: raise NotImplementedError
    def get_active_session(self): raise NotImplementedError

    # --- events ---

    def log_event(self, event) -> None: raise NotImplementedError
    def recent_events(self, session_id: int, limit: int = 20) -> list: raise NotImplementedError

    # --- analytics ---

    def session_summary(self, session_id: int) -> dict:
        """Return {focus_time, distractions_prevented, violations, longest_block}."""
        raise NotImplementedError
