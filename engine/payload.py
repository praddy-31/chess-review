"""
Turns a classified GameReview into the JSON the UI renders.

Everything the board needs (every position as a FEN, every engine line
pre-expanded to FENs, labels, arrows) is computed here, so the JavaScript
never generates moves - it only draws positions. Ported from the v2
board_component.py; the HTML half of that file now lives in web/board.js.
"""

from __future__ import annotations

from collections import Counter

import motifs
from typing import Optional

import chess

from chess_analysis import (ANALYSIS_VERSION, GameReview, MoveReview, opening_name, summarize, time_control_parts,
                            win_percent)

NOTABLE = ("Inaccuracy", "Mistake", "Blunder")


def maia_tags(m: MoveReview) -> list[str]:
    """'Trainable' = a player at this level finds the right move often enough
    that drilling it is realistic; 'Very human' = the move played is what most
    players at this level play."""
    tags = []
    if m.maia_prob_best is not None and m.maia_prob_best >= 0.25:
        tags.append("Trainable")
    if m.maia_prob_played is not None and m.maia_prob_played >= 0.40:
        tags.append("Very human")
    return tags


def is_flagged(m: MoveReview) -> bool:
    return m.severity in NOTABLE or m.missed_opportunity


def _line_fens(fen: str, sans: list[str], max_plies: int = 10) -> list[dict]:
    b = chess.Board(fen)
    out = []
    for san in sans[:max_plies]:
        try:
            mv = b.parse_san(san)
        except ValueError:
            break
        label = f"{b.fullmove_number}.{san}" if b.turn == chess.WHITE else (f"{b.fullmove_number}...{san}" if not out else san)
        uci = mv.uci()
        b.push(mv)
        out.append({"san": san, "label": label, "fen": b.fen(), "uci": uci})
    return out


def _eval_num_white(p) -> float:
    """Eval after the move, White's point of view, in pawns, clamped to +-10."""
    sign = 1 if p.color == "White" else -1
    if p.delivered_mate:
        return 10.0 * sign
    if p.mate_after is not None:
        return 10.0 * sign * (1 if p.mate_after > 0 else -1)
    return max(-10.0, min(10.0, (p.cp_after or 0) * sign / 100))


def _phase_of(m: MoveReview) -> str:
    """The move's phase by Lichess's divider (set by classify_review)."""
    return m.game_phase or ("Opening" if m.move_type == "Opening" else "Endgame" if m.move_type == "Endgame" else "Middlegame")


SEVERITIES = ("Brilliant", "Great", "Best", "Book", "Good", "Inaccuracy", "Mistake", "Blunder")


def _side_summary(review: GameReview, opponent: bool) -> dict:
    s = summarize(review, opponent=opponent)
    ms = review.opp_moves if opponent else review.moves
    by_phase = {}
    for ph in ("Opening", "Middlegame", "Endgame"):
        xs = [m.accuracy for m in ms if _phase_of(m) == ph]
        by_phase[ph] = {"moves": len(xs), "accuracy": round(sum(xs) / len(xs), 1) if xs else None}
    flagged = [m for m in ms if is_flagged(m)]
    out = {
        "accuracy": round(s["accuracy"], 1),
        "median_cp_loss": s["median_cp_loss"],
        "severity": {k: s["severity_counts"].get(k, 0) for k in SEVERITIES},
        "missed": s["missed_opportunities"],
        "by_phase": by_phase,
        "flagged": len(flagged),
        "where": {
            "standing": dict(Counter(m.standing for m in flagged)),
            "phase": dict(Counter(m.phase for m in flagged)),
            "type": dict(Counter(m.move_type for m in flagged)),
        },
    }
    if not opponent:
        timed = [m for m in flagged if m.time_spent is not None]
        out["time_note"] = {"flagged": len(timed), "fast": sum(1 for m in timed if m.time_spent < 4),
                            "trouble": sum(1 for m in timed if (m.clock_after or 0) < 20)} if timed else None
        out["maia_match"] = None if s["maia_top_match_rate"] is None else round(s["maia_top_match_rate"] * 100)
    return out


# ---------------------------------------------------------------------------
# Clock analysis, scaled to the time control
# ---------------------------------------------------------------------------

TYPICAL_MOVES = 40  # moves per player in a typical online game (global figure; your own median replaces it once you have enough games)


def clock_limits(base: float, inc: float = 0, moves: float = TYPICAL_MOVES) -> dict:
    """Thresholds from a per-move budget: the starting clock spread over a
    typical game, plus the increment.
      snap move   under 1/3 of the budget     (10+0: 5 s, 3+0: 1.5 s, 3+2: 2.2 s)
      long think  over 3x the budget          (10+0: 45 s, 3+0: 13.5 s)
      low clock   under 4x the budget left    (10+0: 60 s, 3+0: 18 s; at least 10 s)"""
    budget = base / max(1.0, moves) + inc
    return {"budget": budget, "quick": max(0.5, budget / 3), "long": budget * 3, "low": max(10.0, budget * 4)}


def fmt_secs(s: float) -> str:
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}" if s >= 60 else f"{s} s"


def _clock_side(ms: list[MoveReview], base: int, inc: int, lim: dict) -> Optional[dict]:
    timed = [m for m in ms if m.time_spent is not None]
    if not timed:
        return None
    quick, low, long_ = lim["quick"], lim["low"], lim["long"]
    used = sum(m.time_spent for m in timed)
    by_phase = {}
    for ph in ("Opening", "Middlegame", "Endgame"):
        xs = [m.time_spent for m in timed if _phase_of(m) == ph]
        if xs:
            by_phase[ph] = {"moves": len(xs), "secs": round(sum(xs)), "avg": round(sum(xs) / len(xs), 1)}
    flagged = [m for m in timed if is_flagged(m)]
    fast = [m for m in timed if m.time_spent < quick]
    normal = [m for m in timed if quick <= m.time_spent <= long_]
    longs = [m for m in timed if m.time_spent > long_]
    in_low = [m for m in timed if (m.clock_after or 0) + (m.time_spent or 0) < low]  # clock was already low before the move
    longest = max(timed, key=lambda m: m.time_spent)

    def rate(xs):
        return round(100 * sum(1 for m in xs if is_flagged(m)) / len(xs)) if xs else None
    return {
        "used": round(used), "used_pct": round(100 * used / (base + inc * len(timed))) if base else None,
        "end_clock": timed[-1].clock_after, "min_clock": min(m.clock_after for m in timed if m.clock_after is not None),
        "avg": round(used / len(timed), 1), "moves": len(timed), "by_phase": by_phase,
        "fast": len(fast), "fast_flagged": sum(1 for m in fast if is_flagged(m)), "fast_rate": rate(fast),
        "normal_rate": rate(normal), "long": len(longs), "long_flagged": sum(1 for m in longs if is_flagged(m)), "long_rate": rate(longs),
        "low_moves": len(in_low), "low_flagged": sum(1 for m in in_low if is_flagged(m)),
        "flagged": len(flagged),
        "longest": {"ply": longest.ply, "label": longest.label + longest.played_san, "secs": round(longest.time_spent),
                    "severity": longest.severity, "clock": longest.clock_after},
        "per_move": [{"ply": m.ply, "label": m.label + m.played_san, "spent": round(m.time_spent, 1), "clock": m.clock_after,
                      "severity": m.severity, "flagged": is_flagged(m)} for m in timed],
    }


def tc_label(base: int, inc: int) -> str:
    if base < 60:
        b = f"{base} seconds"
    else:
        mins = base / 60
        b = f"{mins:g} minute{'s' if mins != 1 else ''}"
    return f"{b} each" + (f", +{inc} s a move" if inc else ", no increment")


def clock_report(review: GameReview, expected_moves: Optional[float] = None, moves_source: str = "") -> Optional[dict]:
    """Time use for both sides, judged against this game's time control."""
    base, inc = time_control_parts(review.time_control_raw)
    if not review.has_clocks or not base or review.time_control == "daily":
        return None
    n = expected_moves or TYPICAL_MOVES
    lim = clock_limits(base, inc, n)
    me, opp = _clock_side(review.moves, base, inc, lim), _clock_side(review.opp_moves, base, inc, lim)
    if not me:
        return None
    quick, low, long_ = lim["quick"], lim["low"], lim["long"]
    q = f"{quick:.1f}".rstrip("0").rstrip(".")
    notes = []
    if me["flagged"]:
        if me["fast_flagged"] * 2 >= me["flagged"]:
            notes.append(f"Most of your errors were snap moves: {me['fast_flagged']} of {me['flagged']} came in under {q} s. Slowing down on those would have paid.")
        else:
            slow = sorted([m for m in me["per_move"] if m["flagged"] and m["spent"] >= quick], key=lambda m: -m["spent"])[:2]
            ex = " and ".join(f"{m['label']} ({m['spent']:.0f} s)" for m in slow)
            k, n_f = me["fast_flagged"], me["flagged"]
            lead = (f"None of your {n_f} flagged moves were snap moves." if k == 0 and n_f > 1 else
                    "Your flagged move was not a snap move." if k == 0 else
                    f"Your errors were mostly not rushed: {k} of your {n_f} flagged moves were snap moves.")
            went = "went" if len(slow) > 1 or n_f > 1 else "went"
            notes.append(lead + (f" {ex} {went} wrong after real thought, so {'those positions were' if len(slow) > 1 else 'that position was'} hard, not careless." if ex else ""))
    if me["low_flagged"]:
        notes.append(f"{me['low_flagged']} of your errors came with under {fmt_secs(low)} on the clock.")
    elif me["min_clock"] is not None:
        notes.append(f"You never got near time trouble: your clock never went below {fmt_secs(me['min_clock'])}.")
    if opp and opp["longest"]["secs"] >= long_:
        lg = opp["longest"]
        notes.append(f"Your opponent's longest think: {fmt_secs(lg['secs'])} on {lg['label']}.")
    if me["by_phase"]:
        ph, v = max(me["by_phase"].items(), key=lambda kv: kv[1]["secs"])
        notes.append(f"Most of your time went into the {ph.lower()}: {fmt_secs(v['secs'])} over {v['moves']} moves.")
    return {"base": base, "inc": inc, "tc": tc_label(base, inc), "budget": lim["budget"], "quick": quick, "long": long_, "low": low,
            "expected_moves": n, "moves_source": moves_source or "a typical game", "me": me, "opp": opp, "notes": notes,
            "my_color": review.player_color}


def review_payload(review: GameReview, expected_moves: Optional[float] = None, moves_source: str = "") -> dict:
    mine = {m.ply for m in review.moves}
    by_ply = {m.ply: m for m in review.moves + review.opp_moves}
    start_fen = review.raw[0].fen_before if review.raw else chess.STARTING_FEN
    plies = []
    for p in review.raw:
        m = by_ply.get(p.ply)
        d = {
            "ply": p.ply, "label": f"{p.move_number}{'.' if p.color == 'White' else '...'}", "san": p.played_san,
            "color": p.color, "fen_before": p.fen_before, "fen_after": p.fen_after, "played_uci": p.played_uci,
            "mine": p.ply in mine, "eval_num": _eval_num_white(p),
            "clock": p.clock_after, "spent": p.time_spent,
        }
        if m is not None:
            d.update({
                "severity": m.severity, "missed": m.missed_opportunity, "missed_reason": m.missed_reason,
                "flagged": is_flagged(m),
                "pp": round(m.pp_loss, 1), "eval_before": m.eval_before_white, "eval_after": m.eval_after_white,
                "win_before": round(m.win_before), "win_after": round(m.win_after), "accuracy": round(m.accuracy),
                "standing": m.standing, "phase": m.phase, "phase_why": m.phase_why, "type": m.move_type,
                "game_phase": _phase_of(m),
                "best_san": m.best_san, "best_uci": m.best_uci,
                "best_line": _line_fens(m.fen_before, m.best_line_san),
                "refutation": _line_fens(p.fen_after, m.refutation_san),
                "sac": p.sac_points or 0, "special": m.special_why,
                "eval_before_mover": _mover_eval(p.cp_before, p.mate_before),
                "cp_before_mover": p.cp_before, "cp_after_mover": p.cp_after, "mate_after_mover": p.mate_after, "mate_before_mover": p.mate_before,
                "maia": None if m.maia_prob_best is None else {
                    "top": m.maia_top_san, "p_best": round(m.maia_prob_best * 100), "p_played": round((m.maia_prob_played or 0) * 100),
                    "tags": maia_tags(m) if is_flagged(m) else []},
            })
        plies.append(d)
    me = review.player_color
    names = {me: "you", ("Black" if me == "White" else "White"): review.headers.get("Black" if me == "White" else "White", "your opponent")}
    for k, d in enumerate(plies):
        if d.get("flagged"):
            d["explain"] = motifs.explain(d, plies[k - 1] if k else None, names)
    op = opening_name(review)
    summary, opp_summary = _side_summary(review, False), (_side_summary(review, True) if review.opp_moves else None)
    return {
        "key_moments": motifs.key_moments(plies, names),
        "story": game_story(review, summary, opp_summary, names),
        "orientation": "white" if review.player_color == "White" else "black",
        "player": review.player_color,
        "start_fen": start_fen,
        "start_win": win_percent(review.raw[0].cp_before, review.raw[0].mate_before) if review.raw else 50,
        "plies": plies,
        "white": review.headers.get("White", "White"), "black": review.headers.get("Black", "Black"),
        "summary": summary,
        "opp_summary": opp_summary,
        "clock": clock_report(review, expected_moves, moves_source),
        "opening": {"eco": op[0], "name": op[1]} if op else None,
        "engine": review.engine_name, "depth": review.depth,
        "maia_used": review.maia_used, "maia_band": review.maia_band, "player_rating": review.player_rating, "maia_error": review.maia_error,
        "has_clocks": review.has_clocks, "book_used": review.book_used,
        "analysis_version": review.analysis_version, "current_version": ANALYSIS_VERSION,
    }


def _mover_eval(cp, mate) -> str:
    if mate is not None:
        return f"mate in {mate}" if mate > 0 else f"mated in {-mate}"
    v = (cp or 0) / 100
    return "0.0" if abs(v) < 0.05 else f"{v:+.1f}"


def game_story(review: GameReview, a: dict, b: Optional[dict], names: dict) -> str:
    """One sentence on how the game went, from the result and the two summaries."""
    me = review.player_color
    opp = names["Black" if me == "White" else "White"]
    res = review.headers.get("Result", "*")
    term = (review.headers.get("Termination") or "").lower()
    how = ""
    for word, phrase in (("checkmate", "by checkmate"), ("resign", "on resignation"), ("time", "on time"), ("abandon", "by abandonment"),
                         ("stalemate", "by stalemate"), ("repetition", "by repetition"), ("insufficient", "by insufficient material"), ("agree", "by agreement")):
        if word in term:
            how = " " + phrase
            break
    last = review.raw[-1] if review.raw else None
    if not how and last is not None and last.delivered_mate:
        how = " by checkmate"
    n = review.raw[-1].move_number if review.raw else 0
    if res in ("1-0", "0-1"):
        won = (res == "1-0") == (me == "White")
        first = f"You {'won' if won else 'lost'}{how} on move {n}."
    elif res == "1/2-1/2":
        first = f"Drawn{how} on move {n}."
    else:
        first = f"Unfinished after {n} moves."
    if not b:
        return first
    diff = a["accuracy"] - b["accuracy"]
    acc = (f" You were the more accurate side ({a['accuracy']:.0f} to {b['accuracy']:.0f})" if diff >= 3 else
           f" {opp} was the more accurate side ({b['accuracy']:.0f} to {a['accuracy']:.0f})" if diff <= -3 else
           f" Both sides were about as accurate ({a['accuracy']:.0f} and {b['accuracy']:.0f})")
    errs = lambda s: s["severity"].get("Mistake", 0) + s["severity"].get("Blunder", 0)
    ea, eb = errs(a), errs(b)
    if ea or eb:
        acc += f"; {opp} made {eb} mistake{'s' if eb != 1 else ''} or blunder{'s' if eb != 1 else ''} to your {ea}."
    else:
        acc += "; neither side made a mistake."
    return first + acc


def summary_columns(review: GameReview) -> dict:
    """The few numbers the Library list shows, cached next to the review."""
    s = summarize(review)
    o = summarize(review, opponent=True)
    sev = s["severity_counts"]
    return {"accuracy": round(s["accuracy"], 1), "blunders": sev.get("Blunder", 0), "mistakes": sev.get("Mistake", 0),
            "inaccuracies": sev.get("Inaccuracy", 0), "missed": s["missed_opportunities"],
            "opp_accuracy": round(o["accuracy"], 1) if review.opp_moves else None,
            "brilliant": sev.get("Brilliant", 0), "great": sev.get("Great", 0)}
