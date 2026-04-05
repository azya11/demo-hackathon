"""Process monitor — rules-first process blocking.

Parallel to the URL detector: lists running processes via psutil, matches
against a blocklist, terminates offenders (strict) or warns (soft).

Matching is by process name (exact, case-insensitive). Allowlist wins
over blocklist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import Lock


def _normalize(name: str) -> str:
    return (name or "").strip().lower()


@dataclass
class ProcessInfo:
    """Snapshot of a running process we care about."""
    pid: int
    name: str
    timestamp: datetime


class ProcessMonitor:
    """Holds the process rules and scans the system each tick."""

    def __init__(self, blocklist: list[str], allowlist: list[str]) -> None:
        self._lock = Lock()
        self._blocklist = {_normalize(n) for n in blocklist if n}
        self._allowlist = {_normalize(n) for n in allowlist if n}
        self._psutil = None
        try:
            import psutil
            self._psutil = psutil
        except ImportError:
            pass

    @property
    def available(self) -> bool:
        return self._psutil is not None

    # --- scanning ---

    def scan_blocked(self) -> list[ProcessInfo]:
        """Return every running process whose name is on the blocklist."""
        if self._psutil is None:
            return []
        with self._lock:
            blocklist = set(self._blocklist)
            allowlist = set(self._allowlist)
        if not blocklist:
            return []
        out: list[ProcessInfo] = []
        now = datetime.now()
        for proc in self._psutil.process_iter(["pid", "name"]):
            try:
                name = _normalize(proc.info.get("name") or "")
                if not name or name in allowlist:
                    continue
                if name in blocklist:
                    out.append(ProcessInfo(pid=proc.info["pid"], name=name, timestamp=now))
            except (self._psutil.NoSuchProcess, self._psutil.AccessDenied):
                continue
        return out

    # --- actions ---

    def kill(self, pid: int) -> bool:
        """Terminate a process by PID. Returns success."""
        if self._psutil is None:
            return False
        try:
            proc = self._psutil.Process(pid)
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except self._psutil.TimeoutExpired:
                proc.kill()
            return True
        except (self._psutil.NoSuchProcess, self._psutil.AccessDenied):
            return False
        except Exception:
            return False

    # --- dynamic list management ---

    def add_block(self, name: str) -> str:
        n = _normalize(name)
        if not n:
            raise ValueError("empty process name")
        with self._lock:
            self._blocklist.add(n)
            self._allowlist.discard(n)
        return n

    def add_allow(self, name: str) -> str:
        n = _normalize(name)
        if not n:
            raise ValueError("empty process name")
        with self._lock:
            self._allowlist.add(n)
            self._blocklist.discard(n)
        return n

    def remove_block(self, name: str) -> bool:
        n = _normalize(name)
        with self._lock:
            if n in self._blocklist:
                self._blocklist.remove(n)
                return True
        return False

    def list_blocked(self) -> list[str]:
        with self._lock:
            return sorted(self._blocklist)

    def list_allowed(self) -> list[str]:
        with self._lock:
            return sorted(self._allowlist)
