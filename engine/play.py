"""
Play a game against Maia (V10).

  - you pick a Maia rating (the weights installed: 1100-1900), your colour and a
    clock: none (the default) or base+increment
  - Maia picks among its likely moves (5%+ probability, weighted by it), as in
    the convert drills, so no two games are the same
  - no takebacks; the game ends on mate, stalemate, threefold repetition, the
    50-move rule, insufficient material, your resignation or your flag
  - with a clock, Maia "thinks" for a human-like share of its time (it answers at
    once; the time is booked so the PGN's clocks look like a real game's)
  - the game in progress is saved (meta "play_saved") at the start, after every move
    and on Pause, so it survives leaving Play, an idle hour and quitting the app;
    Pause stops both clocks (the page measures your time and sends it, so a pause is
    simply time that isn't counted). One saved game at a time: starting another
    drops it. Time between your last move or pause and quitting isn't counted.
  - the finished game goes into the Library as source "maia", not analysed:
    you analyse it when you choose. Games against Maia stay out of Insights unless
    Settings counts them (store.maia_counted)

Needs lc0 and Maia weights; Stockfish isn't used while playing.
"""

from __future__ import annotations

import datetime as _dt
import json
import random
import threading
import time
import uuid
from typing import Optional

import chess
import chess.pgn

import store

MIN_P = 0.05
_SESSIONS: dict = {}
_LOCK = threading.Lock()


def _engines():
    import engines
    s = store.get_settings()
    return engines._which("lc0", s.get("lc0_path", "")), engines.maia_weights(s)


def options() -> dict:
    lc0, weights = _engines()
    s = store.get_settings()
    bands = sorted(weights)
    rating = store.my_rating(settings=s)
    near = min(bands, key=lambda b: abs(b - rating)) if bands else None
    with store.db() as con:
        rows = con.execute("SELECT id, white, black, result, player_color, played_at, white_elo, black_elo, "
                           "(SELECT 1 FROM reviews r WHERE r.game_id = g.id) AS analysed FROM games g WHERE source = ? "
                           "ORDER BY played_at DESC LIMIT 8", (store.BOT_SOURCE,)).fetchall()
    recent = []
    for r in rows:
        me = r["player_color"]
        res = r["result"]
        out = "draw" if res == "1/2-1/2" else "win" if (res == "1-0") == (me == "White") else "loss"
        recent.append({"id": r["id"], "maia": r["black"] if me == "White" else r["white"], "color": me, "outcome": out,
                       "date": (r["played_at"] or "")[:10], "analysed": bool(r["analysed"])})
    saved = _saved()
    return {"available": bool(lc0 and bands), "lc0": bool(lc0), "bands": bands,
            "band": s.get("play_maia_band") if s.get("play_maia_band") in bands else near,
            "clock": s.get("play_clock") or "none", "rating": rating, "recent": recent,
            "saved": {"id": saved["id"], "band": saved["band"], "color": saved["color"],
                      "moves": len(saved["moves"]), "started": saved["started"]} if saved else None}


def _saved() -> Optional[dict]:
    try:
        return json.loads(store.get_meta("play_saved") or "null")
    except ValueError:
        return None


def _save(gid: str, gm: "Game") -> None:
    store.set_meta("play_saved", json.dumps(gm.snapshot(gid)))


def _drop_saved(gid: Optional[str] = None) -> None:
    sv = _saved()
    if sv and (gid is None or sv.get("id") == gid):
        store.set_meta("play_saved", "null")


def parse_clock(spec: str) -> Optional[tuple[int, int]]:
    """'10+5' -> (600, 5) seconds; 'none' or nonsense -> None."""
    try:
        base, inc = spec.split("+")
        b, i = int(float(base) * 60), int(inc)
        return (b, i) if b > 0 and 0 <= i <= 180 else None
    except (ValueError, AttributeError):
        return None


class Game:
    def __init__(self, band: int, color: str, clock: Optional[tuple[int, int]]):
        from chess_analysis import MaiaEngine
        lc0, weights = _engines()
        if not lc0 or band not in weights:
            raise RuntimeError("Play needs lc0 and the Maia weights (see Setup)")
        self.maia = MaiaEngine(lc0, weights[band], timeout=30)
        self.band = band
        self.me = chess.WHITE if color == "White" else chess.BLACK
        self.board = chess.Board()
        self.clock = clock
        self.left = {chess.WHITE: float(clock[0]), chess.BLACK: float(clock[0])} if clock else None
        self.clocks: list[Optional[float]] = []      # the mover's clock after each move, for [%clk]
        self.started = _dt.datetime.now(_dt.timezone.utc)
        self.last = time.time()
        self.result: Optional[dict] = None
        self.pending = 0.0          # seconds you'd used on this move before a pause
        self.paused = False

    # --- saved between sessions ------------------------------------------------
    def snapshot(self, gid: str) -> dict:
        return {"id": gid, "band": self.band, "color": "White" if self.me == chess.WHITE else "Black",
                "clock": list(self.clock) if self.clock else None,
                "left": None if self.left is None else {"White": self.left[chess.WHITE], "Black": self.left[chess.BLACK]},
                "clocks": self.clocks, "moves": [m.uci() for m in self.board.move_stack],
                "started": self.started.isoformat(), "pending": self.pending, "paused": self.paused}

    @classmethod
    def restore(cls, snap: dict) -> "Game":
        gm = cls(int(snap["band"]), snap["color"], tuple(snap["clock"]) if snap.get("clock") else None)
        for u in snap["moves"]:
            gm.board.push(chess.Move.from_uci(u))
        if gm.left is not None and snap.get("left"):
            gm.left = {chess.WHITE: float(snap["left"]["White"]), chess.BLACK: float(snap["left"]["Black"])}
        gm.clocks = list(snap.get("clocks") or [])
        gm.started = _dt.datetime.fromisoformat(snap["started"])
        gm.pending, gm.paused = float(snap.get("pending") or 0), bool(snap.get("paused"))
        return gm

    # --- moves -----------------------------------------------------------
    def _book(self, side: bool, spent: float) -> None:
        if self.left is None:
            self.clocks.append(None)
            return
        self.left[side] = self.left[side] - spent
        if self.left[side] > 0:
            self.left[side] += self.clock[1]
        self.clocks.append(round(max(0.0, self.left[side]), 1))

    def _maia_time(self) -> float:
        """A human-like think: a share of what's left, quicker in the opening."""
        left = self.left[not self.me]
        n = self.board.fullmove_number
        share = left / (40 if n > 10 else 80)
        return max(0.5, min(left * 0.5, share * random.uniform(0.4, 1.6)))

    def _pick(self) -> chess.Move:
        pol = self.maia.policy(self.board)
        legal = {m.uci(): m for m in self.board.legal_moves}
        cand = [(u, p) for u, p in pol.items() if u in legal and p >= MIN_P] or [(u, p) for u, p in pol.items() if u in legal]
        if not cand:
            return random.choice(list(self.board.legal_moves))
        total = sum(p for _, p in cand)
        x, acc = random.random() * total, 0.0
        for u, p in sorted(cand, key=lambda t: -t[1]):
            acc += p
            if acc >= x:
                return legal[u]
        return legal[cand[0][0]]

    def maia_move(self) -> dict:
        mv = self._pick()
        san = self.board.san(mv)
        self._book(not self.me, self._maia_time() if self.left else 0)
        self.board.push(mv)
        return {"uci": mv.uci(), "san": san}

    def ended(self) -> Optional[tuple[str, str]]:
        """(result, termination) when the game is over."""
        b = self.board
        if b.is_checkmate():
            return ("0-1" if b.turn == chess.WHITE else "1-0"), "checkmate"
        if b.is_stalemate():
            return "1/2-1/2", "stalemate"
        if b.is_insufficient_material():
            return "1/2-1/2", "insufficient material"
        if b.is_repetition(3):
            return "1/2-1/2", "repetition"
        if b.is_fifty_moves():
            return "1/2-1/2", "the 50-move rule"
        return None

    def state(self) -> dict:
        return {"fen": self.board.fen(), "turn": "White" if self.board.turn else "Black",
                "clocks": None if self.left is None else {"White": round(self.left[chess.WHITE], 1), "Black": round(self.left[chess.BLACK], 1)},
                "moves": [m.uci() for m in self.board.move_stack]}

    # --- the end -----------------------------------------------------------
    def finish(self, result: str, termination: str) -> dict:
        if self.result:
            return self.result
        s = store.get_settings()
        name = (s.get("chesscom_user") or s.get("lichess_user") or "You").strip() or "You"
        maia = f"Maia {self.band}"
        g = chess.pgn.Game()
        h = g.headers
        h["Event"] = "Casual game vs Maia"
        h["Site"] = "Chess Review"
        h["Date"] = self.started.strftime("%Y.%m.%d")
        h["UTCDate"], h["UTCTime"] = self.started.strftime("%Y.%m.%d"), self.started.strftime("%H:%M:%S")
        h["White"], h["Black"] = (name, maia) if self.me == chess.WHITE else (maia, name)
        from chess_analysis import time_control_category
        me = str(store.my_rating(time_control_category(f"{self.clock[0]}+{self.clock[1]}") if self.clock else None, s))   # your rating at this speed
        h["WhiteElo"], h["BlackElo"] = (me, str(self.band)) if self.me == chess.WHITE else (str(self.band), me)
        h["TimeControl"] = f"{self.clock[0]}+{self.clock[1]}" if self.clock else "-"
        h["Result"] = result
        winner = {"1-0": h["White"], "0-1": h["Black"]}.get(result)
        h["Termination"] = f"{winner} won by {termination}" if winner else f"Game drawn by {termination}"
        node = g
        for mv, clk in zip(self.board.move_stack, self.clocks):
            node = node.add_main_variation(mv)
            if clk is not None:
                node.set_clock(clk)
        gid, _ = store.add_game(g, s)
        with store.db() as con:
            con.execute("UPDATE games SET source = ?, player_color = ? WHERE id = ?",
                        (store.BOT_SOURCE, "White" if self.me == chess.WHITE else "Black", gid))
        me_white = self.me == chess.WHITE
        outcome = "draw" if result == "1/2-1/2" else "win" if (result == "1-0") == me_white else "loss"
        self.result = {"game_id": gid, "result": result, "termination": termination, "outcome": outcome,
                       "moves": len(self.board.move_stack)}
        return self.result

    def close(self):
        try:
            self.maia.quit()
        except Exception:
            pass


def start(band: int, color: str, clock: str = "none") -> dict:
    _reap()
    if color not in ("White", "Black"):
        color = random.choice(["White", "Black"])
    ck = parse_clock(clock)
    store.set_settings({"play_maia_band": band, "play_clock": clock if ck else "none"})
    gm = Game(int(band), color, ck)
    gid = uuid.uuid4().hex[:12]
    with _LOCK:
        _SESSIONS[gid] = gm
    first = gm.maia_move() if gm.me == chess.BLACK else None
    _save(gid, gm)            # one saved game at a time: this replaces any paused one
    return {"id": gid, "color": color, "band": gm.band, "clock": clock if ck else "none", "maia": first, **gm.state()}


def _info(gid: str, gm: "Game") -> dict:
    return {"id": gid, "color": "White" if gm.me == chess.WHITE else "Black", "band": gm.band,
            "clock": f"{gm.clock[0] // 60}+{gm.clock[1]}" if gm.clock else "none", "maia": None,
            "sans": _sans(gm.board), "last": gm.board.move_stack[-1].uci() if gm.board.move_stack else None,
            "pending": gm.pending, "paused": gm.paused, **gm.state()}


def _sans(board: chess.Board) -> list[str]:
    b, out = chess.Board(), []
    for m in board.move_stack:
        out.append(b.san(m)); b.push(m)
    return out


def pause(gid: str, spent: float = 0.0) -> dict:
    """Stops the clocks: keeps how long you'd thought on this move and saves the game."""
    gm = _get(gid)
    if gm.board.turn == gm.me:
        gm.pending = max(0.0, float(spent or 0))
    gm.paused = True
    _save(gid, gm)
    return _info(gid, gm)


def resume(gid: str) -> dict:
    """Carries on a paused game, after a restart too (rebuilt from the saved copy)."""
    gm = _get(gid)
    gm.paused = False
    _save(gid, gm)
    return _info(gid, gm)


def _get(gid: str) -> Game:
    with _LOCK:
        gm = _SESSIONS.get(gid)
    if gm is None:
        sv = _saved()
        if not sv or sv.get("id") != gid:
            raise KeyError("that game has ended; start a new one")
        gm = Game.restore(sv)          # after a restart or an idle hour
        with _LOCK:
            gm = _SESSIONS.setdefault(gid, gm)
    gm.last = time.time()
    return gm


def move(gid: str, uci: str, spent: float = 0.0) -> dict:
    gm = _get(gid)
    if gm.result:
        raise ValueError("the game is over")
    if gm.board.turn != gm.me:
        raise ValueError("it's Maia's move")
    mv = chess.Move.from_uci(uci)
    if mv not in gm.board.legal_moves:
        raise ValueError("that move isn't legal here")
    san = gm.board.san(mv)
    gm._book(gm.me, max(0.0, float(spent or 0)))
    if gm.left is not None and gm.left[gm.me] <= 0:
        return _end(gid, gm, "0-1" if gm.me == chess.WHITE else "1-0", "time", you=None)
    gm.board.push(mv)
    you = {"uci": uci, "san": san}
    end = gm.ended()
    if end:
        return _end(gid, gm, *end, you=you)
    gm.pending, gm.paused = 0.0, False
    reply = gm.maia_move()
    end = gm.ended()
    if end:
        return _end(gid, gm, *end, you=you, reply=reply)
    _save(gid, gm)
    return {"you": you, "maia": reply, "over": None, **gm.state()}


def _end(gid: str, gm: Game, result: str, why: str, you=None, reply=None) -> dict:
    if why == "time" and gm.board.has_insufficient_material(not gm.me):
        result, why = "1/2-1/2", "timeout vs insufficient material"    # Maia couldn't have mated: a draw
    summary = gm.finish(result, why)
    st = gm.state()
    with _LOCK:
        _SESSIONS.pop(gid, None)
    _drop_saved(gid)
    gm.close()
    return {"you": you, "maia": reply, "over": summary, **st}


def resign(gid: str) -> dict:
    gm = _get(gid)
    return _end(gid, gm, "0-1" if gm.me == chess.WHITE else "1-0", "resignation")


def flag(gid: str) -> dict:
    """Your clock ran out while you were thinking."""
    gm = _get(gid)
    if gm.left is None:
        raise ValueError("this game has no clock")
    return _end(gid, gm, "0-1" if gm.me == chess.WHITE else "1-0", "time")


def _reap(idle: float = 3600) -> None:
    """Frees games nobody has touched for an hour; the saved copy stays, so they can be resumed."""
    now = time.time()
    with _LOCK:
        stale = [k for k, g in _SESSIONS.items() if now - g.last > idle]
        olds = [_SESSIONS.pop(k) for k in stale]
    for g in olds:
        g.close()


def close_all() -> None:
    with _LOCK:
        olds = list(_SESSIONS.values())
        _SESSIONS.clear()
    for g in olds:
        g.close()
