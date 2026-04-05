"""Context detector — reads current browser state.

Two backends:
  - launch mode: Playwright spawns + controls a Chromium window (demo fallback).
  - attach mode: direct CDP HTTP calls against a user-run Chrome. No Playwright
    page initialization → no hangs when new tabs open.
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse


def extract_domain(url: str) -> str:
    """Return hostname stripped of 'www.' prefix, lowercase."""
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return ""
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


@dataclass
class Context:
    """Snapshot of a single tab's state."""
    url: str
    title: str
    domain: str
    timestamp: datetime
    page: object | None = None  # playwright Page OR target_id string (attach)
    target_id: str | None = None  # CDP target id, attach mode only


class Detector:
    """Inspects a Chromium browser. Playwright for launch, raw CDP for attach."""

    def __init__(self) -> None:
        self._mode: str = "none"  # "launch" | "attach" | "none"
        self._cdp_url: str = ""
        # launch-mode only:
        self._playwright = None
        self._browser = None
        self._context = None

    # --- lifecycle ---

    def launch(self, start_url: str = "about:blank", headless: bool = False) -> None:
        """Start Playwright, open a new browser window."""
        from playwright.sync_api import sync_playwright
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=headless)
        self._context = self._browser.new_context()
        page = self._context.new_page()
        try:
            page.goto(start_url, timeout=5000)
        except Exception:
            pass
        self._mode = "launch"

    def attach(self, cdp_url: str = "http://127.0.0.1:9222") -> None:
        """Attach via direct CDP HTTP — no Playwright instance needed."""
        # Probe /json/version to verify the debug port is live.
        base = cdp_url.rstrip("/")
        try:
            with urllib.request.urlopen(base + "/json/version", timeout=3) as r:
                _ = r.read()
        except Exception as e:
            raise RuntimeError(f"CDP probe failed at {cdp_url}: {e}")
        self._cdp_url = base
        self._mode = "attach"

    def close(self) -> None:
        """Release resources. Does NOT close the user's browser in attach mode."""
        if self._mode == "launch":
            try:
                if self._context is not None:
                    self._context.close()
            except Exception:
                pass
            try:
                if self._browser is not None:
                    self._browser.close()
            except Exception:
                pass
            try:
                if self._playwright is not None:
                    self._playwright.stop()
            except Exception:
                pass
        self._mode = "none"
        self._playwright = None
        self._browser = None
        self._context = None
        self._cdp_url = ""

    # --- introspection ---

    def is_alive(self) -> bool:
        if self._mode == "attach":
            return bool(self._cdp_url)
        return self._context is not None and len(self._context.pages) > 0

    def list_tabs(self) -> list[Context]:
        """Return all open tabs. Fast and non-blocking in attach mode."""
        if self._mode == "attach":
            return self._list_tabs_cdp()
        if self._mode == "launch":
            return self._list_tabs_playwright()
        return []

    # --- attach-mode (raw CDP) ---

    def _list_tabs_cdp(self) -> list[Context]:
        try:
            with urllib.request.urlopen(self._cdp_url + "/json", timeout=2) as r:
                data = json.loads(r.read().decode("utf-8", errors="replace"))
        except Exception:
            return []
        out: list[Context] = []
        now = datetime.now()
        for item in data:
            if item.get("type") != "page":
                continue
            url = item.get("url") or ""
            if url.startswith(("chrome://", "chrome-extension://", "devtools://", "edge://", "about:")):
                continue
            target_id = item.get("id") or ""
            out.append(Context(
                url=url,
                title=item.get("title") or "",
                domain=extract_domain(url),
                timestamp=now,
                page=target_id,
                target_id=target_id,
            ))
        return out

    def close_tab_cdp(self, target_id: str) -> bool:
        """Close a tab via CDP HTTP endpoint."""
        if not target_id or not self._cdp_url:
            return False
        try:
            with urllib.request.urlopen(self._cdp_url + f"/json/close/{target_id}", timeout=2) as r:
                _ = r.read()
            return True
        except Exception:
            return False

    # --- launch-mode (Playwright) ---

    def _list_tabs_playwright(self) -> list[Context]:
        if self._context is None:
            return []
        out: list[Context] = []
        now = datetime.now()
        for page in list(self._context.pages):
            try:
                if page.is_closed():
                    continue
                url = page.url or ""
                if url.startswith(("chrome://", "chrome-extension://", "devtools://", "edge://")):
                    continue
                try:
                    page.set_default_timeout(1500)
                    title = page.title()
                except Exception:
                    title = ""
                out.append(Context(
                    url=url,
                    title=title,
                    domain=extract_domain(url),
                    timestamp=now,
                    page=page,
                ))
            except Exception:
                continue
        return out
