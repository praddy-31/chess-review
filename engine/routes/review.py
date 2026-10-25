"""
One game: exports (Obsidian, annotated PGN), notes and tags, retry-this-move grading, positions and lines, the practical move.
"""

from __future__ import annotations

import threading

from api import ApiError, route
import engines
import export_pgn
import practical
import store
import system
from export_md import game_markdown


@route("GET", r"/api/games/(?P<gid>[^/]+)/export")
def api_export(body, q, gid):
    s = store.get_settings()
    rv = store.load_review(gid, store.thresholds_from(s))
    if not rv:
        raise ApiError(404, "analyse the game first")
    lines = q.get("lines", ["1" if s["export_lines"] else "0"])[0] == "1"
    comments = q.get("comments", ["1" if s["export_comments"] else "0"])[0] == "1"
    md = game_markdown(rv, with_lines=lines, with_comments=comments)
    nt = store.get_notes(gid)          # V7: your own notes and tags travel with the export
    if nt["notes"] or nt["tags"]:
        by_ply = {p.ply: p for p in rv.raw}
        extra = ["", "## My notes"]
        if nt["tags"]:
            extra.append("Tags: " + ", ".join(nt["tags"]))
        if nt["notes"].get(0):
            extra.append(nt["notes"][0])
        for ply in sorted(k for k in nt["notes"] if k):
            p = by_ply.get(ply)
            mv = f"{p.move_number}{'.' if p.color == 'White' else '...'}{p.played_san}" if p else f"ply {ply}"
            extra.append(f"- {mv}: {nt['notes'][ply]}")
        md = md.rstrip("\n") + "\n" + "\n".join(extra) + "\n"
    return {"markdown": md}


@route("GET", r"/api/games/(?P<gid>[^/]+)/pgn")
def api_export_pgn(body, q, gid):
    """V10: the game as annotated PGN (labels as NAGs, verdicts, evals, better lines, notes)."""
    s = store.get_settings()
    lines = q.get("lines", ["1" if s["export_lines"] else "0"])[0] == "1"
    comments = q.get("comments", ["1" if s["export_comments"] else "0"])[0] == "1"
    pgn = export_pgn.annotate(gid, lines, comments)
    if pgn is None:
        raise ApiError(404, "no such game")
    return {"pgn": pgn}


@route("POST", r"/api/export/pgn")
def api_export_pgn_many(body, q):
    """V10: the ticked Library games in one PGN file."""
    b = body or {}
    ids = [i for i in (b.get("ids") or []) if isinstance(i, str)]
    if not ids:
        raise ApiError(400, "tick some games first")
    s = store.get_settings()
    return export_pgn.export_many(ids, bool(b.get("lines", s["export_lines"])), bool(b.get("comments", s["export_comments"])))


class _Grader:
    """One Stockfish kept open for grading moves you try on the board."""
    def __init__(self):
        self.lock = threading.Lock()
        self.engine = None

    def _get(self):
        import chess.engine
        if self.engine is None:
            s = store.get_settings()
            path = engines._which("stockfish", s.get("stockfish_path", ""))
            if not path:
                raise ApiError(400, system.install_hint("stockfish"))
            self.engine = chess.engine.SimpleEngine.popen_uci(path)
            try:
                self.engine.configure({"Threads": max(1, int(s.get("threads", 2))), "Hash": 128})
            except Exception:
                pass
        return self.engine

    def grade(self, fen: str, uci: str, depth: int, fastest: bool = False) -> dict:
        import chess
        import chess.engine
        from chess_analysis import Thresholds, win_percent, _score_to_cp_and_mate, _san_line
        board = chess.Board(fen)
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            raise ApiError(400, "that move isn't legal here")
        with self.lock:
            try:
                eng = self._get()
                limit = chess.engine.Limit(depth=depth)
                pre = eng.analyse(board, limit)
                after = board.copy(); after.push(move)
                post = None if after.is_game_over() else eng.analyse(after, limit)
            except chess.engine.EngineError:
                self.engine = None
                raise
        cp_b, m_b = _score_to_cp_and_mate(pre["score"])
        if after.is_checkmate():
            cp_a, m_a = None, 0
        elif post is None:
            cp_a, m_a = 0, None
        else:
            a_cp, a_m = _score_to_cp_and_mate(post["score"])
            cp_a, m_a = (-a_cp if a_cp is not None else None), (-a_m if a_m is not None else None)
        best = (pre.get("pv") or [move])[0]
        wb, wa = win_percent(cp_b, m_b), (100.0 if after.is_checkmate() else win_percent(cp_a, m_a))
        pp = 0.0 if move == best else max(0.0, wb - wa)
        t = store.thresholds_from(store.get_settings())
        label = ("Best" if pp < 1 else "Good" if pp < t.inaccuracy_pp else "Inaccuracy" if pp < t.mistake_pp
                 else "Mistake" if pp < t.blunder_pp else "Blunder")
        # A retry is solved only when it is close to the best move (within 3 points)
        # and keeps a forced mate when one was there - "Good" alone is too loose.
        kept_mate = m_b is None or m_b <= 0 or after.is_checkmate() or (m_a is not None and m_a > 0)
        solved = (move == best) or (pp < 3 and kept_mate)
        # puzzles: with a short forced mate on the board only an equally fast mate is another answer
        slower = False
        if fastest and m_b is not None and 0 < m_b <= 4 and move != best and not after.is_checkmate():
            fast = m_a is not None and m_a > 0 and m_a <= m_b - 1
            slower = solved and not fast
            solved = solved and fast
        return {"san": board.san(move), "label": label, "pp": round(pp, 1), "solved": solved, "slower": slower,
                "mate_before": m_b if (m_b or 0) > 0 else None, "mate_after": m_a if (m_a or 0) > 0 else None,
                "best_san": board.san(best), "best_uci": best.uci(), "best_line": _san_line(board, pre.get("pv") or [], 6),
                "reply_line": _san_line(after, (post or {}).get("pv") or [], 6),
                "reply_uci": (((post or {}).get("pv") or [None])[0] or chess.Move.null()).uci() if (post or {}).get("pv") else None,
                "win_before": round(wb), "win_after": round(wa)}


    def threat(self, fen: str, depth: int) -> dict:
        """What the side NOT to move threatens: give them the move (a null move) and ask the engine."""
        import chess
        import chess.engine
        from chess_analysis import _score_to_cp_and_mate, comparable
        board = chess.Board(fen)
        if board.is_check() or board.is_game_over():
            return {"uci": None}
        nb = board.copy(stack=False)   # same position, the other side to move (no null move in the history)
        nb.turn = not nb.turn
        nb.ep_square = None
        with self.lock:
            try:
                eng = self._get()
                lim = chess.engine.Limit(depth=depth)
                now = eng.analyse(board, lim)
                th = eng.analyse(nb, lim)
            except chess.engine.EngineError:
                self.engine = None
                raise
        cp0, m0 = _score_to_cp_and_mate(now["score"])           # side to move's view
        cp1, m1 = _score_to_cp_and_mate(th["score"])            # opponent's view, if it were their move
        pv = th.get("pv") or []
        if not pv:
            return {"uci": None}
        base = -comparable(cp0, m0)                              # opponent's view now
        # When the side to move has a forced mate (or is being mated), "now" is a mate score and
        # any free move for the opponent looks like a gain of ~1,000 pawns. Like the analysis probes,
        # only compare plain evals; otherwise the threat counts only if its line wins material or mates.
        plain = m0 is None and m1 is None and abs(base) < 5000
        gain = comparable(cp1, m1) - base if plain else None
        mv = pv[0]
        san = nb.san(mv)
        line = []
        b = nb.copy(stack=False)
        for x in pv[:6]:
            if x not in b.legal_moves:
                break
            line.append(b.san(x)); b.push(x)
        text = ""
        try:
            from motifs import analyse_line
            r = analyse_line(nb.copy(), line, ben_cp=cp1, ben_mate=m1 if (m1 or 0) > 0 else None)
            if r.get("phrase"):
                text = f"{san} {r['phrase']}"
        except Exception:
            pass
        mate = m1 if (m1 or 0) > 0 else None
        from chess_analysis import _line_is_tactical
        tactical = _line_is_tactical(nb.copy(stack=False), pv[:6], pov=nb.turn, min_material=1)
        return {"uci": mv.uci(), "san": san, "line": line, "gain_cp": gain, "mate": mate, "text": text,
                "real": bool(mate) or tactical or (gain is not None and gain >= 150)}


GRADER = _Grader()


@route("POST", r"/api/threat")
def api_threat(body, q):
    fen = (body or {}).get("fen", "")
    try:
        import chess
        chess.Board(fen)
    except ValueError:
        raise ApiError(400, "bad FEN")
    return GRADER.threat(fen, 12)


def _opening_at(fen: str):
    from chess_analysis import openings, _epd
    hit = openings().get(_epd(fen))
    return f"{hit[0]} {hit[1]}" if hit else None


@route("POST", r"/api/position")
def api_position(body, q):
    """Legal moves for a position, so the board can show where a piece may go."""
    import chess
    try:
        board = chess.Board((body or {}).get("fen", ""))
    except ValueError:
        raise ApiError(400, "bad FEN")
    moves = []
    for mv in board.legal_moves:
        san = board.san(mv)
        board.push(mv)
        moves.append({"uci": mv.uci(), "from": chess.square_name(mv.from_square), "to": chess.square_name(mv.to_square),
                      "san": san, "promotion": bool(mv.promotion), "fen": board.fen(), "opening": _opening_at(board.fen())})
        board.pop()
    over = None
    if board.is_checkmate():
        over = "checkmate"
    elif board.is_stalemate():
        over = "stalemate"
    elif board.is_insufficient_material() or board.can_claim_draw():
        over = "draw"
    return {"turn": "White" if board.turn else "Black", "moves": moves, "fen": board.fen(), "opening": _opening_at(board.fen()),
            "check": board.is_check(), "game_over": over, "move_number": board.fullmove_number}


@route("POST", r"/api/line")
def api_line(body, q):
    """Play a list of UCI moves from a FEN: the SAN and position after each (stops at the first illegal one)."""
    import chess
    b = body or {}
    try:
        board = chess.Board(b.get("fen", ""))
    except ValueError:
        raise ApiError(400, "bad FEN")
    out = []
    for u in list(b.get("moves") or [])[:200]:
        try:
            mv = chess.Move.from_uci(u)
        except ValueError:
            break
        if mv not in board.legal_moves:
            break
        san = board.san(mv)
        board.push(mv)
        out.append({"uci": u, "san": san, "fen": board.fen(), "opening": _opening_at(board.fen())})
    return {"steps": out}


@route("POST", r"/api/grade")
def api_grade(body, q):
    b = body or {}
    fen, uci = b.get("fen", ""), b.get("uci", "")
    depth = min(18, int(store.get_settings().get("depth", 16)))
    res = GRADER.grade(fen, uci, depth, fastest=bool(b.get("fastest")))
    if b.get("record", True):   # puzzles grade alternatives without counting them as retries
        store.save_retry(b.get("game_id"), b.get("ply"), fen, uci, res["label"], res["pp"], res["solved"])
    return res


@route("POST", r"/api/retry-gave-up")
def api_retry_gave_up(body, q):
    b = body or {}
    store.save_retry(b.get("game_id"), b.get("ply"), b.get("fen", ""), "", None, None, False, True)
    return {"ok": True}


@route("GET", r"/api/games/(?P<gid>[^/]+)/notes")
def api_notes(body, q, gid):
    return store.get_notes(gid)


@route("POST", r"/api/games/(?P<gid>[^/]+)/notes")
def api_set_note(body, q, gid):
    b = body or {}
    if not store.get_game(gid):
        raise ApiError(404, "game not found")
    store.set_note(gid, int(b.get("ply") or 0), b.get("text", ""))
    return store.get_notes(gid)


@route("POST", r"/api/games/(?P<gid>[^/]+)/tags")
def api_set_tags(body, q, gid):
    if not store.get_game(gid):
        raise ApiError(404, "game not found")
    return {"tags": store.set_tags(gid, list((body or {}).get("tags") or []))}


@route("GET", r"/api/tags")
def api_tags(body, q):
    return {"tags": store.all_tags()}


@route("GET", r"/api/notes/search")
def api_notes_search(body, q):
    words = [w for w in (q.get("q") or [""])[0].lower().split() if w]
    return {"ids": sorted(store.search_notes(words))}


@route("GET", r"/api/practical")
def api_practical(body, q):
    if not practical.available():
        return {"available": False, "practical": None}
    try:
        return {"available": True, "practical": practical.practical((q.get("fen") or [""])[0])}
    except Exception as e:
        return {"available": True, "practical": None, "error": str(e)}
