"""Agent orchestrator — session state holder and command dispatcher.

Phase 1 scope: holds the current Session and an in-memory event log.
The CLI invokes its methods; the UI reads its state.

Phase 2 will add the tick loop that polls the Detector, runs the Policy,
and applies Tools on every tick. For now, those deps are not wired.
"""

from __future__ import annotations

from app.models import Event, EventType
from app.session import Session, SessionMode


class Orchestrator:
    """Coordinates session lifecycle and events. Phase 1: in-memory only."""

    def __init__(self, ui) -> None:
        self.ui = ui
        self.session: Session | None = None
        self.events: list[Event] = []

    # --- session lifecycle ---

    def start_session(self, goal: str, duration_minutes: int, mode: SessionMode) -> Session:
        if self.session is not None and self.session.is_active():
            raise RuntimeError("a session is already active - /stop it first")
        self.session = Session(goal=goal, duration_minutes=duration_minutes, mode=mode)
        self.session.start()
        self._log(EventType.SESSION_STARTED, reason=f'"{goal}" for {duration_minutes}m ({mode.value})')
        return self.session

    def stop_session(self) -> Session:
        self._require_session()
        assert self.session is not None
        self.session.stop()
        self._log(EventType.SESSION_STOPPED)
        return self.session

    def pause_session(self) -> None:
        self._require_session()
        assert self.session is not None
        self.session.pause()
        self._log(EventType.SESSION_PAUSED)

    def resume_session(self) -> None:
        self._require_session()
        assert self.session is not None
        self.session.resume()
        self._log(EventType.SESSION_RESUMED)

    def set_mode(self, mode: SessionMode) -> None:
        self._require_session()
        assert self.session is not None
        self.session.mode = mode
        self._log(EventType.MODE_CHANGED, reason=f"mode set to {mode.value}")

    # --- state queries ---

    def recent_events(self, limit: int = 20) -> list[Event]:
        return self.events[-limit:]

    # --- internals ---

    def _require_session(self) -> None:
        if self.session is None:
            raise RuntimeError("no session - start one with /start")

    def _log(self, event_type: EventType, **fields) -> None:
        session_id = self.session.id if self.session is not None else 0
        self.events.append(Event(session_id=session_id, type=event_type, **fields))

    # TODO(phase-2): _tick_loop + _tick — integrate detector + policy + tools
