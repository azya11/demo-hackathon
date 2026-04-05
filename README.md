# Focus Guardian AI

An agent that protects your focus, not just tracks it.

## Overview

Terminal-first AI agent that watches your browser tabs and desktop processes during a focus session, detects distractions, and takes real action — warn, close tab, or kill process — to keep you aligned with your stated goal.

Rules run first. Gemini AI handles ambiguous cases. Three enforcement modes let you choose how strict the agent is.

## Architecture

```
┌─────────────────────────────┐
│        Terminal UI          │  ui.py (Rich / Catppuccin theme)
│  commands, logs, session    │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│      Agent Orchestrator     │  orchestrator.py
│  session loop + decisions   │
└───────┬─────────┬───────────┘
        │         │
        ▼         ▼
┌──────────────┐  ┌──────────────────┐
│ Context      │  │ Policy Engine    │
│ Collector    │  │ rules + AI judge │
│ detector.py  │  │ policy.py + ai.py│
└──────┬───────┘  └──────────────────┘
       │
       ▼
┌─────────────────────────────┐
│        Tool Layer           │  tools.py
│ close tab / warn / redirect │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ Local persistence / memory  │  storage.py
│ session state, events, logs │
└─────────────────────────────┘
```

## Module responsibilities

| Module | Responsibility |
|---|---|
| `main.py` | Entry point — wires dependencies, loads config, starts CLI |
| `cli.py` | Parse slash commands (`/start`, `/stop`, `/settings`, etc.) |
| `ui.py` | Rich dashboard with live toolbar, event feed, status panels |
| `orchestrator.py` | Main polling loop — coordinates detector → policy → tools |
| `session.py` | Session lifecycle (create, pause, resume, stop, timer) |
| `policy.py` | Rules-first decision engine (allow / warn / block) |
| `detector.py` | Read browser tabs via Playwright or CDP; normalize URLs |
| `tools.py` | Agent actions: close tab, kill process, warn user, log event |
| `ai.py` | Gemini integration — classifies ambiguous tabs and processes |
| `process_monitor.py` | Scan running desktop processes via psutil |
| `popup.py` | Spawn warning notification in a separate terminal window |
| `typegame.py` | Typing game for break time — tracks WPM and accuracy |
| `storage.py` | Persistence (settings/blocklists saved as JSON; SQLite stub) |
| `models.py` | Dataclasses: Session, Event, Decision, Context |

## Enforcement modes

| Mode | Behavior |
|---|---|
| **chill** | Monitor and warn only. Never closes tabs or kills processes. Tracks cumulative distraction time. |
| **normal** | Warns first, then closes/kills after a grace period (default 15 min). Per-domain/process grace tracking. |
| **hardcore** | Immediate action — no warnings, no grace period. First offense = instant closure or termination. |

Change mode mid-session with `/settings mode <chill\|normal\|hardcore>` or set a default in `settings.json`.

## Commands

### Session

```
/start "<goal>" <minutes> [mode]   Start a focus session
/stop                              End session and show summary
/status                            Show current session dashboard
/pause                             Pause timer and enforcement
/resume                            Resume after pause
/clear                             Redraw the screen
/quit  /q  /exit                   Exit the app
```

### Settings

```
/settings                          Interactive settings menu
/settings mode <chill|normal|hardcore>
/settings grace <minutes>          Grace period for normal mode
/settings time [+20|-10|45]        Adjust session time (delta or absolute)
/settings block <domain>           Add domain to blocklist
/settings allow <domain>           Add domain to allowlist
/settings blocks                   List blocked/allowed domains
/settings pblock <process.exe>     Block a desktop process
/settings pallow <process.exe>     Allow a desktop process
/settings pblocks                  List blocked/allowed processes
```

### Other

```
/help         Command reference
/gamestats    All-time typing game stats and last 20 sessions
```

## AI integration

Gemini is used only for ambiguous cases — explicit blocklists and allowlists are evaluated first.

- **Browser tabs:** classified by goal, page title, and URL
- **Desktop processes:** classified by goal and process name
- Results are cached per session so the same resource isn't re-classified every tick
- A circuit breaker disables AI after 3 errors and re-enables on the next session

**Authentication** (in order of preference):
1. Service-account JSON placed in `configs/` (Vertex AI)
2. `GEMINI_API_KEY` or `GOOGLE_API_KEY` environment variable

## Browser integration

**Attach mode** (default/recommended) — connects to your existing Chrome via Chrome DevTools Protocol:

```bash
# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222

# Windows
chrome.exe --remote-debugging-port=9222
```

**Launch mode** — Playwright spawns and controls a Chromium window directly. Set in `settings.json`:
```json
"browser": { "mode": "launch", "headless": false }
```

## Configuration

**`configs/settings.json`**

```jsonc
{
  "default_mode": "chill",                // chill | normal | hardcore
  "tick_seconds": 2.0,                    // polling interval
  "normal_mode_grace_minutes": 15.0,      // grace period for normal mode
  "browser": {
    "mode": "attach",                     // attach | launch
    "cdp_url": "http://127.0.0.1:9222",   // Chrome debug port
    "headless": false,                    // launch mode only
    "start_url": "about:blank"            // launch mode only
  },
  "ai": {
    "model": "gemini-2.5-flash",
    "enabled": true
  }
}
```

**`configs/blocked_sites.json`** — domain blocklist and allowlist

**`configs/blocked_processes.json`** — process name blocklist and allowlist

## Typing game

Pause your session (`/pause`) and launch the typing game to make break time intentional.

- 64 randomized sentences across animals, tech, history, and pop culture
- Scores WPM and accuracy with character-level diff highlighting
- All-time stats saved to `configs/gamestats.json` and viewable with `/gamestats`

## Docker

**Build**
```bash
docker build -t focus-guardian .
```

**Run** (interactive — required, it's a REPL)
```bash
docker run -it -e GEMINI_API_KEY=your_key focus-guardian
```

Persist session history across runs by mounting a volume:
```bash
docker run -it -e GEMINI_API_KEY=your_key -v focus-data:/app/data focus-guardian
```

> **Browser config:** the default `settings.json` uses `"mode": "attach"` (CDP). Switch to headless launch mode for container use:
> ```json
> "browser": { "mode": "launch", "headless": true }
> ```

## Installation

**macOS / Linux**
```bash
pip install -r requirements.txt
playwright install chromium
```

**Windows** (if `pip.exe` is blocked by Application Control policy)
```powershell
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/playwright.exe install chromium
```

## Running

**macOS / Linux**
```bash
python3 -m app.main
```

**Windows**
```powershell
.venv/Scripts/python.exe -m app.main
```

## Stack

- Python 3.11+
- Rich — terminal UI (Catppuccin Mocha theme)
- prompt_toolkit — live slash-command completion
- Playwright — controlled browser session
- psutil — desktop process monitoring
- Google Generative AI (Gemini) — reasoning layer
- SQLite — persistence (planned)
