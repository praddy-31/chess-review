"""
Convert-the-win drills (V8): winning positions from your games that you
didn't win, played out again.

  - found in analysed games you drew or lost: the first position (after move 8,
    your move) where you were +3 or better
  - the defender is Maia at your opponent's rating, picking among its likely
    moves (so it doesn't play the same game every time); without Maia,
    Stockfish limited to a human strength (UCI_Elo)
  - Stockfish only judges: after each of your moves it gives your win chance
  - won  = checkmate, or 95%+ win chance after at least 6 of your moves
  - lost = your win chance falls under 60%, or a draw (stalemate, repetition,
    50 moves, no material), or 60 of your moves without finishing
  - its own daily number (Settings) and spaced repetition like puzzles
"""

from __future__ import annotations

import datetime as _dt
import json
import random
import threading
import time
from typing import Optional

import chess
import chess.engine

import store
from chess_analysis import win_percent

START_CP = 300            # "+3": where a drill starts
MIN_MOVE = 8              # not in the opening
WIN_PCT, LOST_PCT = 95.0, 60.0
MIN_MINE = 6              # your moves before a 95% position counts as converted
MAX_MINE = 60
JUDGE_DEPTH = 14
SCHEMA = """
CREATE TABLE IF NOT EXISTS convert_drills (
    id TEXT PRIMARY KEY, game_id TEXT NOT NULL, ply INTEGER NOT NULL, fen TEXT NOT NULL, color TEXT NOT NULL,
    start_cp INTEGER, opp_elo INTEGER, outcome TEXT, opponent TEXT, played_at TEXT, created REAL NOT NULL,
    due TEXT, interval REAL NOT NULL DEFAULT 0, ease REAL NOT NULL DEFAULT 2.5, reps INTEGER NOT NULL DEFAULT 0,
    lapses INTEGER NOT NULL DEFAULT 0, last_result TEXT, last_at REAL, best_mine INTEGER
);
CREATE TABLE IF NOT EXISTS convert_log (drill_id TEXT, day TEXT, result TEXT, moves INTEGER, at REAL);
CREATE TABLE IF NOT EXISTS convert_scan (game_id TEXT PRIMARY KEY, stamp TEXT NOT NULL);
"""


def today() -> str:
    return _dt.date.today().isoformat()


def ensure(con) -> None:
    con.executescript(SCHEMA)


# ---------------------------------------------------------------------------
# finding the drills
# ---------------------------------------------------------------------------

def scan() -> int:
    """Adds a drill for every analysed game you didn't win from a +3 position. Returns how many were added."""
    th = store.thresholds_from(store.get_settings())
    with store.db() as con:
        ensure(con)
        have = {r[0] for r in con.execute("SELECT game_id FROM convert_drills")}
        seen = {r[0]: r[1] for r in con.execute("SELECT game_id, stamp FROM convert_scan")}
        todo = [r["game_id"] for r in con.execute("SELECT game_id, analysed_at FROM reviews")
                if r["game_id"] not in have and seen.get(r["game_id"]) != str(r["analysed_at"])]
    added = 0
    for gid in todo:
        with store.db() as con:
            r = con.execute("SELECT r.game_id, r.analysed_at, r.review_json, g.white, g.black, g.white_elo, g.black_elo, g.result, g.played_at "
                            "FROM reviews r JOIN games g ON g.id = r.game_id WHERE r.game_id = ?", (gid,)).fetchone()
            if r is None:
                continue
            con.execute("INSERT OR REPLACE INTO convert_scan VALUES (?, ?)", (gid, str(r["analysed_at"])))
        try:
            rv = store.review_from_json(r["review_json"], th)
        except Exception:
            continue
        me = rv.player_color
        res = r["result"] or "*"
        won = (res == "1-0" and me == "White") or (res == "0-1" and me == "Black")
        if won or res == "*":
            continue
        for p in rv.raw:
            if p.color != me or p.move_number < MIN_MOVE:
                continue
            if p.mate_before is not None and p.mate_before > 0 or (p.cp_before or -9999) >= START_CP:
                opp_elo = r["black_elo"] if me == "White" else r["white_elo"]
                with store.db() as con:
                    con.execute("INSERT OR IGNORE INTO convert_drills (id, game_id, ply, fen, color, start_cp, opp_elo, outcome, opponent, played_at, created) "
                                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                (f"{r['game_id']}:{p.ply}", r["game_id"], p.ply, p.fen_before, me,
                                 10000 if p.mate_before else p.cp_before, opp_elo, "draw" if res == "1/2-1/2" else "loss",
                                 r["black"] if me == "White" else r["white"], r["played_at"], time.time()))
                added += 1
                break
    return added


def queue(more: bool = False) -> dict:
    s = store.get_settings()
    per_day = max(1, int(s.get("convert_per_day", 3) or 3))
    day = today()
    with store.db() as con:
        ensure(con)
        done_ids = {r[0] for r in con.execute("SELECT DISTINCT drill_id FROM convert_log WHERE day = ?", (day,))}
        rows = [dict(r) for r in con.execute("SELECT * FROM convert_drills ORDER BY (due IS NULL), due, played_at DESC")]
        total = len(rows)
    due = [r for r in rows if r["due"] and r["due"] <= day and r["id"] not in done_ids]
    new = [r for r in rows if not r["due"] and r["id"] not in done_ids]
    left = max(0, per_day - len(done_ids))
    items = (due + new) if more else (due + new)[:left]
    lc0, _ = _maia_weights(None)
    return {"day": day, "per_day": per_day, "done_today": len(done_ids), "queue": items, "total": total,
            "due_count": len(due), "new_count": len(new), "maia": bool(lc0)}


# ---------------------------------------------------------------------------
# playing one out: a session keeps the engines open between moves
# ---------------------------------------------------------------------------

def _maia_weights(elo: Optional[int]):
    import engines
    s = store.get_settings()
    lc0 = engines._which("lc0", s.get("lc0_path", ""))
    weights = engines.maia_weights(s)
    if not lc0 or not weights:
        return None, None
    target = int(elo or store.my_rating(settings=s))
    band = min(weights, key=lambda b: abs(b - target))
    return lc0, (band, weights[band])


class Session:
    def __init__(self, drill: dict):
        import engines
        self.drill = drill
        self.board = chess.Board(drill["fen"])
        self.me = chess.WHITE if drill["color"] == "White" else chess.BLACK
        self.start_ply = len(self.board.move_stack)
        self.moves: list[dict] = []
        self.last = time.time()
        s = store.get_settings()
        path = engines._which("stockfish", s.get("stockfish_path", ""))
        if not path:
            raise RuntimeError("Stockfish isn't installed (see Setup)")
        self.judge = chess.engine.SimpleEngine.popen_uci(path)
        self.defender_name = None
        self.maia = None
        self.weak = None
        lc0, w = _maia_weights(drill.get("opp_elo"))
        if lc0:
            try:
                from chess_analysis import MaiaEngine
                self.maia = MaiaEngine(lc0, w[1], timeout=30)
                self.defender_name = f"Maia {w[0]}"
            except Exception:
                self.maia = None
        if self.maia is None:
            self.weak = chess.engine.SimpleEngine.popen_uci(path)
            elo = max(1320, min(3190, int(drill.get("opp_elo") or s.get("rating") or 1300)))
            try:
                self.weak.configure({"UCI_LimitStrength": True, "UCI_Elo": elo})
            except Exception:
                pass
            self.defender_name = f"Stockfish at {elo}"
        self.win = self._win()
        self.start_win = self.win

    def _win(self) -> float:
        info = self.judge.analyse(self.board, chess.engine.Limit(depth=JUDGE_DEPTH, time=1.5))
        sc = info["score"].pov(self.me)
        return win_percent(sc.score(), sc.mate())

    def _defend(self) -> chess.Move:
        if self.maia is not None:
            pol = self.maia.policy(self.board)
            legal = {m.uci(): m for m in self.board.legal_moves}
            cand = [(u, p) for u, p in pol.items() if u in legal and p >= 0.05]
            if not cand:
                cand = [(u, p) for u, p in pol.items() if u in legal]
            if cand:
                total = sum(p for _, p in cand)
                x, acc = random.random() * total, 0.0
                for u, p in sorted(cand, key=lambda t: -t[1]):
                    acc += p
                    if acc >= x:
                        return legal[u]
        res = self.weak.play(self.board, chess.engine.Limit(time=0.3))
        return res.move

    def mine(self) -> int:
        return sum(1 for m in self.moves if m["by"] == "you")

    def status(self) -> Optional[str]:
        b = self.board
        if b.is_checkmate():
            return "won" if b.turn != self.me else "lost"
        if b.is_stalemate() or b.is_insufficient_material() or b.can_claim_draw():
            return "drawn"
        if self.win < LOST_PCT:
            return "slipped"
        if self.win >= WIN_PCT and self.mine() >= MIN_MINE:
            return "won"
        if self.mine() >= MAX_MINE:
            return "unfinished"
        return None

    def play(self, uci: str) -> dict:
        self.last = time.time()
        mv = chess.Move.from_uci(uci)
        if mv not in self.board.legal_moves:
            raise ValueError("that move isn't legal here")
        before = self.win
        san = self.board.san(mv)
        self.board.push(mv)
        self.win = self._win() if not self.board.is_game_over() else (100.0 if self.board.is_checkmate() else 50.0)
        self.moves.append({"by": "you", "uci": uci, "san": san, "win": round(self.win), "drop": round(max(0.0, before - self.win))})
        st = self.status()
        reply = None
        if st is None:
            r = self._defend()
            rsan = self.board.san(r)
            self.board.push(r)
            self.win = self._win() if not self.board.is_game_over() else (0.0 if self.board.is_checkmate() else 50.0)
            reply = {"by": "them", "uci": r.uci(), "san": rsan, "win": round(self.win)}
            self.moves.append(reply)
            st = self.status()
        return {"fen": self.board.fen(), "you": self.moves[-2] if reply else self.moves[-1], "reply": reply,
                "win": round(self.win), "status": st, "mine": self.mine()}

    def close(self):
        for e in (self.judge, self.weak):
            try:
                if e:
                    e.quit()
            except Exception:
                pass
        if self.maia is not None:
            self.maia.quit()


_SESSIONS: dict = {}
_LOCK = threading.Lock()


def start(drill_id: str) -> dict:
    with store.db() as con:
        ensure(con)
        r = con.execute("SELECT * FROM convert_drills WHERE id = ?", (drill_id,)).fetchone()
    if r is None:
        raise KeyError(drill_id)
    _reap()
    with _LOCK:
        old = _SESSIONS.pop(drill_id, None)
    if old:
        old.close()
    s = Session(dict(r))
    with _LOCK:
        _SESSIONS[drill_id] = s
    return {"id": drill_id, "fen": s.board.fen(), "color": dict(r)["color"], "win": round(s.win), "defender": s.defender_name,
            "drill": dict(r)}


def move(drill_id: str, uci: str) -> dict:
    with _LOCK:
        s = _SESSIONS.get(drill_id)
    if s is None:
        raise KeyError("start the drill first")
    out = s.play(uci)
    if out["status"]:
        out["summary"] = finish(drill_id, out["status"])
    return out


def resign(drill_id: str) -> dict:
    return finish(drill_id, "gave up")


def finish(drill_id: str, status: str) -> dict:
    with _LOCK:
        s = _SESSIONS.pop(drill_id, None)
    moves = s.moves if s else []
    worst = max((m for m in moves if m["by"] == "you"), key=lambda m: m.get("drop", 0), default=None)
    won = status == "won"
    day = today()
    with store.db() as con:
        ensure(con)
        r = con.execute("SELECT * FROM convert_drills WHERE id = ?", (drill_id,)).fetchone()
        if r is not None:
            interval, ease, reps, lapses = r["interval"], r["ease"], r["reps"], r["lapses"]
            if won:
                reps += 1
                interval = 3 if reps == 1 else 7 if reps == 2 else interval * ease
                ease = min(3.0, ease + 0.1)
            else:
                reps, lapses, interval, ease = 0, lapses + 1, 1.0, max(1.3, ease - 0.2)
            due = (_dt.date.today() + _dt.timedelta(days=max(1, round(interval)))).isoformat()
            mine = sum(1 for m in moves if m["by"] == "you")
            best = (min(r["best_mine"], mine) if r["best_mine"] else mine) if won else r["best_mine"]   # fewest moves to convert
            con.execute("UPDATE convert_drills SET interval=?, ease=?, reps=?, lapses=?, due=?, last_result=?, last_at=?, best_mine=? WHERE id=?",
                        (interval, ease, reps, lapses, due, status, time.time(), best, drill_id))
            con.execute("INSERT INTO convert_log VALUES (?,?,?,?,?)", (drill_id, day, status, mine, time.time()))
        else:
            due = None
    if s:
        s.close()
    return {"status": status, "won": won, "due": due, "moves": moves,
            "worst": worst if worst and worst.get("drop", 0) >= 8 else None,
            "start_win": round(s.start_win) if s else None, "defender": s.defender_name if s else None}


def _reap(idle: float = 900) -> None:
    """Closes sessions nobody has touched for 15 minutes."""
    now = time.time()
    with _LOCK:
        stale = [k for k, s in _SESSIONS.items() if now - s.last > idle]
        olds = [_SESSIONS.pop(k) for k in stale]
    for s in olds:
        s.close()
