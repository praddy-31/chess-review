"""
Opening study: your repertoire learnt line by line (the Openings redesign, Oct 4).

A line runs from the start position to the end of your repertoire: your
starred move at each of your turns, and every opponent reply that leads to
another starred position branches into its own line. Lines are rebuilt from
the `repertoire` table whenever it changes; a line that grows keeps its
progress (and comes back for review so you see the new moves).

States of one line:
  new       in the repertoire, not studied
  learning  studied today; same-day steps: again ~10 minutes later, then at
            the end of the session
  review    due after 1, 3, 7, 16, 35, 80, 180 days, one step further after
            each clean recall; a miss sends it back to the same-day steps
  learned   (a flag on review lines) recalled cleanly 7+ days after you
            learned it

Daily numbers: new lines per day (Settings, 3); every due review. Extra
rounds after that are logged as practice and don't move the schedule.

Games: when a new game of yours leaves a line you are reviewing at one of
your moves, that line moves one step back (due in 7 days -> due in 3).
"""

from __future__ import annotations

import datetime as _dt
import json
import time
from typing import Optional

import chess

import store
from chess_analysis import _epd, openings

LADDER = [1, 3, 7, 16, 35, 80, 180]       # review intervals in days
STEP1_SECONDS = 600                        # the first same-day step
MISS_SECONDS = 60                          # a missed line comes back almost at once
LEARNED_AFTER_DAYS = 7
MAX_LINES = 800                            # per colour
MAX_PLIES = 80

SCHEMA = """
CREATE TABLE IF NOT EXISTS rep_lines (
    color TEXT NOT NULL, key TEXT NOT NULL,          -- key = the line's moves, UCI, comma-joined
    opening TEXT, moves TEXT NOT NULL, san TEXT NOT NULL, mine INTEGER NOT NULL,
    start INTEGER NOT NULL DEFAULT 0,                -- moves before this are played in for you (repertoire starts later)
    freq INTEGER NOT NULL DEFAULT 0,                 -- your games that reached the end of the line
    state TEXT NOT NULL DEFAULT 'new', step INTEGER NOT NULL DEFAULT 0, due REAL,
    ladder INTEGER NOT NULL DEFAULT 0, learned_on TEXT, learned INTEGER NOT NULL DEFAULT 0,
    reps INTEGER NOT NULL DEFAULT 0, lapses INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL, last_at REAL,
    PRIMARY KEY (color, key)
);
CREATE TABLE IF NOT EXISTS study_log (color TEXT, key TEXT, day TEXT, kind TEXT, result TEXT, at REAL);
CREATE TABLE IF NOT EXISTS study_openings (            -- openings you chose to learn, with their length
    color TEXT NOT NULL, opening TEXT NOT NULL, moves TEXT NOT NULL, level INTEGER NOT NULL DEFAULT 3,
    added REAL NOT NULL, PRIMARY KEY (color, opening)
);
CREATE TABLE IF NOT EXISTS explorer_cache (fen TEXT PRIMARY KEY, data TEXT NOT NULL, at REAL NOT NULL);
"""


def ensure_schema(con) -> None:
    import repertoire as rp
    rp.ensure_schema(con)
    con.executescript(SCHEMA)


def today() -> str:
    return _dt.date.today().isoformat()


def day_start(day: str) -> float:
    return time.mktime(_dt.date.fromisoformat(day).timetuple())


def in_days(n: int) -> float:
    return day_start((_dt.date.today() + _dt.timedelta(days=n)).isoformat())


def end_of_today() -> float:
    return in_days(1) - 1


# ---------------------------------------------------------------------------
# line length for an opening you learn: a 1-5 scale around your rating
# ---------------------------------------------------------------------------

LEVELS = {1: "Short", 2: "Shorter", 3: "Recommended", 4: "Longer", 5: "To the end of theory"}


def level_moves(level: int, rating: Optional[int]) -> int:
    """Your moves per line at each level; 3 is the rating-based recommendation."""
    import repertoire as rp
    cap = rp.depth_cap(rating)
    return {1: max(3, cap - 4), 2: max(4, cap - 2), 3: cap, 4: cap + 4}.get(int(level), 30)


def levels(rating: Optional[int]) -> list[dict]:
    return [{"level": k, "name": v, "moves": level_moves(k, rating) if k < 5 else None} for k, v in LEVELS.items()]


# ---------------------------------------------------------------------------
# lines from the repertoire
# ---------------------------------------------------------------------------

def _family(name: str) -> str:
    n = name[4:] if len(name) > 4 and name[0] in "ABCDE" and name[1:3].isdigit() and name[3] == " " else name
    return n.split(":")[0].split(",")[0].strip()


def enumerate_lines(color: str, rep: dict) -> list[dict]:
    """Every line through `rep` ({epd: row}) as {moves, san, mine, opening}."""
    mine_turn = chess.WHITE if color == "White" else chess.BLACK
    out: list[dict] = []
    names = openings()

    visited: set = set()

    def emit(moves, sans, mine, opening, named, start):
        if mine and len(out) < MAX_LINES:
            out.append({"moves": list(moves), "san": list(sans), "mine": mine, "start": start,
                        "opening": opening or (f"{named[0]} {named[1]}" if named else None)})

    def walk(b, moves, sans, mine, opening, named, seen, start):
        if len(out) >= MAX_LINES:
            return
        if len(moves) >= MAX_PLIES:
            return emit(moves, sans, mine, opening, named, start)
        e = _epd(b.fen())
        if b.turn == mine_turn:
            r = rep.get(e)
            if r is None or e in seen:
                return emit(moves, sans, mine, opening, named, start)
            visited.add(e)
            mv = chess.Move.from_uci(r["uci"])
            if mv not in b.legal_moves:
                return emit(moves, sans, mine, opening, named, start)
            san = b.san(mv)
            nb = b.copy(stack=False)
            nb.push(mv)
            hit = names.get(_epd(nb.fen()))
            walk(nb, moves + [r["uci"]], sans + [san], mine + 1, r["opening"] or opening, hit or named, seen | {e}, start)
        else:
            nexts = []
            for mv in b.legal_moves:
                nb = b.copy(stack=False)
                nb.push(mv)
                if _epd(nb.fen()) in rep:
                    nexts.append((mv, nb))
            if not nexts:
                return emit(moves, sans, mine, opening, named, start)
            for mv, nb in nexts:
                hit = names.get(_epd(nb.fen()))
                walk(nb, moves + [mv.uci()], sans + [b.san(mv)], mine, opening, hit or named, seen, start)

    walk(chess.Board(), [], [], 0, None, None, frozenset(), 0)
    # repertoire moves the start can't reach (an opening learnt from move 3, say): lines start there,
    # with the moves before it played in for you
    roots = sorted((r for e, r in rep.items() if e not in visited and r.get("path") is not None),
                   key=lambda r: len(json.loads(r["path"])))
    for r in roots:
        if _epd(r["fen"]) in visited or len(out) >= MAX_LINES:
            continue
        pre = json.loads(r["path"])
        b, sans, named = chess.Board(), [], None
        try:
            for u in pre:
                mv = chess.Move.from_uci(u)
                sans.append(b.san(mv)); b.push(mv)
                named = names.get(_epd(b.fen())) or named
        except Exception:
            continue
        walk(b, list(pre), sans, 0, r["opening"], named, frozenset(), len(pre))
    return out


def sync_lines(color: str) -> dict:
    """Rebuilds the lines of one colour from the repertoire, keeping each line's progress."""
    import repertoire as rp
    with store.db() as con:
        ensure_schema(con)
        rep = {r["epd"]: dict(r) for r in con.execute("SELECT epd, uci, opening, reps, due, fen, path FROM repertoire WHERE color = ?", (color,))}
        # openings learnt before Oct 4 have no study_openings row yet: add them at the recommended length
        for r in con.execute("SELECT opening, MIN(LENGTH(path)), created added, path FROM repertoire WHERE color = ? AND opening IS NOT NULL "
                             "AND opening NOT IN (SELECT opening FROM study_openings WHERE color = ?) GROUP BY opening", (color, color)).fetchall():
            con.execute("INSERT OR IGNORE INTO study_openings (color, opening, moves, level, added) VALUES (?,?,?,3,?)",
                        (color, r["opening"], r["path"], r["added"]))
        old = {r["key"]: dict(r) for r in con.execute("SELECT * FROM rep_lines WHERE color = ?", (color,))}
    lines = enumerate_lines(color, rep)
    now = time.time()
    keys = set()
    rows = []
    for ln in lines:
        key = ",".join(ln["moves"])
        keys.add(key)
        b = chess.Board()
        for u in ln["moves"]:
            b.push(chess.Move.from_uci(u))
        ln["key"], ln["final_z"] = key, rp.zkey(b)
        rows.append(ln)
    # your games that reached each line's end (what you meet most comes first)
    with store.db() as con:
        freq = {}
        zs = list({ln["final_z"] for ln in rows})
        for i in range(0, len(zs), 500):
            chunk = zs[i:i + 500]
            q = ",".join("?" * len(chunk))
            for r in con.execute(f"SELECT m.z_after AS z, COUNT(*) n FROM op_moves m JOIN games g ON g.okey = m.g "
                                 f"WHERE m.z_after IN ({q}) AND g.player_color = ? GROUP BY m.z_after", (*chunk, color)):
                freq[r["z"]] = r["n"]
        added = kept = grown = 0
        for ln in rows:
            st = old.get(ln["key"])
            f = freq.get(ln["final_z"], 0)
            if st:
                con.execute("UPDATE rep_lines SET opening = ?, san = ?, mine = ?, freq = ?, start = ? WHERE color = ? AND key = ?",
                            (ln["opening"], json.dumps(ln["san"]), ln["mine"], f, ln["start"], color, ln["key"]))
                kept += 1
                continue
            parent = max((o for k, o in old.items() if k not in keys and ln["key"].startswith(k + ",")),
                         key=lambda o: len(o["key"]), default=None)
            if parent:       # the line grew: keep its progress, review the new moves soon
                due = parent["due"]
                if parent["state"] == "review":
                    due = min(due or now, end_of_today())
                con.execute("INSERT INTO rep_lines (color, key, opening, moves, san, mine, start, freq, state, step, due, ladder, learned_on, "
                            "learned, reps, lapses, created, last_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (color, ln["key"], ln["opening"], json.dumps(ln["moves"]), json.dumps(ln["san"]), ln["mine"], ln["start"], f,
                             parent["state"], parent["step"], due, parent["ladder"], parent["learned_on"], 0,
                             parent["reps"], parent["lapses"], now, parent["last_at"]))
                grown += 1
            else:
                state, ladder, due, learned_on = _seed_from_drills(ln, rep)
                con.execute("INSERT INTO rep_lines (color, key, opening, moves, san, mine, start, freq, state, due, ladder, learned_on, created) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (color, ln["key"], ln["opening"], json.dumps(ln["moves"]), json.dumps(ln["san"]), ln["mine"], ln["start"], f,
                             state, due, ladder, learned_on, now))
                added += 1
        gone = [k for k in old if k not in keys]
        for i in range(0, len(gone), 500):
            chunk = gone[i:i + 500]
            con.execute(f"DELETE FROM rep_lines WHERE color = ? AND key IN ({','.join('?' * len(chunk))})", (color, *chunk))
    return {"lines": len(rows), "added": added, "kept": kept, "grown": grown, "removed": len(gone)}


def _seed_from_drills(ln: dict, rep: dict) -> tuple:
    """A new line whose every move you already drilled starts in review (from the old per-move drills)."""
    b = chess.Board()
    reps, dues = [], []
    for u in ln["moves"]:
        r = rep.get(_epd(b.fen()))
        if r is not None and r["uci"] == u:
            reps.append(r["reps"] or 0)
            if r["due"]:
                dues.append(r["due"])
        b.push(chess.Move.from_uci(u))
    if not reps or min(reps) == 0:
        return "new", 0, None, None
    ladder = min(min(reps) - 1, 2)
    due = day_start(min(dues)) if dues else in_days(1)
    return "review", ladder, due, today()


def sync_all() -> None:
    for c in ("White", "Black"):
        sync_lines(c)


# ---------------------------------------------------------------------------
# what to study now
# ---------------------------------------------------------------------------

def _line(r) -> dict:
    d = dict(r)
    d["moves"] = json.loads(d["moves"])
    d["san"] = json.loads(d["san"])
    return d


def _chosen(con) -> set:
    return {(r["color"], r["opening"]) for r in con.execute("SELECT color, opening FROM study_openings")}


def card_name(color: str, opening: Optional[str], chosen: set) -> str:
    """The card a line belongs to: an opening you chose by its exact name, else its family ("Pirc Defense")."""
    if not opening:
        return "Other lines"
    return opening if (color, opening) in chosen else _family(opening)


def queue(color: str = "", opening: str = "", more: int = 0, practice: bool = False) -> dict:
    """Today's session: same-day steps that are due, reviews due today, then new lines up to the daily number
    (plus `more` extra new lines), and the end-of-session step last. `practice`: up to 10 lines you have
    studied, picked at random, for extra rounds that don't move the schedule."""
    import random
    s = store.get_settings()
    per_day = max(0, int(s.get("new_lines_per_day", 3) or 0))
    now, eod, day = time.time(), end_of_today(), today()
    w, a = "1", []
    if color:
        w += " AND color = ?"; a.append(color)
    with store.db() as con:
        ensure_schema(con)
        chosen = _chosen(con)
        keep = (lambda r: card_name(r["color"], r["opening"], chosen) == opening) if opening else (lambda r: True)
        learned_today = con.execute("SELECT COUNT(DISTINCT color || key) FROM study_log WHERE day = ? AND kind = 'learn'", (day,)).fetchone()[0]
        if practice:
            pool = [_line(r) for r in con.execute(f"SELECT * FROM rep_lines WHERE {w} AND state != 'new'", a) if keep(r)]
            random.shuffle(pool)
            return {"day": day, "per_day": per_day, "learned_today": learned_today, "queue": [dict(x, mode="practice") for x in pool[:10]],
                    "reviews_due": 0, "steps_due": 0, "waiting": 0, "next_step_at": None, "new_left": 0, "new_total": 0}
        steps = [_line(r) for r in con.execute(f"SELECT * FROM rep_lines WHERE {w} AND state = 'learning' ORDER BY due", a) if keep(r)]
        reviews = [_line(r) for r in con.execute(f"SELECT * FROM rep_lines WHERE {w} AND state = 'review' AND due <= ? ORDER BY due, freq DESC", (*a, eod)) if keep(r)]
        news = [_line(r) for r in con.execute(f"SELECT * FROM rep_lines WHERE {w} AND state = 'new' ORDER BY freq DESC, mine, created", a) if keep(r)]
    left = max(0, per_day - learned_today) + max(0, int(more))
    waiting = [x for x in steps if x["due"] and x["due"] > now]          # the 10-minute step, not yet
    soon = [x for x in steps if not x["due"] or x["due"] <= now]
    first = [x for x in soon if x["step"] <= 1]
    last = [x for x in soon if x["step"] >= 2]
    items = ([dict(x, mode="step") for x in first] + [dict(x, mode="review") for x in reviews]
             + [dict(x, mode="learn") for x in news[:left]] + [dict(x, mode="step") for x in last])
    return {"day": day, "per_day": per_day, "learned_today": learned_today, "queue": items,
            "reviews_due": len(reviews), "steps_due": len(soon), "waiting": len(waiting),
            "next_step_at": min((x["due"] for x in waiting), default=None),
            "new_left": max(0, len(news) - left) if left < len(news) else 0, "new_total": len(news)}


def result(color: str, key: str, clean: bool, practice: bool = False) -> dict:
    """Records one pass through a line and moves it along (see the module notes)."""
    now, day = time.time(), today()
    with store.db() as con:
        ensure_schema(con)
        r = con.execute("SELECT * FROM rep_lines WHERE color = ? AND key = ?", (color, key)).fetchone()
        if r is None:
            raise KeyError(key)
        r = dict(r)
        if practice:
            con.execute("INSERT INTO study_log VALUES (?,?,?,?,?,?)", (color, key, day, "practice", "clean" if clean else "miss", now))
            return {"state": r["state"], "due": r["due"], "practice": True}
        st, step, ladder, learned, learned_on = r["state"], r["step"], r["ladder"], r["learned"], r["learned_on"]
        reps, lapses = r["reps"], r["lapses"]
        if st == "new":
            kind = "learn"
            st, step, due = "learning", (1 if clean else 0), now + (STEP1_SECONDS if clean else MISS_SECONDS)
        elif st == "learning":
            kind = "step"
            if not clean:
                step, due = 1, now + MISS_SECONDS
            elif step <= 0:
                step, due = 1, now + STEP1_SECONDS
            elif step == 1:
                step, due = 2, now                       # once more at the end of the session
            else:
                st, step, ladder, due = "review", 0, 0, in_days(LADDER[0])
                learned_on = learned_on or day
        else:
            kind = "review"
            if clean:
                reps += 1
                if learned_on and (_dt.date.today() - _dt.date.fromisoformat(learned_on)).days >= LEARNED_AFTER_DAYS:
                    learned = 1
                ladder = min(ladder + 1, len(LADDER) - 1)
                due = in_days(LADDER[ladder])
            else:
                lapses += 1
                st, step, ladder, learned, due = "learning", 1, 0, 0, now + MISS_SECONDS
        con.execute("UPDATE rep_lines SET state=?, step=?, due=?, ladder=?, learned=?, learned_on=?, reps=?, lapses=?, last_at=? "
                    "WHERE color = ? AND key = ?", (st, step, due, ladder, learned, learned_on, reps, lapses, now, color, key))
        con.execute("INSERT INTO study_log VALUES (?,?,?,?,?,?)", (color, key, day, kind, "clean" if clean else "miss", now))
    return {"state": st, "step": step, "due": due, "learned": bool(learned), "interval": LADDER[ladder] if st == "review" else 0}


# ---------------------------------------------------------------------------
# the overview: one card per opening
# ---------------------------------------------------------------------------

def overview() -> dict:
    now, eod = time.time(), end_of_today()
    with store.db() as con:
        ensure_schema(con)
        rows = [dict(r) for r in con.execute("SELECT color, key, opening, state, learned, due, freq, mine FROM rep_lines")]
        chosen = {(r["color"], r["opening"]): dict(r) for r in con.execute("SELECT * FROM study_openings")}
        week = con.execute("SELECT kind, result FROM study_log WHERE at >= ? AND kind IN ('step', 'review')", (now - 7 * 86400,)).fetchall()
    cards: dict = {}
    for r in rows:
        name = r["opening"] or "Other lines"
        fam = card_name(r["color"], r["opening"], set(chosen))
        c = cards.setdefault((r["color"], fam), {"color": r["color"], "opening": fam, "chosen": (r["color"], name) in chosen,
                                                 "lines": 0, "new": 0, "learning": 0, "learned": 0, "due": 0, "games": 0})
        c["lines"] += 1
        c["games"] += r["freq"] or 0
        if r["state"] == "new":
            c["new"] += 1
        elif r["learned"]:
            c["learned"] += 1
        else:
            c["learning"] += 1
        if (r["state"] == "learning" and (r["due"] or 0) <= now) or (r["state"] == "review" and (r["due"] or 0) <= eod):
            c["due"] += 1
    for (color, name), o in chosen.items():
        c = cards.get((color, name))
        if c:
            c["level"] = o["level"]
            c["path"] = json.loads(o["moves"])
    out = sorted(cards.values(), key=lambda c: (not c["chosen"], -(c["due"] + c["learning"]), -c["games"]))
    q = queue()
    recall = [w["result"] for w in week]
    return {"openings": out, "reviews_due": q["reviews_due"] + q["steps_due"], "new_today": sum(1 for x in q["queue"] if x["mode"] == "learn"),
            "waiting": q["waiting"], "next_step_at": q["next_step_at"],
            "recall_7d": round(100 * recall.count("clean") / len(recall)) if recall else None,
            "per_day": q["per_day"]}


def lines_of(color: str, opening: str) -> list[dict]:
    """The lines on one card (by family name, or an opening you chose by its exact name)."""
    with store.db() as con:
        ensure_schema(con)
        rows = [_line(r) for r in con.execute("SELECT * FROM rep_lines WHERE color = ? ORDER BY key", (color,))]
        chosen = _chosen(con)
    return [r for r in rows if card_name(color, r["opening"], chosen) == opening]


def make_due(color: str, key: str = "", prefix: Optional[list] = None) -> int:
    """Makes a line (or every studied line through `prefix`) due now."""
    with store.db() as con:
        ensure_schema(con)
        if prefix is not None:
            p = ",".join(prefix)
            return con.execute("UPDATE rep_lines SET due = ? WHERE color = ? AND state = 'review' AND (key = ? OR key LIKE ?)",
                               (time.time(), color, p, p + ",%")).rowcount
        return con.execute("UPDATE rep_lines SET due = ? WHERE color = ? AND key = ? AND state != 'new'", (time.time(), color, key)).rowcount


# ---------------------------------------------------------------------------
# your games: deviations
# ---------------------------------------------------------------------------

def apply_games() -> int:
    """New games that left a line you review at one of your moves move that line one step back.
    Runs over games imported since the last call; returns how many lines moved."""
    import repertoire as rp
    last = float(store.get_meta("study_games_at") or 0)
    with store.db() as con:
        ensure_schema(con)
        games = con.execute("SELECT id, okey, player_color, played_at, imported_at FROM games WHERE imported_at > ? AND player_color IS NOT NULL AND source != 'maia'",
                            (last,)).fetchall()
        if not games:
            return 0
        newest = max(g["imported_at"] for g in games)
        moved = 0
        for color in ("White", "Black"):
            rep = {}
            for r in con.execute("SELECT fen, uci FROM repertoire WHERE color = ?", (color,)):
                rep[rp.zkey(chess.Board(r["fen"]))] = r["uci"]
            if not rep:
                continue
            lines = [dict(r) for r in con.execute("SELECT key, moves, ladder, due, learned_on FROM rep_lines WHERE color = ? AND state = 'review'", (color,))]
            if not lines:
                continue
            for g in games:
                if g["player_color"] != color or g["okey"] is None:
                    continue
                mv = con.execute("SELECT ply, z, uci FROM op_moves WHERE g = ? ORDER BY ply", (g["okey"],)).fetchall()
                prefix = []
                for m in mv:
                    if m["z"] in rep and m["uci"] != rep[m["z"]]:
                        pre = ",".join(prefix)
                        day = (g["played_at"] or "")[:10]
                        for ln in lines:
                            if (ln["key"] == pre or ln["key"].startswith(pre + ",") if pre else True) and (not ln["learned_on"] or day >= ln["learned_on"]):
                                lad = max(0, ln["ladder"] - 1)
                                due = min(ln["due"] or time.time(), in_days(LADDER[lad]))
                                con.execute("UPDATE rep_lines SET ladder = ?, due = ? WHERE color = ? AND key = ?", (lad, due, color, ln["key"]))
                                ln["ladder"], ln["due"] = lad, due
                                moved += 1
                        break
                    prefix.append(m["uci"])
    store.set_meta("study_games_at", repr(newest))
    return moved


def deviations(days: int = 30, limit: int = 12) -> list[dict]:
    """Recent games where you or your opponent left your repertoire: who, where, what was played."""
    import repertoire as rp
    since = time.strftime("%Y-%m-%d", time.gmtime(time.time() - days * 86400))
    out = []
    with store.db() as con:
        ensure_schema(con)
        for color in ("White", "Black"):
            rep = {}
            for r in con.execute("SELECT fen, uci, san FROM repertoire WHERE color = ?", (color,)):
                rep[rp.zkey(chess.Board(r["fen"]))] = (r["uci"], r["san"])
            if not rep:
                continue
            games = con.execute("SELECT id, okey, white, black, played_at, result FROM games WHERE player_color = ? AND played_at >= ? AND source != 'maia' "
                                "ORDER BY played_at DESC LIMIT 200", (color, since)).fetchall()
            for g in games:
                mv = con.execute("SELECT ply, z, uci, san, z_after FROM op_moves WHERE g = ? ORDER BY ply", (g["okey"],)).fetchall()
                met, prefix = False, []
                for i, m in enumerate(mv):
                    mine = (m["ply"] % 2 == 1) == (color == "White")     # ply 1 = White's first move
                    if mine:
                        if m["z"] in rep:
                            met = True
                            if m["uci"] != rep[m["z"]][0]:
                                out.append({"who": "you", "color": color, "game_id": g["id"], "played_at": g["played_at"],
                                            "opponent": g["black"] if color == "White" else g["white"], "moves": list(prefix),
                                            "played": m["san"], "planned": rep[m["z"]][1], "ply": m["ply"]})
                                break
                        elif met:
                            break               # past the end of your line
                    elif met and m["z_after"] not in rep and i + 1 < len(mv):
                        # their reply leads to a position where you have no move: a reply your repertoire doesn't cover
                        out.append({"who": "they", "color": color, "game_id": g["id"], "played_at": g["played_at"],
                                    "opponent": g["black"] if color == "White" else g["white"], "moves": list(prefix),
                                    "played": m["san"], "uci": m["uci"], "ply": m["ply"]})
                        break
                    prefix.append(m["uci"])
    out.sort(key=lambda d: d["played_at"] or "", reverse=True)
    for d in out[:limit]:
        b = chess.Board()
        sans = []
        for u in d["moves"]:
            mv = chess.Move.from_uci(u)
            sans.append(b.san(mv)); b.push(mv)
        d["san"] = sans
        d["fen"] = b.fen()
    return out[:limit]


# ---------------------------------------------------------------------------
# Insights: one row per opening
# ---------------------------------------------------------------------------

def insights() -> list[dict]:
    ov = overview()["openings"]
    now = time.time()
    with store.db() as con:
        ensure_schema(con)
        logs = con.execute("SELECT l.color, l.key, l.result, r.opening FROM study_log l JOIN rep_lines r ON r.color = l.color AND r.key = l.key "
                           "WHERE l.at >= ? AND l.kind IN ('step', 'review')", (now - 7 * 86400,)).fetchall()
    rec: dict = {}
    for l in logs:
        name = l["opening"] or "Other lines"
        for c in ov:
            if c["color"] == l["color"] and (c["opening"] == name or c["opening"] == _family(name)):
                v = rec.setdefault((c["color"], c["opening"]), [0, 0])
                v[0] += l["result"] == "clean"
                v[1] += 1
                break
    out = []
    for c in ov:
        if c["new"] == c["lines"]:
            continue
        r = rec.get((c["color"], c["opening"]))
        out.append({"color": c["color"], "opening": c["opening"], "lines": c["lines"], "learned": c["learned"],
                    "recall_7d": round(100 * r[0] / r[1]) if r else None, "attempts_7d": r[1] if r else 0})
    return out


# ---------------------------------------------------------------------------
# Lichess opening explorer (optional, off by default; needs your Lichess token)
# ---------------------------------------------------------------------------

EXPLORER = "https://explorer.lichess.org/lichess"
BUCKETS = [0, 1000, 1200, 1400, 1600, 1800, 2000, 2200, 2500]


def explorer(fen: str) -> Optional[dict]:
    """Replies played at your level on Lichess (blitz and rapid), cached for 30 days. None when switched off."""
    s = store.get_settings()
    if not s.get("explorer_lookup") or not (s.get("explorer_token") or "").strip():
        return None
    with store.db() as con:
        ensure_schema(con)
        hit = con.execute("SELECT data, at FROM explorer_cache WHERE fen = ?", (fen,)).fetchone()
    if hit and time.time() - hit["at"] < 30 * 86400:
        return json.loads(hit["data"])
    import urllib.error
    import urllib.parse
    import urllib.request
    from chess_analysis import USER_AGENT
    r = store.my_rating(settings=s)
    lo = max(b for b in BUCKETS if b <= r)
    nxt = [b for b in BUCKETS if b > lo]
    bands = [lo] + nxt[:1]
    url = EXPLORER + "?" + urllib.parse.urlencode({"fen": fen, "ratings": ",".join(map(str, bands)), "speeds": "blitz,rapid", "topGames": 0, "recentGames": 0})
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + s["explorer_token"].strip(), "User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": "Lichess refused the token (check it in Settings)" if e.code in (401, 403) else f"Lichess explorer: HTTP {e.code}"}
    except Exception as e:
        return {"error": f"Lichess explorer unreachable ({e.__class__.__name__})"}
    total = sum(m.get("white", 0) + m.get("draws", 0) + m.get("black", 0) for m in raw.get("moves", [])) or 1
    data = {"bands": bands, "games": total, "moves": [
        {"uci": m["uci"], "san": m["san"], "n": m.get("white", 0) + m.get("draws", 0) + m.get("black", 0),
         "share": round(100 * (m.get("white", 0) + m.get("draws", 0) + m.get("black", 0)) / total)} for m in raw.get("moves", [])[:8]]}
    with store.db() as con:
        con.execute("INSERT OR REPLACE INTO explorer_cache VALUES (?,?,?)", (fen, json.dumps(data), time.time()))
    return data
