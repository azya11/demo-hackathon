"""Theme definitions for Focus Guardian.

Each theme changes only colors — layout and structure are untouched.
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Theme:
    name: str
    description: str
    # identity colors
    accent: str      # primary brand  (titles, commands, panel borders)
    accent2: str     # secondary accent
    # state colors
    active: str      # ACTIVE status, success
    warning: str     # PAUSED status, warnings
    error: str       # STOPPED status, errors
    complete: str    # COMPLETED status
    info: str        # info messages, elapsed time
    # text scale
    text: str        # main body text
    subtext: str     # secondary text
    dim: str         # separators, labels, dim text
    # surface scale
    surface: str     # subtle surface (event feed border etc.)


THEMES: list[Theme] = [
    Theme(
        name="Catppuccin Mocha",
        description="warm purples & dreamy blues",
        accent="#cba6f7",
        accent2="#b4befe",
        active="#a6e3a1",
        warning="#f9e2af",
        error="#f38ba8",
        complete="#89b4fa",
        info="#94e2d5",
        text="#cdd6f4",
        subtext="#a6adc8",
        dim="#585b70",
        surface="#45475a",
    ),
    Theme(
        name="Tokyo Night",
        description="midnight city lights, electric neon",
        accent="#7aa2f7",
        accent2="#bb9af7",
        active="#9ece6a",
        warning="#e0af68",
        error="#f7768e",
        complete="#bb9af7",
        info="#73daca",
        text="#c0caf5",
        subtext="#9aa5ce",
        dim="#414868",
        surface="#24283b",
    ),
    Theme(
        name="Dracula",
        description="vampiric pink, lime blood & purple",
        accent="#ff79c6",
        accent2="#bd93f9",
        active="#50fa7b",
        warning="#f1fa8c",
        error="#ff5555",
        complete="#bd93f9",
        info="#8be9fd",
        text="#f8f8f2",
        subtext="#6272a4",
        dim="#44475a",
        surface="#282a36",
    ),
    Theme(
        name="Sunset Glow",
        description="golden hour, coral fire & warm sky",
        accent="#fd79a8",
        accent2="#e17055",
        active="#ffd32a",
        warning="#ff9f43",
        error="#ee5a24",
        complete="#74b9ff",
        info="#00cec9",
        text="#ffeaa7",
        subtext="#fdcb6e",
        dim="#636e72",
        surface="#2d3436",
    ),
    Theme(
        name="Emerald Forest",
        description="deep jungle, midnight greens & gold",
        accent="#00b894",
        accent2="#55efc4",
        active="#55efc4",
        warning="#fdcb6e",
        error="#d63031",
        complete="#74b9ff",
        info="#00cec9",
        text="#dfe6e9",
        subtext="#b2bec3",
        dim="#636e72",
        surface="#2d3436",
    ),
    Theme(
        name="Arctic Frost",
        description="northern lights, ice & aurora",
        accent="#81ecec",
        accent2="#a29bfe",
        active="#55efc4",
        warning="#fdcb6e",
        error="#ff7675",
        complete="#a29bfe",
        info="#74b9ff",
        text="#dfe6e9",
        subtext="#b2bec3",
        dim="#636e72",
        surface="#2d3436",
    ),
    Theme(
        name="Synthwave",
        description="neon grids, retro-futuristic glow",
        accent="#e040fb",
        accent2="#7c4dff",
        active="#00e5ff",
        warning="#ffea00",
        error="#ff1744",
        complete="#7c4dff",
        info="#00bcd4",
        text="#f3e5f5",
        subtext="#ce93d8",
        dim="#6a1b9a",
        surface="#4a148c",
    ),
    Theme(
        name="Amber CRT",
        description="vintage terminal, warm amber monochrome",
        accent="#ffb300",
        accent2="#ff8f00",
        active="#ffd54f",
        warning="#ff8f00",
        error="#e65100",
        complete="#ffe082",
        info="#ffcc02",
        text="#ffe0b2",
        subtext="#ffcc80",
        dim="#8d6e63",
        surface="#4e342e",
    ),
    Theme(
        name="Sakura Dream",
        description="cherry blossoms, soft pink & sage",
        accent="#f48fb1",
        accent2="#f06292",
        active="#ce93d8",
        warning="#fff176",
        error="#e91e63",
        complete="#80cbc4",
        info="#80deea",
        text="#fce4ec",
        subtext="#f8bbd0",
        dim="#ad1457",
        surface="#880e4f",
    ),
    Theme(
        name="Hacker",
        description="matrix green, pure terminal energy",
        accent="#00ff41",
        accent2="#00cc33",
        active="#00ff41",
        warning="#ffff00",
        error="#ff0000",
        complete="#00b300",
        info="#00cc44",
        text="#00ff41",
        subtext="#00cc33",
        dim="#006600",
        surface="#003300",
    ),
]

# The active theme — mutate this to switch themes globally.
current: Theme = THEMES[0]
