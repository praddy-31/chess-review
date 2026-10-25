"""
Weekly study plan (V8): your training time for the week, split across the
app's four kinds of practice and tilted toward what you most need.

  - the weekly time is asked once (welcome, or the first start after the
    update) and lives in Settings; 0 switches the plan off
  - base split: puzzles 30%, opening study 25%, convert drills 20%,
    reviewing your games 25%
  - the weekly focus and your top recurring mistake move time toward the part
    that trains them
  - progress is estimated from what you did this week (Monday to Sunday):
    a puzzle about 1.5 minutes, an opening line 1.5, a convert drill 6, a
    reviewed game 8
"""

from __future__ import annotations

import datetime as _dt
import json
import time
from typing import Optional

import store

BASE = {"puzzles": 0.30, "openings": 0.25, "convert": 0.20, "review": 0.25}
COST = {"puzzles": 1.5, "openings": 1.5, "convert": 6.0, "review": 8.0}
LABEL = {"puzzles": "Puzzles", "openings": "Opening study", "convert": "Convert drills", "review": "Review your games"}
LINK = {"puzzles": "#/puzzles", "openings": "#/openings", "convert": "#/puzzles/convert", "review": "#/review"}
UNIT = {"puzzles": "puzzle", "openings": "line", "convert": "drill", "review": "game"}
FOCUS_TILT = {"opening": "openings", "converting": "convert", "blunders": "puzzles", "tactics": "puzzles", "time": "puzzles",
              "defending": "review", "endgame": "convert", "tilt": "review", "sessions": "review"}


def week_bounds(today: Optional[_dt.date] = None) -> tuple[str, str]:
    t = today or _dt.date.today()
    mon = t - _dt.timedelta(days=t.weekday())
    return mon.isoformat(), (mon + _dt.timedelta(days=7)).isoformat()


def log_review(game_id: str) -> None:
    """Called when you open an analysed game in Review (once per game per day)."""
    day = _dt.date.today().isoformat()
    with store.db() as con:
        con.execute("CREATE TABLE IF NOT EXISTS review_log (game_id TEXT, day TEXT, at REAL, PRIMARY KEY (game_id, day))")
        con.execute("INSERT OR IGNORE INTO review_log VALUES (?,?,?)", (game_id, day, time.time()))


def _done(a: str, b: str) -> dict:
    out = {"puzzles": 0, "openings": 0, "convert": 0, "review": 0}
    with store.db() as con:
        for key, sql in (("puzzles", "SELECT COUNT(*) FROM puzzle_log WHERE day >= ? AND day < ?"),
                         ("openings", "SELECT COUNT(*) FROM study_log WHERE day >= ? AND day < ?"),
                         ("convert", "SELECT COUNT(*) FROM convert_log WHERE day >= ? AND day < ?"),
                         ("review", "SELECT COUNT(*) FROM review_log WHERE day >= ? AND day < ?")):
            try:
                out[key] = con.execute(sql, (a, b)).fetchone()[0]
            except Exception:
                out[key] = 0
    return out


def build() -> dict:
    s = store.get_settings()
    minutes = s.get("plan_minutes")
    if minutes is None:
        return {"enabled": False, "asked": False}
    minutes = int(minutes or 0)
    if minutes <= 0:
        return {"enabled": False, "asked": True}
    w = dict(BASE)
    reasons = []
    focus = json.loads(store.get_meta("focus") or "null")
    if focus and FOCUS_TILT.get(focus.get("key")):
        k = FOCUS_TILT[focus["key"]]
        w[k] += 0.15
        reasons.append(f"more {LABEL[k].lower()} for your weekly focus")
    try:
        import patterns
        top = (patterns.build().get("patterns") or [None])[0]
    except Exception:
        top = None
    if top:
        w["puzzles"] += 0.05
        reasons.append(f"puzzles from “{top['title'].lower()}”")
    total = sum(w.values())
    a, b = week_bounds()
    done = _done(a, b)
    day_i = _dt.date.today().weekday()          # 0 = Monday
    parts = []
    for k, v in w.items():
        mins = round(minutes * v / total)
        n = max(1, round(mins / COST[k]))
        d = done[k]
        parts.append({"key": k, "label": LABEL[k], "minutes": mins, "count": n, "done": d,
                      "done_minutes": round(min(d, n * 2) * COST[k]), "unit": UNIT[k], "link": LINK[k],
                      "left": max(0, n - d)})
    planned = sum(p["minutes"] for p in parts)
    done_m = sum(min(p["done_minutes"], p["minutes"]) for p in parts)
    # today: the part furthest behind where it should be by now
    expect = (day_i + 1) / 7
    behind = sorted(parts, key=lambda p: (p["done"] / p["count"]) - expect)
    nxt = next((p for p in behind if p["left"]), None)
    return {"enabled": True, "asked": True, "minutes": minutes, "week": a, "parts": parts, "planned": planned, "done": done_m,
            "reasons": reasons, "next": {"key": nxt["key"], "label": nxt["label"], "link": nxt["link"],
                                          "count": max(1, round(nxt["left"] / max(1, 7 - day_i)))} if nxt else None}
