"""Agent tool layer.

Every action the agent can take on the world. Kept separate so we can
(a) log every invocation uniformly, (b) swap the browser backend later,
(c) expose these as function-calling tools to Gemini if we want.
"""

from __future__ import annotations


class Tools:
    """The agent's action surface."""

    def __init__(self, detector, ui, storage) -> None:
        # TODO: store deps — needs detector to reach the active page
        raise NotImplementedError

    # --- primary actions ---

    def warn_user(self, message: str) -> None:
        """Display warning in terminal UI."""
        raise NotImplementedError

    def close_active_tab(self) -> bool:
        """Close the tab triggering the violation. Returns success."""
        raise NotImplementedError

    def open_url(self, url: str) -> None:
        """Open a new tab (e.g., redirect to study resource)."""
        raise NotImplementedError

    def log_event(self, event_type: str, metadata: dict) -> None:
        """Record an event to storage."""
        raise NotImplementedError

    # --- dispatcher ---

    def apply(self, decision, context) -> None:
        """Execute whatever the Decision calls for."""
        # TODO: match decision.action → warn / close / allow noop
        # TODO: always log_event
        raise NotImplementedError
