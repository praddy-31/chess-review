"""
Opening theory from the bundled Lichess opening list (CC0), for learning an
opening you don't play yet (V6).

The list holds every position on a named line (named or "on the way"). Joined
by legal moves they form a theory tree: from the start position, a move is
theory when the position after it is in the list. Built once, cached in the
data folder.

learn(color, path) adds an opening to your repertoire:
  - along the path to the named position: your move at each of your turns;
  - below it, inside theory: your move = the main line (the child with the
    biggest theory subtree, preferring one that keeps the opening's name);
    their moves = every named reply, each a branch;
  - past the end of theory, Stockfish adds its top reply and your best move,
    until your rating's depth cap.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from typing import Optional

import chess
import chess.engine

import store
from chess_analysis import openings, _epd, _openings_path

START_EPD = _epd(chess.STARTING_FEN)
MAX_STARS = 80            # per opening added
MAX_ENGINE = 40           # engine positions per opening added
ENGINE_DEPTH = 14
_lock = threading.Lock()
_T: Optional[dict] = None


def _cache_path() -> str:
    return os.path.join(store.data_dir(), "theory-cache.json")


def _shipped_path() -> str:
    """The tree built at packaging time (tools/make_theory.py), next to openings.tsv."""
    src = _openings_path()
    return os.path.join(os.path.dirname(src), "theory.json") if src else ""


def tree() -> dict:
    """{'kids': {epd: [[uci, san, child_epd], ...]}, 'parent': {epd: [parent_epd, uci]}, 'size': {epd: n}}"""
    global _T
    with _lock:
        if _T is not None:
            return _T
        src = _openings_path()
        stamp = f"{os.path.getsize(src)}:{int(os.path.getmtime(src))}" if src else "none"
        for p in (_shipped_path(), _cache_path()):
            try:
                with open(p, encoding="utf-8") as f:
                    c = json.load(f)
                if c.get("stamp") == stamp or (p == _shipped_path() and c.get("lines") == _count_lines(src)):
                    _T = c
                    return _T
            except (OSError, ValueError, TypeError):
                pass
        ops = openings()
        kids: dict = {}
        parent: dict = {START_EPD: None}
        q = deque([chess.Board()])
        while q:
            b = q.popleft()
            e = _epd(b.fen())
            out = []
            for mv in b.legal_moves:
                san = b.san(mv)
                b.push(mv)
                ce = _epd(b.fen())
                if ce in ops:
                    out.append([mv.uci(), san, ce])
                    if ce not in parent:
                        parent[ce] = [e, mv.uci()]
                        q.append(b.copy(stack=False))
                b.pop()
            if out:
                kids[e] = out
        size: dict = {}

        def sz(e, seen):
            if e in size:
                return size[e]
            seen.add(e)
            n = 1 + sum(sz(c[2], seen) for c in kids.get(e, []) if c[2] not in seen)
            size[e] = n
            return n
        import sys
        old = sys.getrecursionlimit()
        sys.setrecursionlimit(max(old, 20000))
        try:
            sz(START_EPD, set())
        finally:
            sys.setrecursionlimit(old)
        _T = {"stamp": stamp, "lines": _count_lines(src), "kids": kids, "parent": parent, "size": size}
        try:
            with open(_cache_path(), "w", encoding="utf-8") as f:
                json.dump(_T, f)
        except OSError:
            pass
        return _T


def _count_lines(src: str) -> int:
    try:
        with open(src, encoding="utf-8") as f:
            return sum(1 for _ in f)
    except (OSError, TypeError):
        return -1


def path_to(epd: str) -> list[str]:
    """Moves (UCI) from the start to a theory position, along the first path found."""
    t = tree()
    out = []
    cur = epd
    while cur and t["parent"].get(cur):
        p, u = t["parent"][cur]
        out.append(u)
        cur = p
    return list(reversed(out))


def children(fen: str) -> list[dict]:
    """Theory moves in a position: [{'uci','san','name','size'}], main line first."""
    t = tree()
    ops = openings()
    out = []
    for u, san, ce in t["kids"].get(_epd(fen), []):
        hit = ops.get(ce)
        out.append({"uci": u, "san": san, "name": f"{hit[0]} {hit[1]}" if hit else None, "size": t["size"].get(ce, 1)})
    return sorted(out, key=lambda c: -c["size"])


def search(q: str, limit: int = 40) -> list[dict]:
    """Named openings matching every word of q (case, apostrophes and hyphens ignored)."""
    import re
    norm = lambda s: re.sub(r"\s+", " ", re.sub(r"[-_:,./()]+", " ", re.sub(r"['’‘`´]", "", s.lower()))).strip()
    words = norm(q).split()
    t = tree()
    seen = set()
    out = []
    for epd, v in openings().items():
        if not v or epd not in t["parent"]:
            continue
        eco, name = v
        if (eco, name) in seen:
            continue
        hay = norm(f"{eco} {name}")
        if words and not all(w in hay for w in words):
            continue
        seen.add((eco, name))
        path = path_to(epd)
        out.append({"eco": eco, "name": name, "epd": epd, "moves": path, "plies": len(path), "size": t["size"].get(epd, 1)})
    # the family's main entries first: short names and shallow lines, then by theory below them
    out.sort(key=lambda r: (r["name"].count(":") + r["name"].count(","), r["plies"], -r["size"]))
    for r in out[:limit]:
        b = chess.Board()
        sans = []
        for u in r["moves"]:
            mv = chess.Move.from_uci(u)
            sans.append(b.san(mv)); b.push(mv)
        r["san"] = sans
        r["fen"] = b.fen()
        r["side"] = "Black" if any(w in r["name"] for w in ("Defense", "Defence", "Countergambit", "Counter-Gambit")) else "White"
    return out[:limit]


# ---------------------------------------------------------------------------
# adding an opening to the repertoire
# ---------------------------------------------------------------------------

def _engine():
    import engines
    path = engines._which("stockfish", store.get_settings().get("stockfish_path", ""))
    if not path:
        return None
    eng = chess.engine.SimpleEngine.popen_uci(path)
    try:
        eng.configure({"Threads": 1, "Hash": 64})
    except Exception:
        pass
    return eng


def learn(color: str, moves: list[str], rating: Optional[int], use_engine: bool = True, level: Optional[int] = None) -> dict:
    """Adds an opening to your repertoire. `level` 1-5 sets the line length (3 = the rating-based
    recommendation, 5 = to the end of named theory plus 4 of your moves from Stockfish)."""
    import repertoire as rp
    import study
    if color not in ("White", "Black"):
        raise ValueError("color must be White or Black")
    b, path = rp._walk(moves)
    name = next((p["opening"] for p in reversed(path) if p["opening"]), "Starting position")
    family = name.split(" ", 1)[1].split(":")[0] if " " in name else name
    level = int(level or store.get_settings().get("learn_depth", 3) or 3)
    level = min(5, max(1, level))
    cap = study.level_moves(level, rating)
    tail = 4 if level == 5 else None          # engine moves allowed past the end of theory (None = up to the cap)
    max_stars = MAX_STARS * (2 if level >= 4 else 1)
    mine_of = lambda bd: (bd.turn == chess.WHITE) == (color == "White")
    stars: list[tuple] = []          # (fen, moves, uci, san, source)
    replaced = 0

    # 1. along the path: your moves
    bb = chess.Board()
    for i, u in enumerate(moves):
        if mine_of(bb):
            mv = chess.Move.from_uci(u)
            stars.append((bb.fen(), moves[:i], u, bb.san(mv), "theory"))
        bb.push(chess.Move.from_uci(u))
    mine_count = sum(1 for s in stars)

    # 2. below: theory, then the engine
    eng = _engine() if use_engine else None
    engine_used = 0
    try:
        stack = [(b.copy(stack=False), list(moves), mine_count, 0)]
        seen = set()
        while stack and len(stars) < max_stars:
            bd, mvs, mine, eng_n = stack.pop()
            e = _epd(bd.fen())
            if e in seen or bd.is_game_over():
                continue
            seen.add(e)
            th = children(bd.fen())
            if mine_of(bd):
                if mine >= cap:
                    continue
                pick = None
                if th:
                    keep = [c for c in th if not c["name"] or family in c["name"]] or th   # unnamed = on the way to more of it
                    pick = keep[0]
                    if eng is not None and len(keep) > 1 and engine_used < MAX_ENGINE:
                        # several theory moves: the main line (most theory below it) among those
                        # Stockfish rates within half a pawn of the best - sound and well-trodden
                        infos = eng.analyse(bd, chess.engine.Limit(depth=12), multipv=min(5, len(keep)),
                                            root_moves=[chess.Move.from_uci(c["uci"]) for c in keep])
                        engine_used += 1
                        sc = {}
                        for inf in infos if isinstance(infos, list) else [infos]:
                            if inf.get("pv"):
                                sc[inf["pv"][0].uci()] = inf["score"].relative.score(mate_score=10000)
                        if sc:
                            top = max(sc.values())
                            ok = [c for c in keep if c["uci"] in sc and sc[c["uci"]] >= top - 50]
                            pick = max(ok, key=lambda c: c["size"]) if ok else pick
                    src = "theory"
                elif eng is not None and engine_used < MAX_ENGINE * (2 if level >= 4 else 1) and (tail is None or eng_n < tail):
                    info = eng.analyse(bd, chess.engine.Limit(depth=ENGINE_DEPTH))
                    engine_used += 1
                    mv = (info.get("pv") or [None])[0]
                    if mv is not None:
                        pick = {"uci": mv.uci(), "san": bd.san(mv)}
                    src = "engine"
                if not pick:
                    continue
                stars.append((bd.fen(), mvs, pick["uci"], pick["san"], src))
                nb = bd.copy(stack=False); nb.push(chess.Move.from_uci(pick["uci"]))
                stack.append((nb, mvs + [pick["uci"]], mine + 1, eng_n + (src == "engine")))
            else:
                replies = [c["uci"] for c in th]
                if (not replies and eng is not None and engine_used < MAX_ENGINE * (2 if level >= 4 else 1) and mine < cap
                        and (tail is None or eng_n < tail)):
                    info = eng.analyse(bd, chess.engine.Limit(depth=ENGINE_DEPTH))
                    engine_used += 1
                    mv = (info.get("pv") or [None])[0]
                    if mv is not None:
                        replies = [mv.uci()]
                for u in reversed(replies):          # main reply explored first
                    nb = bd.copy(stack=False); nb.push(chess.Move.from_uci(u))
                    stack.append((nb, mvs + [u], mine, eng_n))
    finally:
        if eng is not None:
            try:
                eng.quit()
            except Exception:
                pass

    added = trimmed = 0
    with store.db() as con:
        study.ensure_schema(con)
        # a shorter length than before: drop this opening's moves past the new end
        for r in con.execute("SELECT epd, path FROM repertoire WHERE color = ? AND opening = ?", (color, name)).fetchall():
            if len(json.loads(r["path"])) // 2 >= cap:
                con.execute("DELETE FROM repertoire WHERE color = ? AND epd = ?", (color, r["epd"]))
                trimmed += 1
        con.execute("INSERT OR REPLACE INTO study_openings (color, opening, moves, level, added) VALUES (?,?,?,?,COALESCE("
                    "(SELECT added FROM study_openings WHERE color = ? AND opening = ?), ?))",
                    (color, name, json.dumps(moves), level, color, name, time.time()))
        for fen, mvs, uci, san, src in stars:
            e = _epd(fen)
            old = con.execute("SELECT uci, opening FROM repertoire WHERE color = ? AND epd = ?", (color, e)).fetchone()
            if old and old["uci"] == uci:
                if not old["opening"]:
                    con.execute("UPDATE repertoire SET opening = ? WHERE color = ? AND epd = ?", (name, color, e))
                continue
            if old:
                replaced += 1
            n = con.execute("SELECT COUNT(*) FROM op_moves m JOIN games g ON g.okey = m.g WHERE m.z = ? AND m.uci = ? AND g.player_color = ?",
                            (rp.zkey(chess.Board(fen)), uci, color)).fetchone()[0]
            con.execute("INSERT OR REPLACE INTO repertoire (color, epd, uci, san, fen, path, games, created, opening, source) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)", (color, e, uci, san, fen, json.dumps(mvs), n, time.time(), name, src))
            added += 1
    lines = study.sync_lines(color)
    return {"opening": name, "added": added, "replaced": replaced, "trimmed": trimmed, "theory": sum(1 for s in stars if s[4] == "theory"),
            "engine": sum(1 for s in stars if s[4] == "engine"), "cap": cap, "level": level, "lines": lines}


def by_name(name: str) -> Optional[dict]:
    """The theory entry for an exact opening name ('B07 Pirc Defense' or 'Pirc Defense')."""
    nm = name.split(" ", 1)[1] if len(name) > 4 and name[0] in "ABCDE" and name[1:3].isdigit() and name[3] == " " else name
    t = tree()
    best = None
    for epd, v in openings().items():
        if v and v[1] == nm and epd in t["parent"]:
            p = path_to(epd)
            if best is None or len(p) < len(best["moves"]):
                best = {"eco": v[0], "name": v[1], "epd": epd, "moves": p}
    if best:
        b = chess.Board()
        best["san"] = []
        for u in best["moves"]:
            mv = chess.Move.from_uci(u); best["san"].append(b.san(mv)); b.push(mv)
        best["fen"] = b.fen()
        best["side"] = "Black" if any(w in nm for w in ("Defense", "Defence", "Countergambit")) else "White"
    return best


def recent(color: str, days: int = 90, limit: int = 8) -> list[dict]:
    """Openings from your recent games (by the family name, e.g. "King's Indian Attack"), newest first,
    with how often you played each lately and before - so what you play now outranks what you used to."""
    since = time.strftime("%Y-%m-%d", time.gmtime(time.time() - days * 86400))
    with store.db() as con:
        rows = con.execute("SELECT opening, played_at FROM games WHERE player_color = ? AND opening IS NOT NULL AND opening != ''",
                           (color,)).fetchall()
    fam: dict = {}
    for r in rows:
        f = r["opening"].split(":")[0].split(",")[0].strip()      # "King's Indian Attack, with e6" -> the family
        d = fam.setdefault(f, {"family": f, "recent": 0, "before": 0, "last": ""})
        if (r["played_at"] or "") >= since:
            d["recent"] += 1
        else:
            d["before"] += 1
        d["last"] = max(d["last"], r["played_at"] or "")
    out = [d for d in fam.values() if d["recent"]]
    out.sort(key=lambda d: (-d["recent"], d["last"]), reverse=False)
    out = sorted(out, key=lambda d: -d["recent"])[:limit]
    for d in out:
        e = by_name(d["family"])
        if e:
            d.update({k: e[k] for k in ("eco", "moves", "san", "fen", "side")})
    return [d for d in out if "moves" in d]


def my_openings(color: str = "") -> list[dict]:
    """The openings you are learning (added by name), with drill progress."""
    import repertoire as rp
    day = rp.today()
    with store.db() as con:
        rp.ensure_schema(con)
        rows = con.execute(
            "SELECT color, opening, COUNT(*) n, SUM(reps >= 3) learned, SUM(due IS NOT NULL AND due <= ?) due, SUM(due IS NULL) new, "
            "MIN(created) since FROM repertoire WHERE opening IS NOT NULL" + (" AND color = ?" if color else "") +
            " GROUP BY color, opening ORDER BY MIN(created) DESC", (day, color) if color else (day,)).fetchall()
    return [dict(r) for r in rows]


def forget_opening(color: str, name: str) -> int:
    import study
    with store.db() as con:
        study.ensure_schema(con)
        n = con.execute("DELETE FROM repertoire WHERE color = ? AND opening = ?", (color, name)).rowcount
        con.execute("DELETE FROM study_openings WHERE color = ? AND opening = ?", (color, name))
    study.sync_lines(color)
    return n
