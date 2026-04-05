"""Session lifecycle.

A Session holds the active focus goal, timer, mode, and offense counters.
Sessions are created by the orchestrator and persisted via storage.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from itertools import count


class SessionMode(str, Enum):
    SOFT = "soft"      # warn only
    STRICT = "strict"  # warn + close tab


class SessionStatus(str, Enum):
    IDLE = "idle"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED = "stopped"


class Session:
    """A single focus session (created via /start, ended via /stop)."""

    _id_counter = count(1)

    def __init__(self, goal: str, duration_minutes: int, mode: SessionMode) -> None:
        self.id: int = next(Session._id_counter)
        self.goal: str = goal
        self.duration: timedelta = timedelta(minutes=duration_minutes)
        self.mode: SessionMode = mode
        self.status: SessionStatus = SessionStatus.IDLE
        self.started_at: datetime | None = None
        self.ended_at: datetime | None = None
        self.pause_started_at: datetime | None = None
        self.paused_duration: timedelta = timedelta(0)
        self.offense_count: int = 0
        self.last_warning_at: datetime | None = None

    # --- state transitions ---

    def start(self) -> None:
        if self.status != SessionStatus.IDLE:
            raise RuntimeError(f"cannot start session in status {self.status.value}")
        self.status = SessionStatus.ACTIVE
        self.started_at = datetime.now()

    def pause(self) -> None:
        if self.status != SessionStatus.ACTIVE:
            raise RuntimeError(f"cannot pause session in status {self.status.value}")
        self.status = SessionStatus.PAUSED
        self.pause_started_at = datetime.now()

    def resume(self) -> None:
        if self.status != SessionStatus.PAUSED:
            raise RuntimeError(f"cannot resume session in status {self.status.value}")
        if self.pause_started_at is not None:
            self.paused_duration += datetime.now() - self.pause_started_at
            self.pause_started_at = None
        self.status = SessionStatus.ACTIVE

    def stop(self) -> None:
        if self.status in (SessionStatus.STOPPED, SessionStatus.COMPLETED):
            return
        # Finalize any in-flight pause so paused_duration is accurate.
        if self.status == SessionStatus.PAUSED and self.pause_started_at is not None:
            self.paused_duration += datetime.now() - self.pause_started_at
            self.pause_started_at = None
        self.status = SessionStatus.STOPPED
        self.ended_at = datetime.now()

    # --- queries ---

    def is_active(self) -> bool:
        return self.status == SessionStatus.ACTIVE

    def time_remaining(self) -> timedelta:
        if self.started_at is None:
            return self.duration
        elapsed = datetime.now() - self.started_at - self.paused_duration
        # Subtract the ongoing pause so the timer freezes while paused.
        if self.status == SessionStatus.PAUSED and self.pause_started_at is not None:
            elapsed -= datetime.now() - self.pause_started_at
        remaining = self.duration - elapsed
        return max(remaining, timedelta(0))

    def is_expired(self) -> bool:
        return self.time_remaining() <= timedelta(0)

    def adjust_time(self, minutes: int) -> None:
        """Add or remove minutes from the session duration. minutes can be negative."""
        self.duration += timedelta(minutes=minutes)
        if self.duration < timedelta(0):
            self.duration = timedelta(0)

    # --- offense tracking ---

    def record_offense(self) -> int:
        """Increment counter, return new count. Used by policy for escalation."""
        self.offense_count += 1
        self.last_warning_at = datetime.now()
        return self.offense_count
