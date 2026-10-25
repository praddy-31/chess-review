"""
Follow Palette (V11): take the app's colours from the Palette theme switcher.

Palette (a separate, optional app) rewrites ~/.config/palette/current/chess-review.json
on every theme switch: the theme's named colours as plain "#rrggbb" values (the same
contract as its Habit Tracker file). When the "Follow Palette" setting is on (off by
default) the page asks /api/palette every couple of seconds; this module reads the file,
accepts it only if every colour is plain #rrggbb, and works out the app's CSS variables.

What follows the theme: the page, cards, text, chart lines and the accent. What doesn't:
the move-label colours (they carry meaning, the same on every theme) and the board
(its own setting). An accent in the reds, oranges and yellows would read as an error
label, so then the theme's blue, magenta or cyan stands in for it.

Only a local file is read; nothing here touches the network.
"""

from __future__ import annotations

import colorsys
import json
import os
import re
from typing import Optional

KEYS = ["background", "dark_background", "lighter_background", "selection", "muted", "foreground",
        "dark_foreground", "light_foreground", "bright_foreground", "accent", "red", "orange", "yellow",
        "green", "cyan", "blue", "magenta"]
MAX_BYTES = 16 * 1024          # the real file is under 1 KB
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def folder() -> str:
    return os.environ.get("CHESS_REVIEW_PALETTE_DIR") or os.path.expanduser("~/.config/palette")


def colours_file() -> str:
    return os.path.join(folder(), "current", "chess-review.json")


def parse(text: str) -> Optional[dict]:
    """The colours, or None unless every one is a plain #rrggbb."""
    try:
        o = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(o, dict):
        return None
    c = {}
    for k in KEYS:
        v = o.get(k)
        if not isinstance(v, str) or not HEX.match(v):
            return None
        c[k] = v.lower()
    c["mode"] = "light" if o.get("mode") == "light" else "dark"
    c["theme"] = re.sub(r"[^\w .()+-]", "", str(o.get("theme") or ""))[:60] or "Palette"
    return c


# ---- colour helpers -----------------------------------------------------------------
def _rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def _hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, round(x))):02x}" for x in rgb)


def mix(a: str, b: str, t: float) -> str:
    A, B = _rgb(a), _rgb(b)
    return _hex(x + (y - x) * t for x, y in zip(A, B))


def lum(h: str) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    x, y = lum(a), lum(b)
    return (max(x, y) + 0.05) / (min(x, y) + 0.05)


def readable(col: str, page: str, ink: str, target: float = 3.0) -> str:
    """Nudges a colour toward the text colour until it reads on the page."""
    c = col
    for i in range(1, 7):
        if contrast(c, page) >= target:
            break
        c = mix(col, ink, i / 8)
    return c


def _warm(h: str) -> bool:
    """Red, orange or yellow and clearly coloured: would read like an error label."""
    r, g, b = (v / 255 for v in _rgb(h))
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    deg = hue * 360
    return sat > 0.35 and 0.15 < light < 0.9 and (deg < 62 or deg > 340)


def accent(c: dict) -> str:
    """The theme's accent, unless it's warm: then the first of blue, magenta, cyan that isn't."""
    if not _warm(c["accent"]):
        return c["accent"]
    for k in ("blue", "magenta", "cyan"):
        if not _warm(c[k]) and contrast(c[k], c["background"]) >= 2.5:
            return c[k]
    return c["accent"]


def css_vars(c: dict) -> dict:
    """The app's variables (web/styles.css themes) from Palette's colours."""
    dark = c["mode"] != "light"
    page, ink = c["background"], c["foreground"]
    acc = accent(c)
    on_acc = page if contrast(acc, page) >= contrast(acc, c["bright_foreground"]) else c["bright_foreground"]
    sunk = not dark and lum(c["lighter_background"]) < lum(page)   # light themes often raise by darkening
    r, g, b = _rgb(ink)
    return {
        "--page": page,
        "--surface": mix(page, "#ffffff", 0.7) if sunk else c["lighter_background"],
        "--surface-2": c["lighter_background"] if sunk else c["dark_background"],
        "--ink": ink, "--ink-2": mix(ink, c["dark_foreground"], 0.4),
        "--muted": readable(c["dark_foreground"], page, ink),
        "--grid": c["selection"], "--axis": c["muted"],
        "--border": f"rgba({r},{g},{b},{0.12 if dark else 0.18})",
        "--good": readable(c["green"], page, ink), "--critical": readable(c["red"], page, ink),
        "--warning": readable(c["yellow"], page, ink),
        "--accent": acc, "--accent-soft": mix(page, acc, 0.3 if dark else 0.2), "--on-accent": on_acc,
    }


def _read_capped(path: str) -> Optional[str]:
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > MAX_BYTES:
            return None
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def status() -> dict:
    """What Settings' setup check shows, plus the variables when the file is good."""
    path = colours_file()
    text = _read_capped(path)
    c = parse(text) if text else None
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None
    return {
        "installed": os.path.isdir(folder()),
        "active": os.path.isdir(os.path.join(folder(), "current")),   # a theme has been picked once
        "file": text is not None,
        "valid": c is not None,
        "modified": mtime,
        "theme": c["theme"] if c else None,
        "mode": c["mode"] if c else None,
        "swatches": [c[k] for k in ("background", "lighter_background", "foreground", "accent", "green", "yellow", "red")] if c else [],
        "accent_swapped": bool(c) and accent(c) != c["accent"],
        "vars": css_vars(c) if c else None,
    }
