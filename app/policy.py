"""Policy engine — rules-first decision maker.

Receives a Context snapshot and active Session, returns a Decision.
Hard rules run first (explicit blocklist/allowlist). If the page is
ambiguous, the decision is flagged `needs_ai=True` and the orchestrator
hands off to ai.py for classification.

Hardcore mode: any blocklist match → BLOCK immediately (close tab).
Normal mode: any blocklist match → BLOCK with grace period in tools layer.
Chill mode: any blocklist match → WARN (terminal push notification).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import Lock


class Action(str, Enum):
    ALLOW = "allow"
    WARN = "warn"
    BLOCK = "block"


@dataclass
class Decision:
    """Policy output: action + reason + escalation metadata."""
    action: Action
    reason: str
    confidence: float = 1.0
    needs_ai: bool = False


def _normalize(domain: str) -> str:
    d = (domain or "").strip().lower()
    if d.startswith("http://"):
        d = d[7:]
    if d.startswith("https://"):
        d = d[8:]
    if d.startswith("www."):
        d = d[4:]
    return d.rstrip("/")


def _domain_matches(host: str, rule: str) -> bool:
    """True if host equals rule or is a subdomain of rule."""
    if not host or not rule:
        return False
    host = _normalize(host)
    rule = _normalize(rule)
    return host == rule or host.endswith("." + rule)


class Policy:
    """Decides what to do about the current browser context."""

    def __init__(self, blocklist: list[str], allowlist: list[str]) -> None:
        self._lock = Lock()
        self._blocklist = [_normalize(d) for d in blocklist if d]
        self._allowlist = [_normalize(d) for d in allowlist if d]

    # --- decisions ---

    def decide(self, context, session) -> Decision:
        """Apply rules and return a Decision. Does not mutate session."""
        from app.session import SessionMode, SessionStatus

        if session is None or session.status != SessionStatus.ACTIVE:
            return Decision(Action.ALLOW, "no active session", 1.0)

        host = context.domain
        if not host or host in ("", "about:blank"):
            return Decision(Action.ALLOW, "blank page", 1.0)

        with self._lock:
            blocklist = list(self._blocklist)
            allowlist = list(self._allowlist)

        for rule in allowlist:
            if _domain_matches(host, rule):
                return Decision(Action.ALLOW, f"{host} is on allowlist", 1.0)

        for rule in blocklist:
            if _domain_matches(host, rule):
                if session.mode == SessionMode.CHILL:
                    return Decision(Action.WARN, f"{host} is blocked (chill)", 1.0)
                return Decision(Action.BLOCK, f"{host} is blocked ({session.mode.value})", 1.0)

        # Ambiguous — hand off to AI.
        return Decision(Action.ALLOW, "not in rules", 0.5, needs_ai=True)

    # --- dynamic list management ---

    def add_block(self, domain: str) -> str:
        d = _normalize(domain)
        if not d:
            raise ValueError("empty domain")
        with self._lock:
            if d not in self._blocklist:
                self._blocklist.append(d)
            if d in self._allowlist:
                self._allowlist.remove(d)
        return d

    def add_allow(self, domain: str) -> str:
        d = _normalize(domain)
        if not d:
            raise ValueError("empty domain")
        with self._lock:
            if d not in self._allowlist:
                self._allowlist.append(d)
            if d in self._blocklist:
                self._blocklist.remove(d)
        return d

    def remove_block(self, domain: str) -> bool:
        d = _normalize(domain)
        with self._lock:
            if d in self._blocklist:
                self._blocklist.remove(d)
                return True
        return False

    def list_blocked(self) -> list[str]:
        with self._lock:
            return list(self._blocklist)

    def list_allowed(self) -> list[str]:
        with self._lock:
            return list(self._allowlist)
