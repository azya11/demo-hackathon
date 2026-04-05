"""Shared data models.

Kept as plain dataclasses to avoid circular imports. Each module that
produces one of these owns its logic; this file only defines shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class EventType(str, Enum):
    SESSION_STARTED = "session_started"
    SESSION_STOPPED = "session_stopped"
    SESSION_PAUSED = "session_paused"
    SESSION_RESUMED = "session_resumed"
    SESSION_COMPLETED = "session_completed"
    TAB_OBSERVED = "tab_observed"
    WARNING_ISSUED = "warning_issued"
    TAB_CLOSED = "tab_closed"
    AI_CLASSIFIED = "ai_classified"
    MODE_CHANGED = "mode_changed"
    PROCESS_KILLED = "process_killed"
    PROCESS_OBSERVED = "process_observed"


@dataclass
class Event:
    """A single logged event in a session timeline."""
    session_id: int
    type: EventType
    url: str | None = None
    domain: str | None = None
    action: str | None = None
    reason: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
