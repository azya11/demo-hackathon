"""Entry point.

Wires UI + Policy + Detector + Tools + AI + Orchestrator + CLI and starts
the REPL. Config is loaded from configs/settings.json and
configs/blocked_sites.json.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.ai import AI
from app.cli import CLI
from app.detector import Detector
from app.orchestrator import Orchestrator
from app.policy import Policy
from app.process_monitor import ProcessMonitor
from app.tools import Tools
from app.ui import UI


ROOT = Path(__file__).resolve().parent.parent


def _find_service_account(configs_dir: Path) -> Path | None:
    """Find a Google service-account JSON in configs/ (has 'type: service_account')."""
    if not configs_dir.exists():
        return None
    for p in configs_dir.glob("*.json"):
        if p.name in ("settings.json", "blocked_sites.json", "blocked_processes.json"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("type") == "service_account":
                return p
        except Exception:
            continue
    return None


def _load_json(path: Path, default: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def main() -> None:
    settings = _load_json(ROOT / "configs" / "settings.json", {})
    sites = _load_json(ROOT / "configs" / "blocked_sites.json", {"blocklist": [], "allowlist": []})
    procs = _load_json(ROOT / "configs" / "blocked_processes.json", {"blocklist": [], "allowlist": []})

    ui = UI()
    policy = Policy(blocklist=sites.get("blocklist", []), allowlist=sites.get("allowlist", []))
    process_monitor = ProcessMonitor(
        blocklist=procs.get("blocklist", []),
        allowlist=procs.get("allowlist", []),
    )
    if not process_monitor.available:
        ui.warn("process monitor disabled (psutil not installed)")
    detector = Detector()
    events: list = []
    tools = Tools(ui=ui, event_log=events, detector=detector, process_monitor=process_monitor)

    ai_cfg = settings.get("ai", {})
    ai = None
    if ai_cfg.get("enabled", True):
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
        sa_path = _find_service_account(ROOT / "configs")
        ai = AI(
            api_key=api_key,
            model=ai_cfg.get("model", "gemini-1.5-flash"),
            service_account_path=sa_path,
            location=ai_cfg.get("location", "us-central1"),
        )
        if not ai.enabled:
            ui.warn("Gemini disabled (no service-account JSON in configs/ and no GEMINI_API_KEY)")
            if getattr(ai, "_last_error", ""):
                ui.warn(f"  init error: {ai._last_error}")
        elif sa_path is not None:
            ui.info(f"Gemini via Vertex AI ({sa_path.name})")

    browser_cfg = settings.get("browser", {})
    orchestrator = Orchestrator(
        ui=ui,
        policy=policy,
        tick_seconds=float(settings.get("tick_seconds", 2.0)),
        detector=detector,
        tools=tools,
        ai=ai,
        browser_start_url=browser_cfg.get("start_url", "about:blank"),
        browser_headless=bool(browser_cfg.get("headless", False)),
        browser_mode=browser_cfg.get("mode", "launch"),
        cdp_url=browser_cfg.get("cdp_url", "http://localhost:9222"),
        process_monitor=process_monitor,
    )
    # Share the orchestrator's event log with tools so warn/close events land there.
    orchestrator.events = events

    cli = CLI(orchestrator=orchestrator, ui=ui)
    cli.run()


if __name__ == "__main__":
    main()
