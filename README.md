# Focus Guardian AI

An agent that protects your focus, not just tracks it.

## Overview

Terminal-first AI agent that watches your browsing context during a focus session,
detects distractions, and takes real action (warn, close tab, redirect) to keep you
aligned with your stated goal.

## Architecture

```
┌─────────────────────────────┐
│        Terminal UI          │  ui.py (Rich)
│  commands, logs, session    │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│      Agent Orchestrator     │  orchestrator.py
│ session loop + decisions    │
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
| `main.py` | Entry point, wires dependencies, starts CLI |
| `cli.py` | Parse terminal commands (`/start`, `/status`, `/stop`, `/pause`, etc.) |
| `ui.py` | Render dashboard, event feed, status panels via Rich |
| `orchestrator.py` | Main polling loop, coordinate detector → policy → tools |
| `session.py` | Session lifecycle (create, pause, resume, stop, timer) |
| `policy.py` | Rules-first decision engine (allow / warn / block) |
| `detector.py` | Read active window title, browser URL via Playwright |
| `tools.py` | Agent actions: close tab, warn user, open URL, log event |
| `ai.py` | Gemini integration for ambiguous classification + explanations |
| `storage.py` | SQLite persistence for sessions, events, analytics |
| `models.py` | Dataclasses: Session, Event, Decision, Context |

## Scope (hackathon MVP)

- Controlled Playwright browser (not arbitrary OS browsers) for demo stability
- Rules-first policy with AI only for ambiguous cases
- 3 core commands: `/start`, `/status`, `/stop`
- 2 modes: soft (warn only), strict (warn + close tab)

## Commands

```
/start "Study OS for 90 min"
/stop
/status
/pause
/resume
/mode strict | soft
/block <domain>
/allow <domain>
/summary
```

## Installation

**macOS / Linux**
```bash
pip3 install rich prompt_toolkit
```

**Windows** (if `pip.exe` is blocked by Application Control policy)
```powershell
.venv/Scripts/python.exe -m pip install rich prompt_toolkit
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
- Rich — terminal UI
- prompt_toolkit — live slash-command completion
- Playwright — controlled browser session
- Google Generative AI (Gemini) — reasoning layer
- SQLite — persistence
