"""
Phases of a game and how you play each one (V10).

Phases come from Lichess's divider (`divider.py`), the same split the Review,
the move types and the Endgame skill use.

From your analysed games:

  trends()   your accuracy and the win-chance points you lose per move in each
             phase, month by month, and this period against the one before
  heatmap()  where your mistakes and blunders land (the moved piece's square),
             and where you lose pieces (the square of your piece the opponent
             takes on the very next move), both seen from your side of the board
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

import chess

import store
from divider import PHASES, divide, phase_at  # noqa: F401  (divide, phase_at: also used by the self-test)

ERRORS = ("Mistake", "Blunder")
EXAMPLES = 6        # games listed under a heatmap square

_cache: dict = {}   # game id -> (analysed_at, {ply: phase})


def phases_of(gid: str, analysed_at, raw) -> dict:
    """{ply: phase} for every ply of an analysed game (the position before each move decides)."""
    hit = _cache.get(gid)
    if hit and hit[0] == analysed_at:
        return hit[1]
    mid, end = divide([p.fen_before for p in raw])
    out = {p.ply: phase_at(i, mid, end) for i, p in enumerate(raw)}
    _cache[gid] = (analysed_at, out)
    return out


def _entries(tc: str = "") -> list[dict]:
    t = store.thresholds_from(store.get_settings())
    out = []
    for e in store.all_reviews(t, record_only=True):
        g, rv = e["game"], e["review"]
        if not rv.moves or not rv.raw or (tc and (g.get("tc_category") or "") != tc):
            continue
        try:
            when = datetime.strptime((g.get("played_at") or "")[:10], "%Y-%m-%d")
        except ValueError:
            continue
        out.append({"g": g, "rv": rv, "t": when, "ph": phases_of(g["id"], g.get("analysed_at"), rv.raw)})
    return out


def _per_game(e: dict) -> dict:
    """{phase: (sum of accuracy, moves, points lost)} for your moves in one game."""
    acc = defaultdict(lambda: [0.0, 0, 0.0])
    for m in e["rv"].moves:
        if m.severity == "Book":
            continue            # book moves aren't decisions; they'd flatter the opening
        a = acc[e["ph"].get(m.ply, "Middlegame")]
        a[0] += m.accuracy; a[1] += 1; a[2] += m.pp_loss
    return acc


def _summary(es: list[dict]) -> dict:
    out = {}
    for ph in PHASES:
        games = [x[ph] for x in (_per_game(e) for e in es) if x[ph][1]]
        moves = sum(g[1] for g in games)
        out[ph] = {"games": len(games), "moves": moves,
                   "accuracy": round(sum(g[0] for g in games) / moves, 1) if moves else None,
                   "lost_per_move": round(sum(g[2] for g in games) / moves, 1) if moves else None}
    return out


def trends(tc: str = "", days: int = 90, months: int = 12) -> dict:
    es = _entries(tc)
    now = datetime.now()
    cut, cut0 = now - timedelta(days=days), now - timedelta(days=2 * days)
    k = now.year * 12 + now.month - 1 - (months - 1)       # the first of `months` calendar months, this one last
    first = datetime(k // 12, k % 12 + 1, 1)
    by_month = defaultdict(list)
    for e in es:
        if e["t"] >= first:
            by_month[e["t"].strftime("%Y-%m")].append(e)
    series = []
    m = first
    while m <= now:
        k = m.strftime("%Y-%m")
        series.append({"month": k, "games": len(by_month[k]), **_summary(by_month[k])})
        m = (m + timedelta(days=32)).replace(day=1)
    cur = _summary([e for e in es if e["t"] >= cut])
    prev = _summary([e for e in es if cut0 <= e["t"] < cut])
    reached = sum(1 for e in es if e["t"] >= cut and "Endgame" in e["ph"].values())
    return {"tc": tc, "days": days, "series": series, "current": cur, "previous": prev,
            "games": sum(1 for e in es if e["t"] >= cut), "reached_endgame": reached}


def heatmap(tc: str = "", days: int = 0) -> dict:
    """64 counts each (a1 = 0 … h8 = 63, from your side: Black's games are mirrored)."""
    es = _entries(tc)
    if days:
        cut = datetime.now() - timedelta(days=days)
        es = [e for e in es if e["t"] >= cut]
    land, lost = [0] * 64, [0] * 64
    ex_land, ex_lost = defaultdict(list), defaultdict(list)
    for e in es:
        rv, g = e["rv"], e["g"]
        flip = rv.player_color == "Black"
        sq = (lambda s: chess.square_mirror(s)) if flip else (lambda s: s)
        raw = {p.ply: p for p in rv.raw}
        opp = rv.headers.get("Black" if not flip else "White", "?")
        for m in rv.moves:
            if m.severity not in ERRORS:
                continue
            mv = chess.Move.from_uci(m.played_uci)
            s = sq(mv.to_square)
            land[s] += 1
            ex = {"game_id": g["id"], "ply": m.ply, "move": f"{m.label}{m.played_san}", "severity": m.severity,
                  "opponent": opp, "date": (g.get("played_at") or "")[:10], "phase": e["ph"].get(m.ply, "")}
            ex_land[s].append(ex)
            nxt = raw.get(m.ply + 1)
            if nxt is not None:
                b = chess.Board(nxt.fen_before)
                rm = chess.Move.from_uci(nxt.played_uci)
                if b.is_capture(rm) and not b.is_en_passant(rm):
                    t = sq(rm.to_square)
                    lost[t] += 1
                    ex_lost[t].append({**ex, "taken": chess.piece_name(b.piece_type_at(rm.to_square))})
    newest = lambda xs: sorted(xs, key=lambda x: x["date"], reverse=True)[:EXAMPLES]
    return {"games": len(es), "errors": sum(land), "land": land, "lost": lost,
            "examples_land": {str(k): newest(v) for k, v in ex_land.items()},
            "examples_lost": {str(k): newest(v) for k, v in ex_lost.items()}}
