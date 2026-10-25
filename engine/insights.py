"""
Cross-game numbers for the Insights page: accuracy per game over time, where
errors cluster (rates, not counts, so a category you play a lot isn't blamed
just for being common), time use, and a comparison across time controls.

Every view can be narrowed to one time control (bullet / blitz / rapid / ...);
the "By time control" table always shows all of them side by side.
"""

from __future__ import annotations

from chess_analysis import time_control_parts
from payload import clock_limits, is_flagged

ORDER = {
    "standing": ["Winning", "Balanced", "Losing"],
    "phase": ["Attack", "Neutral", "Defense"],
    "move_type": ["Opening", "Tactical", "Positional", "Endgame"],
}
TC_ORDER = ["bullet", "blitz", "rapid", "classical", "daily", "unknown"]


def _tc(e: dict) -> str:
    return e["game"].get("tc_category") or "unknown"


def _time_use(entries: list[dict], typical: dict | None = None) -> dict | None:
    """Quick / low-clock counts with limits scaled to each game's own time control."""
    flagged = fast = low = n_timed = fast_moves = 0
    spent_f, spent_ok, n_ok = 0.0, 0.0, 0
    for e in entries:
        base, inc = time_control_parts(e["review"].time_control_raw)
        if not base or _tc(e) == "daily":
            continue
        lim = clock_limits(base, inc, (typical or {}).get(_tc(e)) or 40)
        quick, low_s = lim["quick"], lim["low"]
        for m in e["review"].moves:
            if m.time_spent is None:
                continue
            n_timed += 1
            if m.time_spent < quick:
                fast_moves += 1
            if is_flagged(m):
                flagged += 1
                spent_f += m.time_spent
                fast += m.time_spent < quick
                low += (m.clock_after or 0) + m.time_spent < low_s
            else:
                spent_ok += m.time_spent
                n_ok += 1
    if not flagged:
        return None
    return {"flagged": flagged, "fast": fast, "trouble": low, "moves": n_timed, "fast_moves": fast_moves,
            "avg_flagged": round(spent_f / flagged, 1), "avg_ok": round(spent_ok / n_ok, 1) if n_ok else None}


def _tc_row(tc: str, entries: list[dict], typical: dict | None = None) -> dict:
    moves = [m for e in entries for m in e["review"].moves]
    flagged = [m for m in moves if is_flagged(m)]
    accs = [sum(m.accuracy for m in e["review"].moves) / len(e["review"].moves) for e in entries if e["review"].moves]
    outcomes = [e["game"].get("outcome") for e in entries]
    t = _time_use(entries, typical)
    return {
        "tc": tc, "games": len(entries),
        "accuracy": round(sum(accs) / len(accs), 1) if accs else None,
        "blunders_pg": round(sum(m.severity == "Blunder" for m in moves) / len(entries), 1) if entries else None,
        "mistakes_pg": round(sum(m.severity == "Mistake" for m in moves) / len(entries), 1) if entries else None,
        "flag_rate": round(100 * len(flagged) / len(moves), 1) if moves else None,
        "score": round(100 * (outcomes.count("win") + 0.5 * outcomes.count("draw")) / len(outcomes)) if outcomes else None,
        "fast_flagged_pct": round(100 * t["fast"] / t["flagged"]) if t else None,
    }


def build(entries: list[dict], tc: str = "all", typical: dict | None = None) -> dict:
    """typical: {time control: your median moves per game} where known."""
    """entries: store.all_reviews() output (oldest first)."""
    entries = [e for e in entries if e["review"].moves]
    present = [k for k in TC_ORDER if any(_tc(e) == k for e in entries)]
    by_tc = [_tc_row(k, [e for e in entries if _tc(e) == k], typical) for k in present]
    if tc != "all":
        entries = [e for e in entries if _tc(e) == tc]

    games = []
    for e in entries:
        ms, g = e["review"].moves, e["game"]
        games.append({
            "id": e["id"], "played_at": g.get("played_at") or "", "opponent": g.get("opponent"),
            "outcome": g.get("outcome"), "tc": _tc(e),
            "accuracy": round(sum(m.accuracy for m in ms) / len(ms), 1),
            "blunders": sum(m.severity == "Blunder" for m in ms), "mistakes": sum(m.severity == "Mistake" for m in ms),
            "inaccuracies": sum(m.severity == "Inaccuracy" for m in ms), "missed": sum(m.missed_opportunity for m in ms),
        })
    moves = [m for e in entries for m in e["review"].moves]
    flagged = [m for m in moves if is_flagged(m)]

    def rates(attr: str) -> list[dict]:
        out = []
        for k in ORDER[attr]:
            tot = sum(1 for m in moves if getattr(m, attr) == k)
            bad = sum(1 for m in flagged if getattr(m, attr) == k)
            out.append({"key": k, "moves": tot, "flagged": bad, "rate": round(100 * bad / tot, 1) if tot else None})
        return out

    scored = [m for m in flagged if m.maia_prob_best is not None]
    return {
        "tc": tc, "tcs": present, "by_tc": by_tc,
        "games": games,
        "n_games": len(games), "n_moves": len(moves), "n_flagged": len(flagged),
        "flag_rate": round(100 * len(flagged) / len(moves), 1) if moves else None,
        "accuracy_avg": round(sum(g["accuracy"] for g in games) / len(games), 1) if games else None,
        "by_standing": rates("standing"), "by_phase": rates("phase"), "by_type": rates("move_type"),
        "time": _time_use(entries, typical),
        "maia": {"scored": len(scored), "trainable": sum(1 for m in scored if m.maia_prob_best >= 0.25),
                 "very_human": sum(1 for m in scored if (m.maia_prob_played or 0) >= 0.40)} if scored else None,
        "enough": len(games) >= 15,
    }
