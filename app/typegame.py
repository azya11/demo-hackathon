"""Typing game — launched from /pause.

Presents a random sentence, times the user's input, then reports
WPM and accuracy using Rich for styled output. Persists session
stats to configs/gamestats.json for /gamestats.
"""

from __future__ import annotations

import json
import random
import time
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

STATS_FILE = Path(__file__).parent.parent / "configs" / "gamestats.json"

_SENTENCES = [
    # fun facts
    "A group of flamingos is called a flamboyance.",
    "Honey never spoils. Archaeologists found 3000-year-old honey in Egyptian tombs.",
    "Octopuses have three hearts and blue blood.",
    "Bananas are technically berries, but strawberries are not.",
    "The Eiffel Tower grows about 15 cm taller in summer due to heat expansion.",
    "A day on Venus is longer than a year on Venus.",
    "Sharks are older than trees and have existed for over 400 million years.",
    "The average cloud weighs around 500 thousand kilograms.",
    "Crows can recognize human faces and hold grudges.",
    "There are more possible chess games than atoms in the observable universe.",
    # technology
    "The first computer bug was an actual moth found inside a relay in 1947.",
    "Python was named after Monty Python, not the snake.",
    "The original iPhone had no copy and paste feature.",
    "Wi-Fi does not stand for wireless fidelity. It never stood for anything.",
    "About 90 percent of the world's data was created in the last two years.",
    "The first computer mouse was made of wood.",
    "Google was originally called BackRub before being renamed.",
    "Email is older than the World Wide Web by about two decades.",
    # nature
    "Trees in a forest communicate and share nutrients through underground fungal networks.",
    "A bolt of lightning is five times hotter than the surface of the sun.",
    "The Amazon rainforest produces about 20 percent of the world's oxygen.",
    "Butterflies taste with their feet.",
    "A single tree can absorb up to 22 kilograms of carbon dioxide per year.",
    "The blue whale's heartbeat can be detected from two miles away.",
    # history
    "Cleopatra lived closer in time to the Moon landing than to the building of the pyramids.",
    "Oxford University is older than the Aztec Empire.",
    "Nintendo was founded in 1889 as a playing card company.",
    "The shortest war in history lasted only 38 to 45 minutes.",
    "Vikings never actually wore horned helmets in battle.",
    # pop culture & random
    "The voice actors of Mickey and Minnie Mouse were married in real life.",
    "A group of cats is called a clowder.",
    "Cereal was invented to be a boring, unseasoned health food.",
    "The longest place name in the world is in New Zealand and has 85 characters.",
    "Hot dogs were originally called frankfurter wuerstchen, meaning little Frankfurt sausage.",
]


def _accuracy(original: str, typed: str) -> float:
    """Accuracy based on matched character blocks, not strict position."""
    if not original:
        return 100.0
    matcher = SequenceMatcher(None, original, typed)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    total = max(len(original), len(typed))
    return round(matched / total * 100, 1)


def _wpm(text: str, elapsed: float) -> float:
    """Standard WPM: words = chars / 5, time in minutes."""
    if elapsed <= 0:
        return 0.0
    words = len(text) / 5
    minutes = elapsed / 60
    return round(words / minutes, 1)


def load_all_stats() -> list[dict]:
    """Load all saved game sessions from disk."""
    if not STATS_FILE.exists():
        return []
    try:
        return json.loads(STATS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


class TypingGame:
    """Self-contained typing mini-game."""

    def __init__(self) -> None:
        self.console = Console()

    def run(self) -> None:
        """Continuous game loop: keeps playing rounds until the user quits."""
        console = self.console
        console.clear()
        console.print(Panel.fit(
            "[bold medium_purple1]Typing Game[/bold medium_purple1]\n"
            "[dim]A quick break for your fingers. Type [bold]q[/bold] at any prompt to leave.[/dim]",
            border_style="medium_purple1",
        ))
        console.print()

        round_num = 0
        rounds: list[dict] = []

        while True:
            round_num += 1
            sentence = random.choice(_SENTENCES)

            console.print(Panel(
                f"[bold white]{sentence}[/bold white]",
                title=f"[dim]Round {round_num} - Type this[/dim]",
                border_style="medium_purple1",
            ))
            console.print()

            start = time.perf_counter()
            try:
                typed = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            elapsed = time.perf_counter() - start

            if typed.lower() == "q":
                break

            wpm = _wpm(sentence, elapsed)
            acc = _accuracy(sentence, typed)
            rounds.append({"wpm": wpm, "accuracy": acc, "time": elapsed})

            console.print()
            self._render_results(sentence, typed, wpm, acc, elapsed)
            console.print()
            console.print("[dim]Press Enter for next round or type q to quit...[/dim]")

            try:
                again = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                break
            if again == "q":
                break

            console.clear()

        if rounds:
            console.print()
            self._render_session_summary(rounds)
            self._save_session(rounds)
            console.print()
            input("[dim]Press Enter to return to Focus Guardian...[/dim]")

        console.print("\n[medium_purple1]Good work! Heading back to your session...[/medium_purple1]\n")

    def _render_results(
        self,
        original: str,
        typed: str,
        wpm: float,
        acc: float,
        elapsed: float,
    ) -> None:
        console = self.console

        diff = Text()
        matcher = SequenceMatcher(None, original, typed)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                diff.append(original[i1:i2], style="green")
            elif tag in ("replace", "delete"):
                diff.append(original[i1:i2], style="red underline")
            elif tag == "insert":
                diff.append(typed[j1:j2], style="yellow")

        console.print(Panel(diff, title="[dim]Result[/dim]", border_style="dim"))
        console.print()

        wpm_color = "green" if wpm >= 60 else "yellow" if wpm >= 30 else "red"
        acc_color = "green" if acc >= 95 else "yellow" if acc >= 80 else "red"

        console.print(
            f"  [bold]WPM:[/bold]      [{wpm_color}]{wpm}[/{wpm_color}]\n"
            f"  [bold]Accuracy:[/bold] [{acc_color}]{acc}%[/{acc_color}]\n"
            f"  [bold]Time:[/bold]     {elapsed:.1f}s"
        )

    def _render_session_summary(self, rounds: list[dict]) -> None:
        console = self.console

        avg_wpm = round(sum(r["wpm"] for r in rounds) / len(rounds), 1)
        best_wpm = max(r["wpm"] for r in rounds)
        avg_acc = round(sum(r["accuracy"] for r in rounds) / len(rounds), 1)
        best_acc = max(r["accuracy"] for r in rounds)
        total_time = sum(r["time"] for r in rounds)

        table = Table(
            title="Session Summary",
            header_style="bold medium_purple1",
            border_style="medium_purple1",
            show_lines=False,
        )
        table.add_column("Stat", style="bold", no_wrap=True)
        table.add_column("Value")

        def wpm_color(v: float) -> str:
            return "green" if v >= 60 else "yellow" if v >= 30 else "red"

        def acc_color(v: float) -> str:
            return "green" if v >= 95 else "yellow" if v >= 80 else "red"

        table.add_row("Rounds played", str(len(rounds)))
        table.add_row("Avg WPM", f"[{wpm_color(avg_wpm)}]{avg_wpm}[/]")
        table.add_row("Best WPM", f"[{wpm_color(best_wpm)}]{best_wpm}[/]")
        table.add_row("Avg Accuracy", f"[{acc_color(avg_acc)}]{avg_acc}%[/]")
        table.add_row("Best Accuracy", f"[{acc_color(best_acc)}]{best_acc}%[/]")
        table.add_row("Total time", f"{total_time:.1f}s")

        console.print(table)

    def _save_session(self, rounds: list[dict]) -> None:
        sessions = load_all_stats()
        sessions.append({
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "rounds": len(rounds),
            "avg_wpm": round(sum(r["wpm"] for r in rounds) / len(rounds), 1),
            "best_wpm": max(r["wpm"] for r in rounds),
            "avg_accuracy": round(sum(r["accuracy"] for r in rounds) / len(rounds), 1),
            "best_accuracy": max(r["accuracy"] for r in rounds),
            "total_time": round(sum(r["time"] for r in rounds), 1),
        })
        STATS_FILE.write_text(json.dumps(sessions, indent=2), encoding="utf-8")
