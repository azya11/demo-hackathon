"""Context detector — reads current browser state.

Uses a Playwright-controlled browser (not OS window introspection) so we
know exactly which tab is active and its URL. This is the demo-safe
approach: the user browses *inside* our launched browser.
"""

from __future__ import annotations


class Context:
    """Snapshot of the user's current browsing context."""

    def __init__(self, url: str, title: str, domain: str, timestamp) -> None:
        # TODO: store fields
        raise NotImplementedError


class Detector:
    """Launches and inspects a Playwright browser session."""

    def __init__(self) -> None:
        # TODO: hold playwright instance, browser, context, active page
        raise NotImplementedError

    # --- browser lifecycle ---

    def launch(self, start_url: str = "about:blank") -> None:
        """Start Playwright, open browser window, attach tab listeners."""
        raise NotImplementedError

    def close(self) -> None:
        """Close browser + playwright."""
        raise NotImplementedError

    # --- introspection ---

    def snapshot(self) -> Context | None:
        """Return context for the currently focused tab, or None if closed."""
        # TODO: find active page (the most recently focused tab)
        # TODO: read page.url, page.title()
        # TODO: extract domain
        raise NotImplementedError

    def list_tabs(self) -> list[Context]:
        """All open tabs — useful for /status."""
        raise NotImplementedError
