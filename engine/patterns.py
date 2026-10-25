"""
Recurring mistakes (V7): your errors grouped by what went wrong, across all
analysed games.

Each of your Mistakes and Blunders is read with the motif detector (the same
one behind the one-line verdicts): what the opponent's best reply does to you
(you walk into a fork, leave a piece hanging...). Missed chances are grouped by
what you missed. A pattern needs 3+ cases. For each: how often (per 10
analysed games), lately (last 30 days) against before, the most common detail
("knight fork"), recent examples, and the puzzles made from those positions so
you can practise exactly them.

Each game is read once and its cases kept in `pattern_cases` until it is re-analysed
or the grading changes, so a new game costs a fraction of a second.
"""

from __future__ import annotations

import json
import threading
import time
from collections import Counter

import store

ALLOWED = {
    "fork": "You walk into forks",
    "hanging piece": "You leave pieces hanging",
    "pin": "You walk into pins",
    "discovered check": "You allow discovered checks",
    "mate": "You walk into mating attacks",
    "back-rank mate": "Your back rank is weak",
    "promotion": "You let pawns through",
    "material": "You lose material in exchanges",
}
MISSED = {
    "fork": "You miss forks",
    "hanging piece": "You miss free pieces",
    "pin": "You miss pins",
    "discovered check": "You miss discovered checks",
    "mate": "You miss mates",
    "back-rank mate": "You miss back-rank mates",
    "promotion": "You miss promotions",
    "material": "You miss winning material",
}
MIN_CASES = 3


SCHEMA = "CREATE TABLE IF NOT EXISTS pattern_cases (game_id TEXT PRIMARY KEY, stamp TEXT NOT NULL, cases TEXT NOT NULL)"


def _detail(kind: str, d: str):
    if not d or kind == "allowed":
        return d
    return ("winning " + d[6:]) if d.startswith("loses ") else ("a free " + d[8:]) if d.startswith("hangs a ") else d


def _cases(review_json: str, th) -> list:
    """Your errors in one game, as (kind, motif, detail, pp, ply, move, verdict, severity)."""
    from payload import review_payload
    pl = review_payload(store.review_from_json(review_json, th))
    me = pl["player"]
    out = []
    for d in pl["plies"]:
        if d.get("color") != me or not d.get("flagged") or not d.get("explain"):
            continue
        ex = d["explain"]
        sev = d.get("severity")
        if sev in ("Mistake", "Blunder") and ex.get("motif_ref"):
            kind, motif, detail = "allowed", ex["motif_ref"], ex.get("short_ref")
        elif d.get("missed") and ex.get("motif_best"):
            kind, motif, detail = "missed", ex["motif_best"], ex.get("short_best")
        else:
            continue
        out.append([kind, motif, _detail(kind, detail), d.get("pp") or 0, d["ply"], f"{d.get('label', '')}{d.get('san', '')}", ex.get("verdict"), sev])
    return out


_LOCK = threading.Lock()


def build(force: bool = False) -> dict:
    """Patterns over all analysed games; each game is read once (until it is re-analysed or the grading changes)."""
    with _LOCK:            # the start-up warm-up and a request may arrive together
        return _build_locked(force)


def _build_locked(force: bool) -> dict:
    th = store.thresholds_from(store.get_settings())
    with store.db() as con:
        con.execute(SCHEMA)
        have = {r["game_id"]: r["stamp"] for r in con.execute("SELECT game_id, stamp FROM pattern_cases")}
        todo = [(r["game_id"], f"{r['analysed_at']}|{store.GRADING_VERSION}") for r in con.execute("SELECT game_id, analysed_at FROM reviews")]
    stale = [(g, st) for g, st in todo if force or have.get(g) != st]
    for gid, st in stale:
        with store.db() as con:
            r = con.execute("SELECT review_json FROM reviews WHERE game_id = ?", (gid,)).fetchone()
        try:
            cs = _cases(r["review_json"], th) if r else []
        except Exception:
            cs = []
        with store.db() as con:
            con.execute("INSERT OR REPLACE INTO pattern_cases VALUES (?,?,?)", (gid, st, json.dumps(cs)))
    bots = store.maia_counted()     # read before the connection below: a second one would wait on its write
    with store.db() as con:
        con.execute("DELETE FROM pattern_cases WHERE game_id NOT IN (SELECT game_id FROM reviews)")
        rows = con.execute("SELECT p.game_id, p.cases, g.played_at, g.white, g.black, g.player_color FROM pattern_cases p "
                           "JOIN games g ON g.id = p.game_id" + ("" if bots else " WHERE g.source != 'maia'")).fetchall()
        puzzle_ids = {r[0] for r in con.execute("SELECT id FROM puzzles WHERE source = 'mine' OR from_retry = 1")}
    since = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 30 * 86400))
    games_recent = games_before = 0
    groups: dict = {}
    for r in rows:
        recent = (r["played_at"] or "") >= since
        games_recent += recent
        games_before += not recent
        opp = r["black"] if r["player_color"] == "White" else r["white"]
        for kind, motif, detail, pp, ply, move, verdict, sev in json.loads(r["cases"]):
            title = (ALLOWED if kind == "allowed" else MISSED).get(motif)
            if not title:
                continue
            g = groups.setdefault((kind, motif), {"kind": kind, "motif": motif, "title": title, "n": 0, "recent": 0, "before": 0,
                                                  "games": set(), "details": Counter(), "examples": [], "pp": 0.0})
            g["n"] += 1
            g["recent" if recent else "before"] += 1
            g["games"].add(r["game_id"])
            if detail:
                g["details"][detail] += 1
            g["pp"] += pp
            pid = f"{r['game_id']}:{ply}"
            g["examples"].append({"game_id": r["game_id"], "ply": ply, "move": move, "verdict": verdict, "opponent": opp,
                                  "date": (r["played_at"] or "")[:10], "severity": sev, "puzzle": pid if pid in puzzle_ids else None})
    analysed = games_recent + games_before
    out = []
    for g in groups.values():
        if g["n"] < MIN_CASES:
            continue
        g["examples"].sort(key=lambda e: e["date"], reverse=True)
        rate_recent = 10 * g["recent"] / games_recent if games_recent else None
        rate_before = 10 * g["before"] / games_before if games_before else None
        trend = None
        if rate_recent is not None and rate_before is not None and g["before"] + g["recent"] >= 4:
            trend = "better" if rate_recent < 0.7 * rate_before else "worse" if rate_recent > 1.3 * rate_before else "same"
        out.append({"kind": g["kind"], "motif": g["motif"], "title": g["title"], "n": g["n"], "games": len(g["games"]),
                    "per10": round(10 * g["n"] / analysed, 1) if analysed else 0,
                    "recent_per10": None if rate_recent is None else round(rate_recent, 1),
                    "before_per10": None if rate_before is None else round(rate_before, 1), "trend": trend,
                    "detail": g["details"].most_common(1)[0][0] if g["details"] else None,
                    "cost": round(g["pp"] / g["n"]), "examples": g["examples"][:6],
                    "puzzles": [e["puzzle"] for e in g["examples"] if e["puzzle"]]})
    out.sort(key=lambda p: (-p["n"] * p["cost"], -p["n"]))
    for p in out:          # the puzzles: every case of the pattern that has one, not only the examples shown
        p["puzzles"] = [f"{e['game_id']}:{e['ply']}" for e in groups[(p["kind"], p["motif"])]["examples"] if e["puzzle"]]
    return {"analysed": analysed, "recent_games": games_recent, "patterns": out[:8]}
