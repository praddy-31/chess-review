"""
Puzzles from your own analysed games (V4), with spaced repetition.

Where they come from (no engine needed - everything is in the stored reviews):
  mine  - a position where you made a mistake or blunder, or missed a chance:
          find the move you should have played.
  opp   - the position right after your opponent's mistake or blunder: find
          the move that punishes it (whether or not you found it in the game).
  retry - a "retry this move" you didn't solve comes back as a puzzle at once.

Two kinds:
  tactic  - the best move is at least CLEAR_GAP points of win chance better
            than the second best (MultiPV 2): one answer to find. A forced
            mate in up to MAX_MATE is always one answer unless the second
            best mates just as fast (win chance tops out near 100%, so a gap
            would call "mate in 1 vs +6" two fine moves); only an equally
            fast mate counts as another solution.
  better  - your own error where several moves were fine: find any move that
            is within 3 points of the best (graded by the engine).
Punish-their-error puzzles are tactics only (otherwise almost any move "keeps
the advantage"). The solution follows the engine's line: your
move, their reply, and more of your moves while they keep forcing (capture,
check, promotion), up to MAX_SOLVER_MOVES. Mates are played out to the end.

Scheduling (a small SM-2): solved without hints -> the gap grows (1, 3, then
x ease days); solved with hints -> a short gap; failed -> back tomorrow.
"""

from __future__ import annotations

import datetime as _dt
import json
import time
from typing import Optional

import chess

import store
from chess_analysis import Thresholds, win_percent

CLEAR_GAP = 10.0
MAX_SOLVER_MOVES = 3
MAX_MATE = 4
SCAN_VERSION = "3"   # 2: explanations (why) for after the puzzle; 3: forced mates are one-answer puzzles
ERRORS = ("Mistake", "Blunder")


def today() -> str:
    return _dt.date.today().isoformat()


def _add_days(day: str, n: float) -> str:
    return (_dt.date.fromisoformat(day) + _dt.timedelta(days=max(1, round(n)))).isoformat()


# ---------------------------------------------------------------------------
# building puzzles from a review
# ---------------------------------------------------------------------------

def _solution(fen: str, sans: list[str], mate_in: Optional[int]) -> tuple[list[str], list[str]]:
    """UCI + SAN of the puzzle line from the engine's best line."""
    b = chess.Board(fen)
    ucis, out_san = [], []
    moves = []
    for s in sans:
        try:
            mv = b.parse_san(s)
        except ValueError:
            break
        moves.append((mv, b.san(mv), b.is_capture(mv) or b.gives_check(mv) or mv.promotion is not None))
        b.push(mv)
    if not moves:
        return [], []
    if mate_in is not None and 0 < mate_in <= MAX_MATE and len(moves) >= 2 * mate_in - 1:
        keep = 2 * mate_in - 1
    else:
        keep = 1
        solver = 1
        # extend with (reply, next solver move) while that next move is forcing
        while solver < MAX_SOLVER_MOVES and keep + 2 <= len(moves) and moves[keep + 1][2]:
            keep += 2
            solver += 1
    for mv, san, _ in moves[:keep]:
        ucis.append(mv.uci())
        out_san.append(san)
    return ucis, out_san


def _motif(fen: str, sans: list[str], cp: Optional[int], mate: Optional[int]) -> str:
    try:
        from motifs import analyse_line
        r = analyse_line(chess.Board(fen), sans, ben_cp=cp, ben_mate=mate if (mate or 0) > 0 else None)
    except Exception:
        return "advantage"
    m = r.get("motif")
    if m in ("mate", "back-rank mate"):
        return m
    if m in (None, "material"):
        return "material" if r.get("gain", 0) >= 1 else "advantage"
    return m


def _uci_line(fen: str, sans: list[str], n: int = 10) -> list[dict]:
    b = chess.Board(fen)
    out = []
    for s in sans[:n]:
        try:
            mv = b.parse_san(s)
        except ValueError:
            break
        lab = f"{b.fullmove_number}{'.' if b.turn else '...'}"
        out.append({"uci": mv.uci(), "san": b.san(mv), "label": lab})
        b.push(mv)
    return out


def _evs(cp, mate) -> str:
    if mate is not None:
        return f"mate in {mate}" if mate > 0 else f"getting mated in {-mate}"
    v = (cp or 0) / 100
    return "0.0" if abs(v) < 0.05 else f"{v:+.1f}"


def _why(p, source: str, opp_move=None) -> dict:
    """What the puzzle's answer does and what the game move allowed, in a line each."""
    from motifs import analyse_line
    line = _uci_line(p.fen_before, p.best_line_san)
    out = {"line": line, "best": "", "played": None}
    if not line:
        return out
    first = line[0]["label"] + line[0]["san"]
    try:
        r = analyse_line(chess.Board(p.fen_before), p.best_line_san, ben_cp=p.cp_before,
                         ben_mate=p.mate_before if (p.mate_before or 0) > 0 else None)
    except Exception:
        r = {}
    if r.get("phrase"):
        out["best"] = f"{first} {r['phrase']}."
    else:
        ev = _evs(p.cp_before, p.mate_before)
        v = 99 if (p.mate_before or 0) > 0 else -99 if p.mate_before is not None else (p.cp_before or 0) / 100
        word = ("wins" if v >= 3 else "keeps a clear edge" if v >= 1 else "keeps it level" if v > -1 else "is the best defence")
        out["best"] = f"{first} {word} ({ev} for you)."
    out["motif_best"] = r.get("motif")
    if source == "mine" and p.played_uci != p.best_uci:
        b = chess.Board(p.fen_before)
        played = chess.Move.from_uci(p.played_uci)
        taken = b.piece_at(played.to_square) if b.is_capture(played) else None
        ref = _uci_line(p.fen_after, p.refutation_san, 6)
        text = ""
        try:
            rr = analyse_line(chess.Board(p.fen_after), p.refutation_san,
                              ben_cp=(-p.cp_after if p.cp_after is not None else None),
                              ben_mate=(-p.mate_after if p.mate_after is not None and p.mate_after < 0 else None),
                              just_lost=(played.to_square, taken.piece_type) if taken else None)
        except Exception:
            rr = {}
        game = f"{p.move_number}{'.' if p.color == 'White' else '...'}{p.played_san}"
        if ref and rr.get("phrase"):
            text = f"Your {game} allowed {ref[0]['label']}{ref[0]['san']}, which {rr['phrase']}."
        elif ref:
            text = (f"Your {game} let them reply {ref[0]['label']}{ref[0]['san']}: "
                    f"{_evs(p.cp_before, p.mate_before)} became {_evs(p.cp_after, p.mate_after)} for you.")
        else:
            text = f"Your {game} kept {_evs(p.cp_after, p.mate_after)} for you, but this was stronger."
        out["played"] = {"uci": p.played_uci, "san": game, "text": text, "reply": ref}
    elif source == "opp" and opp_move is not None:
        out["played"] = {"uci": None, "san": opp_move, "text": f"Their {opp_move} left this open.", "reply": []}
    return out


def _candidate(p, m, source: str, gid: str, before=None) -> Optional[dict]:
    """A puzzle at ply p (PlyData) / m (MoveReview), or None if it isn't clear."""
    if not p.best_line_san or not p.best_uci:
        return None
    if p.second_cp is None and p.second_mate is None:
        return None              # one legal move, or an old review without MultiPV
    if source == "mine" and p.played_uci == p.best_uci:
        return None              # you found it in the game: nothing to practise
    best_win = win_percent(p.cp_before, p.mate_before)
    gap = best_win - win_percent(p.second_cp, p.second_mate)
    if best_win < 40:
        return None              # the best move still loses: nothing to find
    mate_in = p.mate_before if (p.mate_before or 0) > 0 else None
    if mate_in is not None and mate_in <= MAX_MATE:
        # win chance saturates at mate: compare the mates themselves
        kind = "better" if p.second_mate is not None and p.second_mate == mate_in else "tactic"
    else:
        kind = "tactic" if gap >= CLEAR_GAP else "better"
    if kind == "better" and source != "mine":
        return None
    ucis, sans = _solution(p.fen_before, p.best_line_san, mate_in)
    if kind == "better":
        ucis, sans = ucis[:1], sans[:1]
    if not ucis:
        return None
    return {
        "id": f"{gid}:{p.ply}", "game_id": gid, "ply": p.ply, "fen": p.fen_before, "color": p.color,
        "prev_fen": before.fen_before if before else None, "last_uci": before.played_uci if before else None,
        "source": source, "kind": kind, "solution": ucis, "solution_san": sans,
        "motif": _motif(p.fen_before, p.best_line_san, p.cp_before, p.mate_before),
        "severity": m.severity, "played_san": p.played_san,
        "label": f"{p.move_number}{'.' if p.color == 'White' else '...'}", "win_gap": round(gap, 1),
        "why": _why(p, source),
    }


def from_review(gid: str, rv) -> list[dict]:
    """All puzzle candidates in one game, yours and the punish-their-error ones."""
    by_ply = {p.ply: p for p in rv.raw}
    mv = {m.ply: m for m in rv.moves + rv.opp_moves}
    out = []
    for m in rv.moves:
        if m.severity in ERRORS or m.missed_opportunity:
            c = _candidate(by_ply[m.ply], m, "mine", gid, by_ply.get(m.ply - 1))
            if c:
                out.append(c)
    for o in rv.opp_moves:
        if o.severity not in ERRORS:
            continue
        nxt = by_ply.get(o.ply + 1)
        if nxt is None or nxt.ply not in mv:
            continue
        c = _candidate(nxt, mv[nxt.ply], "opp", gid, by_ply.get(o.ply))
        if c:   # describe it by their error, the thing you punish
            c["severity"], c["played_san"] = o.severity, f"{o.move_number}{'.' if o.color == 'White' else '...'}{o.played_san}"
            c["why"] = _why(nxt, "opp", c["played_san"])
        if c and not any(x["id"] == c["id"] for x in out):
            out.append(c)
    return out


def scan(force: bool = False) -> int:
    """Add puzzles from reviews not scanned yet (or analysed again). Returns how many were added."""
    t = store.thresholds_from(store.get_settings())
    added = 0
    with store.db() as con:
        have = {r[0]: r[1] for r in con.execute("SELECT game_id, version FROM puzzle_scan")}
        if any(str(v).startswith("2:") for v in have.values()):
            # the old rule called every forced mate "several moves are fine", so "one move or several?" was
            # scored against the wrong answer: start that score again with the rescan
            con.execute("DELETE FROM meta WHERE key = 'puzzle_judgement'")
        todo = [r[0] for r in con.execute("SELECT game_id, analysed_at FROM reviews").fetchall()
                if force or have.get(r[0]) != f"{SCAN_VERSION}:{r[1]}"]    # compared in Python: SQLite prints REALs differently
        rows = []
        for i in range(0, len(todo), 500):
            chunk = todo[i:i + 500]
            rows += con.execute(f"SELECT game_id, review_json, analysed_at FROM reviews WHERE game_id IN ({','.join('?' * len(chunk))})",
                                chunk).fetchall()
    for r in rows:
        try:
            rv = store.review_from_json(r["review_json"], t)
            cands = from_review(r["game_id"], rv)
        except Exception:
            cands = []
        now = time.time()
        with store.db() as con:
            for c in cands:
                cur = con.execute(
                    "INSERT OR IGNORE INTO puzzles (id, game_id, ply, fen, color, prev_fen, last_uci, source, kind, solution, solution_san,"
                    " motif, severity, played_san, label, win_gap, created, why) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (c["id"], c["game_id"], c["ply"], c["fen"], c["color"], c["prev_fen"], c["last_uci"], c["source"], c["kind"], json.dumps(c["solution"]),
                     json.dumps(c["solution_san"]), c["motif"], c["severity"], c["played_san"], c["label"], c["win_gap"], now,
                     json.dumps(c["why"])))
                if cur.rowcount == 0:   # re-analysed: refresh the line, keep the schedule
                    con.execute("UPDATE puzzles SET fen=?, kind=?, solution=?, solution_san=?, motif=?, severity=?, win_gap=?,"
                                " why=?, prev_fen=?, last_uci=?, played_san=? WHERE id=?",
                                (c["fen"], c["kind"], json.dumps(c["solution"]), json.dumps(c["solution_san"]), c["motif"], c["severity"],
                                 c["win_gap"], json.dumps(c["why"]), c["prev_fen"], c["last_uci"], c["played_san"], c["id"]))
                added += cur.rowcount
            # positions that no longer qualify (new rules, re-analysis) go, unless you've already seen them
            keep = [c["id"] for c in cands]
            con.execute(f"DELETE FROM puzzles WHERE game_id = ? AND due IS NULL AND last_result IS NULL"
                        f"{' AND id NOT IN (' + ','.join('?' * len(keep)) + ')' if keep else ''}", (r["game_id"], *keep))
            con.execute("INSERT OR REPLACE INTO puzzle_scan VALUES (?, ?)", (r["game_id"], f"{SCAN_VERSION}:{r['analysed_at']}"))
    _mark_retries()
    return added


def _mark_retries() -> None:
    """Failed or given-up retries: that puzzle is due today if it is still new."""
    with store.db() as con:
        rows = con.execute(
            "SELECT game_id, ply, MAX(solved) AS ok FROM retries WHERE game_id IS NOT NULL GROUP BY game_id, ply").fetchall()
        for r in rows:
            if r["ok"]:
                continue
            con.execute("UPDATE puzzles SET from_retry = 1, due = COALESCE(due, ?) WHERE id = ? AND from_retry = 0",
                        (today(), f"{r['game_id']}:{r['ply']}"))


def forget_game(gid: str) -> None:
    with store.db() as con:
        con.execute("DELETE FROM puzzles WHERE game_id = ?", (gid,))
        con.execute("DELETE FROM puzzle_scan WHERE game_id = ?", (gid,))


# ---------------------------------------------------------------------------
# the daily queue and the schedule
# ---------------------------------------------------------------------------

def _row(r) -> dict:
    d = dict(r)
    d["solution"] = json.loads(d["solution"])
    d["solution_san"] = json.loads(d["solution_san"])
    d["new"] = d["due"] is None
    d["why"] = json.loads(d["why"]) if d.get("why") else None
    return d


def _games(con, ids: set) -> dict:
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    return {r["id"]: dict(r) for r in con.execute(
        f"SELECT id, white, black, played_at, player_color, time_control FROM games WHERE id IN ({q})", tuple(ids))}


def queue(motif: str = "", more: bool = False, kind: str = "", ids: Optional[list] = None) -> dict:
    """ids: practise exactly these puzzles (a recurring-mistake set), whatever their schedule."""
    s = store.get_settings()
    per_day = max(1, int(s.get("puzzles_per_day", 10) or 10))
    with_opp = bool(s.get("puzzles_include_opponent", True))
    day = today()
    where, args = ["1"], []
    if not with_opp:
        where.append("(source = 'mine' OR from_retry = 1)")
    if motif:
        where.append("motif = ?"); args.append(motif)
    if kind in ("tactic", "better"):
        where.append("kind = ?"); args.append(kind)
    if ids:
        where = [f"id IN ({','.join('?' * len(ids))})"]; args = list(ids)
        more = True
    w = " AND ".join(where)
    with store.db() as con:
        done = con.execute("SELECT COUNT(DISTINCT puzzle_id) FROM puzzle_log WHERE day = ?", (day,)).fetchone()[0]
        done_ids = {r[0] for r in con.execute("SELECT DISTINCT puzzle_id FROM puzzle_log WHERE day = ?", (day,))}
        due = [_row(r) for r in con.execute(
            f"SELECT * FROM puzzles WHERE {w} AND due IS NOT NULL AND due <= ? ORDER BY from_retry DESC, due, created",
            (*args, day))]
        new = [_row(r) for r in con.execute(
            f"SELECT * FROM puzzles WHERE {w} AND due IS NULL ORDER BY created DESC, game_id, ply", tuple(args))]
        total = con.execute("SELECT COUNT(*) FROM puzzles").fetchone()[0]
        motifs = {r[0]: r[1] for r in con.execute(
            "SELECT motif, COUNT(*) FROM puzzles" + ("" if with_opp else " WHERE source = 'mine' OR from_retry = 1")
            + " GROUP BY motif ORDER BY COUNT(*) DESC")}
        if ids:     # a practice set: everything in it, solved today or not
            due = [_row(r) for r in con.execute(f"SELECT * FROM puzzles WHERE {w} ORDER BY game_id, ply", tuple(args))]
            new = []
        due = [p for p in due if p["id"] not in done_ids or ids]
        new = [p for p in new if p["id"] not in done_ids]
        # new ones: take turns between games (newest first), so two puzzles in a
        # row are not the same position one move apart
        buckets: dict = {}
        for p in new:
            buckets.setdefault(p["game_id"], []).append(p)
        for b in buckets.values():
            b.sort(key=lambda p: p["ply"])
        mixed = []
        while buckets:
            for gid in list(buckets):
                mixed.append(buckets[gid].pop(0))
                if not buckets[gid]:
                    del buckets[gid]
        left = max(0, per_day - done)
        items = (due + mixed) if more else (due + mixed)[:left]
        games = _games(con, {p["game_id"] for p in items})
    from payload import clock_limits
    for p in items:
        g = games.get(p["game_id"]) or {}
        p["budget"] = None
        tc = (g.get("time_control") or "").strip()
        if tc and "/" not in tc and tc not in ("-", "?"):
            try:
                base, _, inc = tc.partition("+")
                mine = max(1, (len(p["solution"]) + 1) // 2)
                p["budget"] = round(clock_limits(float(base), float(inc or 0))["budget"] * mine, 1)   # your moves x your per-move time
            except ValueError:
                pass
        mine_col = g.get("player_color")
        opp_name = g.get("black") if mine_col == "White" else g.get("white")
        p["game"] = {"opponent": opp_name, "date": (g.get("played_at") or "")[:10], "tc": g.get("time_control"),
                     "white": g.get("white"), "black": g.get("black")}
    with store.db() as con:
        kinds = {r[0]: r[1] for r in con.execute("SELECT kind, COUNT(*) FROM puzzles GROUP BY kind")}
    jd = json.loads(store.get_meta("puzzle_judgement") or '{"right": 0, "asked": 0}')
    return {"day": day, "per_day": per_day, "kinds": kinds, "done_today": done, "queue": items, "judgement": jd,
            "clock": bool(s.get("puzzle_clock")), "ask_judgement": bool(s.get("puzzle_judgement", True)),
            "due_count": len(due), "new_count": len(new), "total": total, "motifs": motifs,
            "include_opponent": with_opp, "streak": _streak()}


def _streak() -> int:
    with store.db() as con:
        days = {r[0] for r in con.execute("SELECT DISTINCT day FROM puzzle_log")}
    d = _dt.date.today()
    if d.isoformat() not in days:
        d -= _dt.timedelta(days=1)   # today not started yet: the streak still counts up to yesterday
    n = 0
    while d.isoformat() in days:
        n += 1
        d -= _dt.timedelta(days=1)
    return n


def record(pid: str, result: str, hints: int = 0, judged: Optional[bool] = None) -> dict:
    """result: 'solved' | 'failed' | 'slow' (solved, but over the clock: comes back sooner, like a hint).
    hints: 0-3 (piece, square, answer). judged: your 'one move or several?' guess was right (None = not asked)."""
    if result not in ("solved", "failed", "slow"):
        raise ValueError("result must be solved, failed or slow")
    if judged is not None:
        j = json.loads(store.get_meta("puzzle_judgement") or '{"right": 0, "asked": 0}')
        j["asked"] += 1
        j["right"] += bool(judged)
        store.set_meta("puzzle_judgement", json.dumps(j))
    if result == "slow":
        result, hints = "solved", max(hints, 1)          # scheduled like a solve with a hint
    day = today()
    with store.db() as con:
        r = con.execute("SELECT * FROM puzzles WHERE id = ?", (pid,)).fetchone()
        if r is None:
            raise KeyError(pid)
        interval, ease, reps, lapses = r["interval"], r["ease"], r["reps"], r["lapses"]
        if result == "solved" and hints == 0:
            reps += 1
            interval = 1 if reps == 1 else 3 if reps == 2 else interval * ease
            ease = min(3.0, ease + 0.1)
        elif result == "solved":           # with hints: seen again soon
            reps = max(1, reps)
            interval = max(1.0, min(interval, 3.0))
            ease = max(1.3, ease - 0.15)
        else:
            reps, lapses = 0, lapses + 1
            interval = 1.0
            ease = max(1.3, ease - 0.2)
        due = _add_days(day, interval)
        con.execute("UPDATE puzzles SET interval=?, ease=?, reps=?, lapses=?, due=?, last_result=?, last_at=? WHERE id=?",
                    (interval, ease, reps, lapses, due, result, time.time(), pid))
        con.execute("INSERT INTO puzzle_log VALUES (?,?,?,?,?)", (pid, day, result, hints, time.time()))
    return {"id": pid, "due": due, "interval": round(interval, 1), "result": result}


def stats() -> dict:
    with store.db() as con:
        r = con.execute("SELECT COUNT(*) n, SUM(due IS NULL) new, SUM(reps >= 3) learned FROM puzzles").fetchone()
        log = con.execute("SELECT COUNT(*) n, SUM(result = 'solved' AND hints = 0) clean FROM puzzle_log").fetchone()
    return {"total": r["n"] or 0, "new": r["new"] or 0, "learned": r["learned"] or 0,
            "attempts": log["n"] or 0, "clean": log["clean"] or 0}


# ---------------------------------------------------------------------------
# saved variations (analysis board)
# ---------------------------------------------------------------------------

def save_variation(name: str, fen: str, moves: list[str], game_id: Optional[str] = None, ply: Optional[int] = None) -> int:
    b = chess.Board(fen)
    for u in moves:
        mv = chess.Move.from_uci(u)
        if mv not in b.legal_moves:
            raise ValueError(f"illegal move {u}")
        b.push(mv)
    with store.db() as con:
        cur = con.execute("INSERT INTO variations (name, fen, moves, game_id, ply, created) VALUES (?,?,?,?,?,?)",
                          (name.strip()[:120] or "Line", chess.Board(fen).fen(), json.dumps(moves), game_id, ply, time.time()))
        return cur.lastrowid


def variations() -> list[dict]:
    with store.db() as con:
        rows = con.execute("SELECT * FROM variations ORDER BY created DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["moves"] = json.loads(d["moves"])
        b = chess.Board(d["fen"])
        sans = []
        for u in d["moves"]:
            mv = chess.Move.from_uci(u)
            sans.append(b.san(mv)); b.push(mv)
        d["san"] = sans
        out.append(d)
    return out


def delete_variation(vid: int) -> None:
    with store.db() as con:
        con.execute("DELETE FROM variations WHERE id = ?", (vid,))
