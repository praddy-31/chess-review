"""
Practical move (V8): the move players at your level are most likely to find
that is still nearly as good as the engine's best.

Maia (lc0) at your rating ranks the moves humans play; Stockfish checks the
likely ones (up to 6 with 4%+ probability, plus its own best). The practical
move is the most likely one within 5 points of win chance of the best. When
that is the engine's move anyway, there's nothing extra to show.
Needs Maia installed; results are cached per position.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Optional

import chess
import chess.engine

import store
from chess_analysis import win_percent

WITHIN = 5.0
_CACHE: OrderedDict = OrderedDict()
_LOCK = threading.Lock()


def available() -> bool:
    import engines
    lc0, w = engines.pick_maia(store.get_settings())
    return bool(lc0 and w)


def practical(fen: str) -> Optional[dict]:
    s = store.get_settings()
    key = (fen, store.my_rating(settings=s))
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
    import engines
    from chess_analysis import MaiaEngine
    lc0, w = engines.pick_maia(s)
    if not lc0:
        return None
    board = chess.Board(fen)
    if board.is_game_over():
        return None
    m = MaiaEngine(lc0, w, timeout=20)
    try:
        pol = m.policy(board)
    finally:
        m.quit()
    legal = {mv.uci() for mv in board.legal_moves}
    likely = [u for u, p in sorted(pol.items(), key=lambda t: -t[1]) if u in legal and p >= 0.04][:6]
    path = engines._which("stockfish", s.get("stockfish_path", ""))
    if not path or not likely:
        return None
    eng = chess.engine.SimpleEngine.popen_uci(path)
    try:
        top = eng.analyse(board, chess.engine.Limit(depth=16, time=2.0))
        best = top["pv"][0]
        roots = [chess.Move.from_uci(u) for u in likely if u != best.uci()]
        infos = eng.analyse(board, chess.engine.Limit(depth=14, time=2.5), multipv=len(roots), root_moves=roots) if roots else []
        infos = infos if isinstance(infos, list) else [infos]
    finally:
        eng.quit()
    me = board.turn
    sc = lambda i: (lambda x: win_percent(x.score(), x.mate()))(i["score"].pov(me))
    wbest = sc(top)
    scores = {best.uci(): wbest}
    for i in infos:
        if i.get("pv"):
            scores[i["pv"][0].uci()] = sc(i)
    ok = [u for u in likely + [best.uci()] if u in scores and wbest - scores[u] <= WITHIN]
    pick = max(ok, key=lambda u: pol.get(u, 0)) if ok else best.uci()
    band = w.split("maia-")[-1].split(".")[0] if "maia-" in w else str(store.my_rating(settings=s))
    out = {"uci": pick, "san": board.san(chess.Move.from_uci(pick)), "p": round(100 * pol.get(pick, 0)),
           "gap": round(max(0.0, wbest - scores.get(pick, wbest)), 1), "best_uci": best.uci(), "best_san": board.san(best),
           "p_best": round(100 * pol.get(best.uci(), 0)), "same": pick == best.uci(), "band": band}
    with _LOCK:
        _CACHE[key] = out
        while len(_CACHE) > 300:
            _CACHE.popitem(last=False)
    return out
