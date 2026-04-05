"""Dev-session tracker — identifies active code projects during a session.

Scans running editor/terminal processes via psutil, extracts their cwd +
command-line arguments, walks upward to find a `.git` directory, and
accumulates per-repo activity time. Used at session end to build an
AI-generated "what you worked on" report.

Detection is best-effort: permission errors on some processes are ignored.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

try:
    import psutil  # type: ignore
    _PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None  # type: ignore
    _PSUTIL_AVAILABLE = False


# Process names that typically hold an open project.
_EDITOR_NAMES = {
    "code.exe", "code", "cursor.exe", "cursor",
    "devenv.exe",  # Visual Studio
    "pycharm64.exe", "pycharm.exe", "pycharm",
    "idea64.exe", "idea.exe", "idea",
    "webstorm64.exe", "webstorm.exe", "webstorm",
    "goland64.exe", "goland.exe", "goland",
    "clion64.exe", "clion.exe", "clion",
    "rider64.exe", "rider.exe", "rider",
    "rubymine64.exe", "rubymine.exe", "rubymine",
    "phpstorm64.exe", "phpstorm.exe", "phpstorm",
    "datagrip64.exe", "datagrip.exe", "datagrip",
    "zed.exe", "zed",
    "sublime_text.exe", "sublime_text", "subl",
    "atom.exe", "atom",
    "nvim.exe", "nvim", "vim", "vi", "nvim-qt.exe",
    "emacs.exe", "emacs",
    "notepad++.exe", "notepad++",
}
_TERMINAL_NAMES = {
    "windowsterminal.exe", "wt.exe",
    "powershell.exe", "pwsh.exe",
    "cmd.exe",
    "bash.exe", "bash", "zsh", "fish", "sh",
    "alacritty.exe", "alacritty",
    "wezterm-gui.exe", "wezterm.exe",
    "kitty.exe", "kitty",
    "iterm2",
}
_DEV_NAMES = _EDITOR_NAMES | _TERMINAL_NAMES


@dataclass
class RepoActivity:
    """Accumulated activity for a single git repository."""
    root: str
    name: str
    editors: set[str] = field(default_factory=set)
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    # Sampled tick count — multiply by tick_seconds for rough time estimate.
    sample_count: int = 0

    def seconds_active(self, tick_seconds: float) -> int:
        return int(self.sample_count * tick_seconds)


class DevTracker:
    """Scans processes, maps them to git repos, tracks per-repo time."""

    def __init__(self) -> None:
        self.available = _PSUTIL_AVAILABLE
        self._repos: dict[str, RepoActivity] = {}
        # Cache path→repo-root lookups so we don't re-walk the filesystem.
        self._path_to_repo: dict[str, str | None] = {}

    # --- public API ---

    def reset(self) -> None:
        self._repos.clear()
        self._path_to_repo.clear()

    def tick(self) -> None:
        """One sample: scan processes and record hits against repos."""
        if not self.available:
            return
        now = datetime.now()
        active_roots: set[str] = set()
        for proc_name, paths in self._scan_dev_processes():
            for p in paths:
                root = self._resolve_repo_root(p)
                if not root:
                    continue
                active_roots.add(root)
                activity = self._repos.get(root)
                if activity is None:
                    activity = RepoActivity(
                        root=root, name=os.path.basename(root), first_seen=now,
                    )
                    self._repos[root] = activity
                activity.editors.add(proc_name)
                activity.last_seen = now
        for root in active_roots:
            self._repos[root].sample_count += 1

    def repos(self) -> list[RepoActivity]:
        """Return activity sorted by time spent (descending)."""
        return sorted(
            self._repos.values(),
            key=lambda r: r.sample_count,
            reverse=True,
        )

    def summary(self, tick_seconds: float) -> list[dict]:
        """Compact per-repo summary + git stats for AI consumption."""
        out = []
        for repo in self.repos():
            stats = _collect_git_stats(repo.root, repo.first_seen)
            out.append({
                "repo": repo.name,
                "path": repo.root,
                "seconds_active": repo.seconds_active(tick_seconds),
                "editors": sorted(repo.editors),
                "first_seen": repo.first_seen.isoformat() if repo.first_seen else "",
                "last_seen": repo.last_seen.isoformat() if repo.last_seen else "",
                **stats,
            })
        return out

    # --- internals ---

    def _scan_dev_processes(self) -> list[tuple[str, list[str]]]:
        """Yield (name, candidate_paths) for every dev-like running process."""
        out: list[tuple[str, list[str]]] = []
        assert psutil is not None
        for proc in psutil.process_iter(["name", "cmdline", "cwd"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if name not in _DEV_NAMES:
                    continue
                paths: list[str] = []
                cwd = proc.info.get("cwd")
                if cwd:
                    paths.append(cwd)
                cmdline = proc.info.get("cmdline") or []
                for arg in cmdline[1:]:  # skip exe itself
                    if not arg or arg.startswith("-"):
                        continue
                    # Only keep args that look like filesystem paths.
                    if os.path.sep in arg or (len(arg) > 1 and arg[1] == ":"):
                        if os.path.exists(arg):
                            paths.append(arg)
                if paths:
                    out.append((name, paths))
            except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
                continue
        return out

    def _resolve_repo_root(self, path: str) -> str | None:
        """Walk upward from `path` to find a .git directory; cached."""
        try:
            p = Path(path).resolve()
        except Exception:
            return None
        key = str(p)
        if key in self._path_to_repo:
            return self._path_to_repo[key]
        if p.is_file():
            p = p.parent
        # Climb up to 8 levels looking for .git
        current = p
        for _ in range(8):
            if (current / ".git").exists():
                root = str(current)
                self._path_to_repo[key] = root
                return root
            if current.parent == current:
                break
            current = current.parent
        self._path_to_repo[key] = None
        return None


def _collect_git_stats(repo_root: str, since: datetime | None) -> dict:
    """Run git commands in `repo_root` to summarize session activity."""
    since_arg = since.strftime("%Y-%m-%d %H:%M:%S") if since else None

    def _run(args: list[str]) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", repo_root, *args],
                capture_output=True, text=True, timeout=5,
            )
            return (result.stdout or "").strip()
        except Exception:
            return ""

    commits_raw = _run([
        "log", "--oneline", "--no-merges",
        *(["--since", since_arg] if since_arg else []),
    ])
    commits = [line for line in commits_raw.splitlines() if line][:20]

    # Combined diff since session start (committed + uncommitted).
    if since_arg:
        # Find first commit before session start to diff from.
        base = _run(["log", "-n", "1", "--format=%H", "--before", since_arg])
    else:
        base = _run(["log", "-n", "1", "--format=%H"])
    diff_stat = _run(["diff", "--stat", base]) if base else _run(["diff", "--stat", "HEAD"])
    diff_lines = diff_stat.splitlines()[-12:]  # last line = summary + a few files

    status = _run(["status", "--short"])
    status_lines = status.splitlines()[:15]

    branch = _run(["rev-parse", "--abbrev-ref", "HEAD"])

    return {
        "branch": branch,
        "commits": commits,
        "commit_count": len(commits),
        "diff_stat": diff_lines,
        "uncommitted": status_lines,
        "has_uncommitted_changes": bool(status_lines),
    }
