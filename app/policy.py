"""Policy engine — rules-first decision maker.

Receives a Context snapshot and active Session, returns a Decision.
Hard rules run first (explicit blocklist/allowlist). If the page is
ambiguous, the decision is flagged `needs_ai=True` and the orchestrator
hands off to ai.py for classification.

Escalation ladder (strict mode):
    1st offense   → WARN
    2nd offense   → WARN + short countdown
    3rd+ offense  → BLOCK (close tab)
"""

from __future__ import annotations

from enum import Enum


class Action(str, Enum):
    ALLOW = "allow"
    WARN = "warn"
    BLOCK = "block"


class Decision:
    """Policy output: action + reason + escalation metadata."""

    def __init__(
        self,
        action: Action,
        reason: str,
        confidence: float = 1.0,
        needs_ai: bool = False,
    ) -> None:
        # TODO: store fields
        raise NotImplementedError


class Policy:
    """Decides what to do about the current browser context."""

    def __init__(self, blocklist: list[str], allowlist: list[str]) -> None:
        # TODO: normalize domains, store
        raise NotImplementedError

    def decide(self, context, session) -> Decision:
        """Main entry: apply rules, return Decision."""
        # TODO: if no session or paused → ALLOW
        # TODO: if domain in allowlist → ALLOW
        # TODO: if domain in blocklist → escalate(session) → WARN/BLOCK
        # TODO: else → Decision(needs_ai=True)
        raise NotImplementedError

    def _escalate(self, session) -> Action:
        """Map offense count → WARN or BLOCK based on mode."""
        raise NotImplementedError

    # --- dynamic list management ---

    def add_block(self, domain: str) -> None: raise NotImplementedError
    def add_allow(self, domain: str) -> None: raise NotImplementedError
