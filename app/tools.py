"""Agent tool layer.

Every action the agent can take on the world. Kept separate so we can
(a) log every invocation uniformly, (b) swap the browser backend later.
"""

from __future__ import annotations

from app.models import Event, EventType
from app.policy import Action


class Tools:
    """The agent's action surface."""

    def __init__(self, ui, event_log: list, detector=None) -> None:
        self.ui = ui
        self.events = event_log
        self.detector = detector

    # --- primary actions ---

    def warn_user(self, message: str, session_id: int, url: str = "", domain: str = "") -> None:
        """Push-notify the user in the terminal (soft-mode warning)."""
        self.ui.warn(f"[focus] {message}")
        self._log(EventType.WARNING_ISSUED, session_id, url=url, domain=domain, reason=message)

    def close_tab(self, context, session_id: int, reason: str) -> bool:
        """Close a specific tab. Returns success."""
        # Attach mode: close via CDP HTTP.
        target_id = getattr(context, "target_id", None)
        if target_id and self.detector is not None:
            ok = self.detector.close_tab_cdp(target_id)
            if not ok:
                return False
            self.ui.warn(f"[focus] closed {context.domain} — {reason}")
            self._log(
                EventType.TAB_CLOSED, session_id,
                url=context.url, domain=context.domain,
                action=Action.BLOCK.value, reason=reason,
            )
            return True
        # Launch mode: use the Playwright Page.
        page = getattr(context, "page", None)
        if page is None or isinstance(page, str):
            return False
        try:
            browser_ctx = page.context
            if len(browser_ctx.pages) <= 1:
                try:
                    browser_ctx.new_page()
                except Exception:
                    pass
            page.close()
        except Exception:
            return False
        self.ui.warn(f"[focus] closed {context.domain} — {reason}")
        self._log(
            EventType.TAB_CLOSED,
            session_id,
            url=context.url,
            domain=context.domain,
            action=Action.BLOCK.value,
            reason=reason,
        )
        return True

    # --- dispatcher ---

    def apply(self, decision, context, session) -> None:
        """Execute whatever the Decision calls for."""
        if decision.action == Action.ALLOW:
            return
        if decision.action == Action.WARN:
            session.record_offense()
            self.warn_user(decision.reason, session.id, context.url, context.domain)
            return
        if decision.action == Action.BLOCK:
            session.record_offense()
            self.close_tab(context, session.id, decision.reason)
            return

    # --- internals ---

    def _log(self, event_type: EventType, session_id: int, **fields) -> None:
        self.events.append(Event(session_id=session_id, type=event_type, **fields))
