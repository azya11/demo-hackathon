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


# Windows system processes — never surface these to the AI judge.
_SYSTEM_PROCESSES = {
    "system", "system idle process", "registry", "memory compression",
    "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe",
    "lsass.exe", "svchost.exe", "fontdrvhost.exe", "dwm.exe", "taskhostw.exe",
    "explorer.exe", "runtimebroker.exe", "sihost.exe", "ctfmon.exe",
    "searchindexer.exe", "searchprotocolhost.exe", "searchfilterhost.exe",
    "audiodg.exe", "conhost.exe", "dllhost.exe", "smartscreen.exe",
    "applicationframehost.exe", "startmenuexperiencehost.exe", "shellexperiencehost.exe",
    "wmiprvse.exe", "wmiadap.exe", "spoolsv.exe", "securityhealthservice.exe",
    "securityhealthsystray.exe", "msmpeng.exe", "nissrv.exe", "mpdefendercoreservice.exe",
    "wudfhost.exe", "updateorchestrator.exe", "trustedinstaller.exe", "tiworker.exe",
    "usocoreworker.exe", "backgroundtaskhost.exe", "backgroundtransferhost.exe",
    "textinputhost.exe", "lockapp.exe", "crosshairconfiguration.exe",
    "python.exe", "pythonw.exe", "node.exe",  # tools used by the agent itself
    # hardware vendor drivers / overlays / RGB / peripheral managers — never distractions
    "nvcontainer.exe", "nvidia overlay.exe", "nvidia share.exe", "nvidia web helper.exe",
    "nvdisplay.container.exe", "nvbroadcast.container.exe", "nvtelemetrycontainer.exe",
    "lghub.exe", "lghub_agent.exe", "lghub_system_tray.exe", "lghub_updater.exe",
    "logi_crayon.exe", "logioptionsplus.exe", "logioverlay.exe",
    "razer central service.exe", "razer synapse service.exe", "rzsynapse.exe",
    "icue.exe", "corsair.service.exe",
    "armourycrate.exe", "asus framework service.exe",
    "realtekaudioservice64.exe", "ravcpl64.exe",
    "igfxem.exe", "igfxtray.exe", "igfxhk.exe", "igfxext.exe",
    "radeonsoftware.exe", "amdrsserv.exe", "cncmd.exe",
    # cloud sync / update agents — background, not interactive distractions
    "onedrive.exe", "dropbox.exe", "googledrivefs.exe", "googleupdate.exe",
    "microsoftedgeupdate.exe", "adobeupdateservice.exe", "crashpad_handler.exe",
}


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

    def scan_candidates(self) -> list[ProcessInfo]:
        """Return user-facing processes not on any list — candidates for AI judgment.

        Excludes Windows system processes, explicit blocklist (handled by
        scan_blocked), and explicit allowlist. One entry per pid.
        """
        if self._psutil is None:
            return []
        with self._lock:
            blocklist = set(self._blocklist)
            allowlist = set(self._allowlist)
        out: list[ProcessInfo] = []
        now = datetime.now()
        for proc in self._psutil.process_iter(["pid", "name"]):
            try:
                name = _normalize(proc.info.get("name") or "")
                if not name:
                    continue
                if name in _SYSTEM_PROCESSES or name in blocklist or name in allowlist:
                    continue
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
