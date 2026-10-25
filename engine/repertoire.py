"""
V5 Openings: an opening tree built from all your games, a line scan, a
repertoire you star in that tree, and drills with their own daily number.

The tree needs only the PGNs, so it covers every game, analysed or not. Each
game's first MAX_PLIES moves go into op_moves once (position before, move,
position after), keyed by EPD so transpositions meet. Analysed games add the
engine's eval after each move.

Repertoire depth (how far a line is worth knowing) follows your games, capped
by rating: a line is extended while at least MIN_GAMES of your games, and
MIN_SHARE of the games at the start, still reach it - but never past
depth_cap(rating) of your own moves.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import threading
import time
from typing import Optional

import chess
import chess.polyglot

import store
from chess_analysis import openings, _epd

MAX_PLIES = 24
MIN_GAMES = 3
MIN_SHARE = 0.01          # Oct 4: was 3%; more of your side lines make the repertoire
SCAN_MAX_PLIES = 16
INDEX_VERSION = "1"
START = chess.STARTING_FEN

SCHEMA = """
CREATE TABLE IF NOT EXISTS op_moves (       -- compact: positions as 64-bit Zobrist keys, games by a stable key (okey)
    g INTEGER NOT NULL, ply INTEGER NOT NULL,
    z INTEGER NOT NULL, uci TEXT NOT NULL, san TEXT NOT NULL, z_after INTEGER NOT NULL,
    cp_white INTEGER,                         -- engine eval after the move, White's view (analysed games)
    PRIMARY KEY (g, ply)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS op_moves_z ON op_moves(z);
CREATE TABLE IF NOT EXISTS op_games (game_id TEXT PRIMARY KEY, version TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS repertoire (      -- your chosen move where it is your turn
    color TEXT NOT NULL, epd TEXT NOT NULL, uci TEXT NOT NULL, san TEXT NOT NULL,
    fen TEXT NOT NULL, path TEXT NOT NULL,    -- a FEN to show it, and the moves from the start (JSON UCI)
    games INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL,
    due TEXT, interval REAL NOT NULL DEFAULT 0, ease REAL NOT NULL DEFAULT 2.5,
    reps INTEGER NOT NULL DEFAULT 0, lapses INTEGER NOT NULL DEFAULT 0, last_result TEXT, last_at REAL,
    PRIMARY KEY (color, epd)
);
CREATE TABLE IF NOT EXISTS drill_log (color TEXT, epd TEXT, day TEXT, result TEXT, at REAL);
"""


def okey(gid: str) -> int:
    """A stable 64-bit key per game (rowids can change on VACUUM)."""
    import hashlib
    z = int.from_bytes(hashlib.blake2b(gid.encode(), digest_size=8).digest(), "big")
    return z - (1 << 64) if z >= (1 << 63) else z


def ensure_schema(con) -> None:
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(games)")}
    if "okey" not in cols:
        con.execute("ALTER TABLE games ADD COLUMN okey INTEGER")
    con.execute("CREATE INDEX IF NOT EXISTS games_okey ON games(okey)")
    rcols = {r[1] for r in con.execute("PRAGMA table_info(repertoire)")}
    if "opening" not in rcols:      # V6: openings you add by name to learn them
        con.execute("ALTER TABLE repertoire ADD COLUMN opening TEXT")
    if "source" not in rcols:       # games | theory | engine | you
        con.execute("ALTER TABLE repertoire ADD COLUMN source TEXT")


def depth_cap(rating: Optional[int]) -> int:
    """How many of your own moves a repertoire line goes at most."""
    r = int(rating or 1200)
    return 6 if r < 1000 else 8 if r < 1400 else 10 if r < 1800 else 12


def zkey(board: chess.Board) -> int:
    z = chess.polyglot.zobrist_hash(board)
    return z - (1 << 64) if z >= (1 << 63) else z      # SQLite integers are signed


def today() -> str:
    return _dt.date.today().isoformat()


# ---------------------------------------------------------------------------
# the index
# ---------------------------------------------------------------------------

_COMMENT = re.compile(r"\{[^}]*\}|;[^\n]*|\([^()]*\)")
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9+#=\-]*|O-O(?:-O)?[+#]?|0-0(?:-0)?[+#]?")


def _movetext(pgn: str) -> list[str]:
    body = pgn.split("\n\n", 1)[1] if "\n\n" in pgn else pgn
    body = "\n".join(l for l in body.splitlines() if not l.startswith("["))
    prev = None
    while prev != body:                       # nested variations
        prev, body = body, _COMMENT.sub(" ", body)
    body = re.sub(r"\$\d+|\d+\.(\.\.)?", " ", body)
    return [t for t in _TOKEN.findall(body) if t not in ("e", "p")][:MAX_PLIES]


def _rows_for(rowid: int, pgn: str, evals: Optional[dict]) -> list[tuple]:
    b = chess.Board()
    out = []
    for ply, tok in enumerate(_movetext(pgn), start=1):
        try:
            mv = b.parse_san(tok.replace("0", "O") if tok.startswith("0-0") else tok)
        except ValueError:
            break
        z0 = zkey(b)
        san = b.san(mv)
        b.push(mv)
        out.append((rowid, ply, z0, mv.uci(), san, zkey(b), (evals or {}).get(ply)))
    return out


def _evals(review_json) -> dict:
    try:
        d = json.loads(store._unpack(review_json))
    except Exception:
        return {}
    out = {}
    for p in d.get("raw", []):
        if p.get("ply", 99) > MAX_PLIES:
            continue
        if p.get("mate_after") is not None:
            cp = 1000 if p["mate_after"] > 0 else -1000
        elif p.get("cp_after") is not None:
            cp = max(-1000, min(1000, p["cp_after"]))
        else:
            continue
        out[p["ply"]] = cp if p.get("color") == "White" else -cp
    return out


class Indexer:
    def __init__(self):
        self.lock = threading.Lock()
        self.status = {"state": "idle", "done": 0, "total": 0}

    @staticmethod
    def _ver(analysed_at) -> str:
        return f"{INDEX_VERSION}:{analysed_at or 0}"

    def pending(self, con) -> list:
        """Games not indexed yet, or analysed since (the eval column changes). Compared in Python:
        SQLite prints a REAL with different digits than Python does."""
        have = {r[0]: r[1] for r in con.execute("SELECT game_id, version FROM op_games")}
        stale = [r[0] for r in con.execute("SELECT g.id, r.analysed_at FROM games g LEFT JOIN reviews r ON r.game_id = g.id "
                                           "WHERE g.source != 'maia'").fetchall()   # games against Maia aren't your repertoire
                 if have.get(r[0]) != self._ver(r[1])]
        out = []
        for i in range(0, len(stale), 500):
            chunk = stale[i:i + 500]
            out += con.execute(
                f"SELECT g.okey AS rid, g.id, g.pgn, r.review_json, r.analysed_at FROM games g LEFT JOIN reviews r ON r.game_id = g.id "
                f"WHERE g.id IN ({','.join('?' * len(chunk))})", chunk).fetchall()
        return out

    def run(self, claimed: bool = False) -> int:
        with self.lock:
            if self.status["state"] == "running" and not claimed:
                return 0
            self.status = {"state": "running", "done": 0, "total": 0}
        n = 0
        try:
            with store.db() as con:
                ensure_schema(con)
                for r in con.execute("SELECT id FROM games WHERE okey IS NULL").fetchall():
                    con.execute("UPDATE games SET okey = ? WHERE id = ?", (okey(r[0]), r[0]))
                rows = self.pending(con)
            self.status["total"] = len(rows)
            for i in range(0, len(rows), 200):
                chunk = rows[i:i + 200]
                batch, marks = [], []
                for r in chunk:
                    ev = _evals(r["review_json"]) if r["review_json"] else None
                    batch += _rows_for(r["rid"], r["pgn"], ev)
                    marks.append((r["id"], self._ver(r["analysed_at"])))
                with store.db() as con:
                    con.executemany("DELETE FROM op_moves WHERE g = ?", [(r["rid"],) for r in chunk])
                    con.executemany("INSERT OR REPLACE INTO op_moves VALUES (?,?,?,?,?,?,?)", batch)
                    con.executemany("INSERT OR REPLACE INTO op_games VALUES (?, ?)", marks)
                n += len(chunk)
                self.status["done"] = n
        finally:
            self.status["state"] = "idle"
        return n

    def start(self) -> None:
        """Index new or re-analysed games in the background; the status says 'running' at once
        when there is work, so a caller can show progress and poll."""
        with self.lock:
            if self.status["state"] == "running":
                return
            with store.db() as con:
                ensure_schema(con)
                n = len(self.pending(con)) or con.execute("SELECT COUNT(*) FROM games WHERE okey IS NULL").fetchone()[0]
            if not n:
                return
            self.status = {"state": "running", "done": 0, "total": n}
        threading.Thread(target=self.run, kwargs={"claimed": True}, daemon=True, name="opening-index").start()


INDEXER = Indexer()


# ---------------------------------------------------------------------------
# the tree
# ---------------------------------------------------------------------------

def _filters(color: str, tc: str = "", since: str = "") -> tuple[str, list]:
    w, a = ["g.player_color = ?"], [color]
    if tc:
        w.append("g.tc_category = ?"); a.append(tc)
    if since:
        w.append("g.played_at >= ?"); a.append(since)
    return " AND ".join(w), a


def _score(result: str, color: str) -> float:
    if result == "1-0":
        return 1.0 if color == "White" else 0.0
    if result == "0-1":
        return 0.0 if color == "White" else 1.0
    return 0.5


def _walk(moves: list[str]) -> tuple[chess.Board, list[dict]]:
    b = chess.Board()
    path = []
    for u in moves:
        mv = chess.Move.from_uci(u)
        if mv not in b.legal_moves:
            raise ValueError(f"illegal move {u}")
        lab = f"{b.fullmove_number}{'.' if b.turn else '...'}"
        san = b.san(mv)
        b.push(mv)
        hit = openings().get(_epd(b.fen()))
        path.append({"uci": u, "san": san, "label": lab, "fen": b.fen(), "opening": f"{hit[0]} {hit[1]}" if hit else None})
    return b, path


def tree(moves: list[str], color: str, tc: str = "", since: str = "") -> dict:
    b, path = _walk(moves)
    epd = _epd(b.fen())
    z = zkey(b)
    where, args = _filters(color, tc, since)
    with store.db() as con:
        ensure_schema(con)
        rows = con.execute(
            f"SELECT m.uci, m.san, m.cp_white, g.result FROM op_moves m JOIN games g ON g.okey = m.g "
            f"WHERE m.z = ? AND {where}", (z, *args)).fetchall()
        rep = con.execute("SELECT uci, san FROM repertoire WHERE color = ? AND epd = ?", (color, epd)).fetchone()
        reached = con.execute(
            f"SELECT COUNT(DISTINCT m.g) FROM op_moves m JOIN games g ON g.okey = m.g WHERE m.z_after = ? AND {where}",
            (z, *args)).fetchone()[0] if moves else None
    agg: dict = {}
    for r in rows:
        a = agg.setdefault(r["uci"], {"uci": r["uci"], "san": r["san"], "n": 0, "w": 0, "d": 0, "l": 0, "ev": []})
        s = _score(r["result"], color)
        a["n"] += 1
        a["w" if s == 1 else "d" if s == 0.5 else "l"] += 1
        if r["cp_white"] is not None:
            a["ev"].append(r["cp_white"] if color == "White" else -r["cp_white"])
    # theory moves you haven't played here (from the bundled opening list), so you can star them too
    try:
        import theory
        th = theory.children(b.fen())
        played = len(agg)
        for i, c in enumerate(th):
            if c["uci"] not in agg and played and i >= 3 and not (rep and rep["uci"] == c["uci"]):
                continue                          # where you have games, only the main theory moves you haven't tried
            if c["uci"] not in agg:
                agg[c["uci"]] = {"uci": c["uci"], "san": c["san"], "n": 0, "w": 0, "d": 0, "l": 0, "ev": [], "theory_only": True}
            else:
                agg[c["uci"]]["theory"] = True
    except Exception:
        pass
    out = []
    for a in sorted(agg.values(), key=lambda x: (-x["n"], x.get("theory_only", False))):
        nb = b.copy(stack=False); nb.push(chess.Move.from_uci(a["uci"]))
        hit = openings().get(_epd(nb.fen()))
        ev = a.pop("ev")
        a["score"] = round(100 * (a["w"] + 0.5 * a["d"]) / a["n"]) if a["n"] else None
        a["eval"] = round(sum(ev) / len(ev) / 100, 2) if ev else None
        a["eval_n"] = len(ev)
        a["name"] = f"{hit[0]} {hit[1]}" if hit else None
        a["rep"] = bool(rep and rep["uci"] == a["uci"])
        out.append(a)
    total = sum(a["n"] for a in out)
    if rep and not any(a["uci"] == rep["uci"] for a in out):   # a starred move nobody played and not in theory
        out.append({"uci": rep["uci"], "san": rep["san"], "n": 0, "w": 0, "d": 0, "l": 0, "score": None, "eval": None,
                    "eval_n": 0, "name": None, "rep": True, "theory_only": True})
    name = next((p["opening"] for p in reversed(path) if p["opening"]), None)
    my_turn = (b.turn == chess.WHITE) == (color == "White")
    return {"fen": b.fen(), "path": path, "turn": "White" if b.turn else "Black", "my_turn": my_turn,
            "opening": name, "games": total if not moves else max(total, reached or 0), "moves": out,
            "rep": {"uci": rep["uci"], "san": rep["san"]} if rep else None, "index": INDEXER.status}


# ---------------------------------------------------------------------------
# line scan: your best and worst lines in the first 16 half-moves
# ---------------------------------------------------------------------------

def scan(color: str, tc: str = "", since: str = "", k: int = 5) -> dict:
    where, args = _filters(color, tc, since)
    with store.db() as con:
        ensure_schema(con)
        rows = con.execute(
            f"SELECT m.g, m.ply, m.uci, m.san, g.result FROM op_moves m JOIN games g ON g.okey = m.g "
            f"WHERE m.ply <= ? AND {where} ORDER BY m.g, m.ply", (SCAN_MAX_PLIES, *args)).fetchall()
    games: dict = {}
    for r in rows:
        g = games.setdefault(r["g"], {"res": r["result"], "moves": []})
        g["moves"].append((r["uci"], r["san"]))
    n_games = len(games)
    min_n = max(8, round(0.005 * n_games))
    lines: dict = {}
    for g in games.values():
        s = _score(g["res"], color)
        key = ()
        for uci, san in g["moves"]:
            key = key + (uci,)
            L = lines.setdefault(key, {"n": 0, "pts": 0.0, "san": None})
            if L["san"] is None:
                L["san"] = [m[1] for m in g["moves"][:len(key)]]
            L["n"] += 1
            L["pts"] += s
    cands = []
    for key, L in lines.items():
        if len(key) < 4 or L["n"] < min_n:
            continue
        bb = chess.Board()
        for u in key:
            bb.push(chess.Move.from_uci(u))
        hit = openings().get(_epd(bb.fen()))
        if not hit:
            continue                      # only lines that end on a named opening position
        cands.append({"moves": list(key), "san": L["san"], "n": L["n"], "score": round(100 * L["pts"] / L["n"]),
                      "name": f"{hit[0]} {hit[1]}"})
    # one line per opening name: the deepest with enough games
    best_by_name: dict = {}
    for c in cands:
        o = best_by_name.get(c["name"])
        if o is None or len(c["moves"]) > len(o["moves"]):
            best_by_name[c["name"]] = c
    uniq = list(best_by_name.values())
    overall = round(100 * sum(_score(g["res"], color) for g in games.values()) / n_games) if n_games else None
    return {"games": n_games, "min_games": min_n, "overall": overall,
            "worst": sorted(uniq, key=lambda c: (c["score"], -c["n"]))[:k],
            "best": sorted(uniq, key=lambda c: (-c["score"], -c["n"]))[:k]}


# ---------------------------------------------------------------------------
# repertoire
# ---------------------------------------------------------------------------

def set_move(color: str, moves: list[str], uci: Optional[str]) -> dict:
    """Star (or unstar, uci=None) your move in the position reached by `moves`."""
    b, path = _walk(moves)
    if (b.turn == chess.WHITE) != (color == "White"):
        raise ValueError("it isn't your move in that position")
    epd = _epd(b.fen())
    with store.db() as con:
        ensure_schema(con)
        if uci is None:
            con.execute("DELETE FROM repertoire WHERE color = ? AND epd = ?", (color, epd))
    if uci is None:
        import study
        study.sync_lines(color)
        return {"ok": True}
    with store.db() as con:
        mv = chess.Move.from_uci(uci)
        if mv not in b.legal_moves:
            raise ValueError("that move isn't legal here")
        old = con.execute("SELECT uci FROM repertoire WHERE color = ? AND epd = ?", (color, epd)).fetchone()
        if old and old["uci"] == uci:
            return {"ok": True}
        n = con.execute("SELECT COUNT(*) FROM op_moves m JOIN games g ON g.okey = m.g WHERE m.z = ? AND m.uci = ? AND g.player_color = ?",
                        (zkey(b), uci, color)).fetchone()[0]
        keep = con.execute("SELECT opening FROM repertoire WHERE color = ? AND epd = ?", (color, epd)).fetchone()
        con.execute("INSERT OR REPLACE INTO repertoire (color, epd, uci, san, fen, path, games, created, opening, source) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (color, epd, uci, b.san(mv), b.fen(), json.dumps(moves), n, time.time(), keep["opening"] if keep else None, "you"))
    import study
    study.sync_lines(color)
    return {"ok": True}


def build_from_games(color: str, rating: Optional[int], tc: str = "", since: str = "") -> dict:
    """Star your most-played move along every line you meet often enough, up to the rating cap."""
    cap = depth_cap(rating)
    where, args = _filters(color, tc, since)
    with store.db() as con:
        ensure_schema(con)
        rows = con.execute(
            f"SELECT m.z, m.uci, m.san, COUNT(*) n FROM op_moves m JOIN games g ON g.okey = m.g "
            f"WHERE {where} GROUP BY m.z, m.uci", tuple(args)).fetchall()
        total = con.execute(f"SELECT COUNT(*) FROM games g WHERE {where}", tuple(args)).fetchone()[0]
        have = {r["epd"] for r in con.execute("SELECT epd FROM repertoire WHERE color = ?", (color,))}
    by_pos: dict = {}
    for r in rows:
        by_pos.setdefault(r["z"], []).append(r)
    floor = max(MIN_GAMES, MIN_SHARE * total)
    added = 0
    start = chess.Board()
    stack = [(start, [], 0)]                       # board, moves from start, your moves so far
    seen = set()
    new_rows = []
    while stack:
        b, moves, mine = stack.pop()
        epd = _epd(b.fen())
        if epd in seen:
            continue
        seen.add(epd)
        opts = [r for r in by_pos.get(zkey(b), []) if r["n"] >= floor]
        if not opts:
            continue
        my_turn = (b.turn == chess.WHITE) == (color == "White")
        if my_turn:
            if mine >= cap:
                continue
            pick = max(opts, key=lambda r: r["n"])
            if epd not in have:
                new_rows.append((color, epd, pick["uci"], pick["san"], b.fen(), json.dumps(moves), pick["n"], time.time()))
                added += 1
            nb = b.copy(stack=False); nb.push(chess.Move.from_uci(pick["uci"]))
            stack.append((nb, moves + [pick["uci"]], mine + 1))
        else:
            for r in opts:
                nb = b.copy(stack=False); nb.push(chess.Move.from_uci(r["uci"]))
                stack.append((nb, moves + [r["uci"]], mine))
    with store.db() as con:
        con.executemany("INSERT OR IGNORE INTO repertoire (color, epd, uci, san, fen, path, games, created, source) VALUES (?,?,?,?,?,?,?,?,'games')", new_rows)
    import study
    lines = study.sync_lines(color)
    return {"added": added, "cap": cap, "floor": round(floor, 1), "lines": lines}


def coverage(color: str) -> dict:
    """How often your games followed your starred moves, and where you left them."""
    with store.db() as con:
        ensure_schema(con)
        rep = {zkey(chess.Board(r["fen"])): (r["uci"], r["san"], r["fen"], r["path"]) for r in con.execute(
            "SELECT epd, uci, san, fen, path FROM repertoire WHERE color = ?", (color,))}
        rows = con.execute(
            "SELECT g.id AS game_id, m.ply, m.z, m.uci, m.san, g.played_at FROM op_moves m JOIN games g ON g.okey = m.g "
            "WHERE g.player_color = ? ORDER BY m.g, m.ply", (color,)).fetchall()
    if not rep:
        return {"lines": 0, "games": 0, "followed": 0, "share": None, "left": []}
    games: dict = {}
    for r in rows:
        games.setdefault(r["game_id"], []).append(r)
    met = followed = 0
    left: dict = {}
    for gid, mvs in games.items():
        hit = False
        dev = None
        for r in mvs:
            if r["z"] in rep:
                hit = True
                if r["uci"] != rep[r["z"]][0]:
                    dev = r
                    break
        if not hit:
            continue
        met += 1
        if dev is None:
            followed += 1
            continue
        key = dev["z"]
        pth = json.loads(rep[key][3])
        L = left.setdefault(key, {"fen": rep[key][2], "path": pth, "path_san": _walk(pth)[1] if pth else [], "planned": rep[key][1],
                                  "played": {}, "n": 0, "last": None, "last_game": None})
        L["n"] += 1
        L["played"][dev["san"]] = L["played"].get(dev["san"], 0) + 1
        if not L["last"] or (dev["played_at"] or "") > L["last"]:
            L["last"], L["last_game"] = dev["played_at"], gid
    out = sorted(left.values(), key=lambda x: -x["n"])[:8]
    for L in out:
        L["played"] = sorted(L["played"].items(), key=lambda kv: -kv[1])
    return {"lines": len(rep), "games": met, "followed": followed,
            "share": round(100 * followed / met) if met else None, "left": out}


def rep_map(color: str) -> dict:
    with store.db() as con:
        ensure_schema(con)
        return {r["epd"]: (r["uci"], r["san"]) for r in con.execute("SELECT epd, uci, san FROM repertoire WHERE color = ?", (color,))}


# ---------------------------------------------------------------------------
# drills: your own daily number, a small SM-2 like the puzzles
# ---------------------------------------------------------------------------

def drill_queue(color: str = "", more: bool = False, opening: str = "") -> dict:
    s = store.get_settings()
    per_day = max(1, int(s.get("drills_per_day", 10) or 10))
    day = today()
    w, a = ("color = ?", [color]) if color else ("1", [])
    if opening:
        w += " AND opening = ?"; a = a + [opening]
    with store.db() as con:
        ensure_schema(con)
        done = con.execute("SELECT COUNT(*) FROM drill_log WHERE day = ?", (day,)).fetchone()[0]
        done_keys = {(r[0], r[1]) for r in con.execute("SELECT color, epd FROM drill_log WHERE day = ?", (day,))}
        due = [dict(r) for r in con.execute(f"SELECT * FROM repertoire WHERE {w} AND due IS NOT NULL AND due <= ? ORDER BY due", (*a, day))]
        new = [dict(r) for r in con.execute(f"SELECT * FROM repertoire WHERE {w} AND due IS NULL ORDER BY games DESC, LENGTH(path), created", tuple(a))]
        total = con.execute(f"SELECT COUNT(*) FROM repertoire WHERE {w}", tuple(a)).fetchone()[0]
        all_rep = {(r["color"], r["epd"]): dict(r) for r in con.execute("SELECT * FROM repertoire")}
    due = [d for d in due if (d["color"], d["epd"]) not in done_keys]
    new = [d for d in new if (d["color"], d["epd"]) not in done_keys]
    left = max(0, per_day - done)
    items = (due + new) if more else (due + new)[:left]
    for d in items:
        d["path"] = json.loads(d["path"])
        d["line"] = _line_after(d, all_rep)
    return {"day": day, "per_day": per_day, "done_today": done, "queue": items, "due_count": len(due),
            "new_count": len(new), "total": total}


def _line_after(card: dict, all_rep: dict, max_mine: int = 3) -> list[str]:
    """The drill: your starred move, then (while your games continue it) their most common reply and your next starred move."""
    b = chess.Board(card["fen"])
    line = [card["uci"]]
    b.push(chess.Move.from_uci(card["uci"]))
    color = card["color"]
    with store.db() as con:
        for _ in range(max_mine - 1):
            r = con.execute(
                "SELECT m.uci, COUNT(*) n FROM op_moves m JOIN games g ON g.okey = m.g WHERE m.z = ? AND g.player_color = ? "
                "GROUP BY m.uci ORDER BY n DESC LIMIT 1", (zkey(b), color)).fetchone()
            reply = chess.Move.from_uci(r["uci"]) if r else None
            if reply is None or reply not in b.legal_moves:
                reply = None
                for mv in b.legal_moves:          # no game reached it: a reply your repertoire answers
                    b2 = b.copy(stack=False); b2.push(mv)
                    if (color, _epd(b2.fen())) in all_rep:
                        reply = mv
                        break
                if reply is None:
                    break
            b2 = b.copy(stack=False); b2.push(reply)
            nxt = all_rep.get((color, _epd(b2.fen())))
            if not nxt:
                break
            line += [reply.uci(), nxt["uci"]]
            b = b2
            b.push(chess.Move.from_uci(nxt["uci"]))
    return line


def drill_result(color: str, epd: str, result: str) -> dict:
    if result not in ("solved", "failed"):
        raise ValueError("result must be solved or failed")
    day = today()
    with store.db() as con:
        ensure_schema(con)
        r = con.execute("SELECT * FROM repertoire WHERE color = ? AND epd = ?", (color, epd)).fetchone()
        if r is None:
            raise KeyError(epd)
        interval, ease, reps, lapses = r["interval"], r["ease"], r["reps"], r["lapses"]
        if result == "solved":
            reps += 1
            interval = 1 if reps == 1 else 3 if reps == 2 else interval * ease
            ease = min(3.0, ease + 0.1)
        else:
            reps, lapses, interval, ease = 0, lapses + 1, 1.0, max(1.3, ease - 0.2)
        due = (_dt.date.fromisoformat(day) + _dt.timedelta(days=max(1, round(interval)))).isoformat()
        con.execute("UPDATE repertoire SET interval=?, ease=?, reps=?, lapses=?, due=?, last_result=?, last_at=? WHERE color=? AND epd=?",
                    (interval, ease, reps, lapses, due, result, time.time(), color, epd))
        con.execute("INSERT INTO drill_log VALUES (?,?,?,?,?)", (color, epd, day, result, time.time()))
    return {"due": due, "interval": round(interval, 1)}
