"""Gemini reasoning layer.

Used only for:
    1. Ambiguous tab classification (rules couldn't decide)
    2. Goal parsing (turn free-text goal → structured keywords / categories)
    3. Natural-language explanations for decisions

Kept intentionally thin — rules-first means AI is the fallback, not the driver.
"""

from __future__ import annotations


class AI:
    """Wraps Gemini calls for classification + explanation."""

    def __init__(self, api_key: str, model: str = "gemini-1.5-flash") -> None:
        # TODO: configure google.generativeai client
        # TODO: load prompts from prompts/ directory
        raise NotImplementedError

    # --- classification ---

    def classify_tab(self, context, goal: str, recent_activity: list[str]):
        """Return Decision-compatible dict: {decision, confidence, short_reason}."""
        # TODO: render classify_tab.txt with context
        # TODO: call model, parse JSON response
        # TODO: fall back to ALLOW on parse errors (never block on AI failure)
        raise NotImplementedError

    # --- goal understanding ---

    def parse_goal(self, goal_text: str) -> dict:
        """Extract {subject, keywords[], suggested_allowlist[], suggested_blocklist[]}."""
        raise NotImplementedError

    # --- explanations ---

    def explain_decision(self, decision, context, goal: str) -> str:
        """One-sentence natural explanation for the terminal UI."""
        raise NotImplementedError
