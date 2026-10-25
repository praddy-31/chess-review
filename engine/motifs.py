"""
V3 Explain: plain-language explanations built only from engine lines.

For every flagged move (and every missed chance) two lines are read:
  - the engine's best line from the position before the move (what you could have done)
  - the refutation: the opponent's best line after the move played (what you allowed)
A small rule set names what happens in each line. Every claim is checked on
the board with python-chess; when no rule matches, the sentence falls back to
the evaluation instead of guessing ("the position just gets worse").

Rules (in priority order): mate (and back-rank mate), promotion, fork,
discovered check, winning an undefended piece, pin, and plain material won
("wins a knight", "wins the exchange").
"""

from __future__ import annotations

from collections import Counter
from typing import Optional

import chess

VAL = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
NAME = {chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop", chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king"}


def _sq(s: int) -> str:
    return chess.square_name(s)


def _parse_line(board: chess.Board, sans: list[str], limit: int = 10) -> list[chess.Move]:
    b = board.copy()
    out = []
    for san in sans[:limit]:
        try:
            mv = b.parse_san(san)
        except ValueError:
            break
        out.append(mv)
        b.push(mv)
    return out


def _material_desc(won: Counter, lost: Counter) -> Optional[str]:
    """What the beneficiary netted, in words. Names a piece only when the net
    value really is that piece (N for two pawns is 'a pawn', not 'a knight'),
    and names the trade when big pieces changed hands ('the queen for a rook')."""
    net = {pt: won.get(pt, 0) - lost.get(pt, 0) for pt in VAL if pt != chess.KING}
    value = sum(VAL[pt] * n for pt, n in net.items())
    if value < 1:
        return None
    minors = net.get(chess.KNIGHT, 0) + net.get(chess.BISHOP, 0)
    pawns = net.get(chess.PAWN, 0)
    if net.get(chess.QUEEN, 0) == 1:
        gave = []
        if net.get(chess.ROOK, 0) < 0:
            gave.append("a rook" if net[chess.ROOK] == -1 else "two rooks")
        if minors < 0:
            gave.append("a piece" if minors == -1 else "two pieces")
        if gave:
            return "the queen for " + " and ".join(gave)
        return "the queen"
    if net.get(chess.ROOK, 0) == 1 and minors == -1 and net.get(chess.QUEEN, 0) == 0:
        return "the exchange" + (" and a pawn" if pawns == 1 else f" and {pawns} pawns" if pawns > 1 else "")
    if value >= 4.5 and net.get(chess.ROOK, 0) > 0:
        return "a rook"
    if value >= 2.5:
        for pt in (chess.BISHOP, chess.KNIGHT):
            if net.get(pt, 0) > 0:
                return "a " + NAME[pt]
        return "a piece's worth of material"
    return "a pawn" if value < 1.5 else "two pawns"


def analyse_line(board: chess.Board, sans: list[str], horizon: int = 8, ben_cp: Optional[int] = None, ben_mate: Optional[int] = None,
                 just_lost: Optional[tuple[int, int]] = None) -> dict:
    """What happens in an engine line, for the side to move at its start ('us').

    Returns {motif, phrase, short, gain, mate_in, first}; motif is None when
    nothing concrete happens within the horizon."""
    us = board.turn
    moves = _parse_line(board, sans, limit=12)
    out = {"motif": None, "phrase": None, "short": None, "gain": 0, "mate_in": None, "first": None}
    if not moves:
        return out
    b = board.copy()
    first = moves[0]
    out["first"] = b.san(first)
    won, lost = Counter(), Counter()
    if just_lost:           # the move this line answers had just captured one of our pieces
        lost[just_lost[1]] += 1
    captured_from = set()   # squares of enemy pieces we take
    promoted = None
    mated = False
    n = 0
    for k, mv in enumerate(moves):
        mover = b.turn
        if b.is_capture(mv):
            victim = b.piece_at(mv.to_square) or (chess.Piece(chess.PAWN, not mover) if b.is_en_passant(mv) else None)
            if victim:
                (won if mover == us else lost)[victim.piece_type] += 1
                if mover == us:
                    captured_from.add(mv.to_square)
        if mv.promotion and mover == us and promoted is None and k < 6:
            promoted = (k, mv)
        b.push(mv)
        n = k + 1
        if b.is_checkmate():
            mated = b.turn != us
            break
        # stop at the horizon unless the line is mid-exchange (last move a capture)
        if n >= horizon and not (k + 1 < len(moves) and b.is_capture(moves[k + 1])):
            break
    gain_desc = _material_desc(won, lost)
    out["gain"] = sum(VAL[pt] * c for pt, c in won.items()) - sum(VAL[pt] * c for pt, c in lost.items())
    # A line cut off mid-sequence can show material that is won back later.
    # Only claim a gain the engine's eval for this side agrees with.
    if gain_desc and ben_mate is None and ben_cp is not None and ben_cp < 60 * min(out["gain"], 5):
        gain_desc = None

    # 1. mate
    if mated:
        mate_in = (n + 1) // 2
        out["mate_in"] = mate_in
        final = b.peek()
        king_sq = b.king(b.turn)
        mater = b.piece_at(final.to_square)
        back = chess.BB_RANK_1 if b.turn == chess.WHITE else chess.BB_RANK_8
        back_rank = (mater and mater.piece_type in (chess.ROOK, chess.QUEEN) and king_sq is not None
                     and chess.BB_SQUARES[king_sq] & back and chess.BB_SQUARES[final.to_square] & back)
        kind = "back-rank mate" if back_rank else "mate"
        out.update(motif="back-rank mate" if back_rank else "mate",
                   phrase=f"mates in {mate_in}" if mate_in > 1 else "is mate",
                   short=f"{kind} in {mate_in}" if mate_in > 1 else kind)
        return out

    before = board.copy()
    after_first = board.copy()
    after_first.push(first)
    moved = after_first.piece_at(first.to_square)

    # 2. promotion
    if promoted is not None:
        out.update(motif="promotion", phrase="pushes through to promote" + (f" and wins {gain_desc}" if gain_desc else ""),
                   short="promotes")
        return out

    # 3. fork: the moved piece attacks two valuable enemy pieces (or the king and one)
    if moved and gain_desc:
        targets = []
        for sq in after_first.attacks(first.to_square):
            p = after_first.piece_at(sq)
            if p and p.color != us and (p.piece_type == chess.KING or VAL[p.piece_type] >= 3
                                        or (VAL[p.piece_type] > VAL[moved.piece_type] and VAL[p.piece_type] > 0)):
                targets.append((sq, p))
        # a real fork: one of the forked pieces (not the king) is the one we win
        won_target = any(sq in captured_from for sq, p in targets if p.piece_type != chess.KING)
        if len(targets) >= 2 and won_target:
            targets.sort(key=lambda t: t[1].piece_type != chess.KING)
            names = [("the king" if p.piece_type == chess.KING else f"the {NAME[p.piece_type]} on {_sq(sq)}") for sq, p in targets[:2]]
            out.update(motif="fork", phrase=f"forks {names[0]} and {names[1]} and wins {gain_desc}",
                       short=f"{NAME[moved.piece_type]} fork")
            return out

    # 4. discovered check
    if before.gives_check(first):
        checkers = after_first.checkers()
        if checkers and first.to_square not in checkers:
            out.update(motif="discovered check", phrase="is a discovered check" + (f" that wins {gain_desc}" if gain_desc else ""),
                       short="discovered check")
            return out

    # 5. capturing an undefended (or under-defended) piece
    recapture = just_lost is not None and first.to_square == just_lost[0]
    if before.is_capture(first) and gain_desc and not recapture:
        victim = before.piece_at(first.to_square)
        attacker = before.piece_at(first.from_square)
        if victim and attacker:
            defended = bool(before.attackers(not us, first.to_square))
            if not defended:
                out.update(motif="hanging piece", phrase=f"takes the undefended {NAME[victim.piece_type]} on {_sq(first.to_square)}",
                           short=f"hangs a {NAME[victim.piece_type]}" if victim.piece_type != chess.QUEEN else "hangs the queen")
                return out
            if VAL[victim.piece_type] > VAL[attacker.piece_type]:
                out.update(motif="hanging piece", phrase=f"wins {gain_desc}: the {NAME[victim.piece_type]} on {_sq(first.to_square)} was only defended once",
                           short=f"loses {gain_desc}")
                return out

    # 6. pin: after the first move an enemy piece is pinned to its king by the moved piece
    if moved and gain_desc:
        for sq, p in after_first.piece_map().items():
            if p.color != us and p.piece_type not in (chess.KING, chess.PAWN) and after_first.is_pinned(not us, sq):
                if first.to_square in after_first.pin(not us, sq):
                    out.update(motif="pin", phrase=f"pins the {NAME[p.piece_type]} on {_sq(sq)} to the king and wins {gain_desc}",
                               short="pin")
                    return out

    # 7. material
    if gain_desc and out["gain"] >= 1:
        out.update(motif="material", phrase=f"wins {gain_desc}", short=f"loses {gain_desc}")
        return out
    return out


# ---------------------------------------------------------------------------
# Sentences
# ---------------------------------------------------------------------------

def _pawns(cp: Optional[int], mate: Optional[int]) -> str:
    """Eval for the side in question, as words people use."""
    if mate is not None:
        return f"mate in {abs(mate)}" if mate > 0 else f"getting mated in {abs(mate)}"
    v = (cp or 0) / 100
    return f"{v:+.1f}"


def _fmt(v: float, mate: Optional[int] = None) -> str:
    if mate is not None:
        return f"mate in {mate}" if mate > 0 else f"mated in {-mate}"
    return "0.0" if abs(v) < 0.05 else f"{v:+.1f}"


def _standing_word(win: float) -> str:
    if win >= 90:
        return "winning"
    if win >= 65:
        return "better"
    if win > 35:
        return "about equal"
    if win > 10:
        return "worse"
    return "lost"


def explain(ply: dict, prev: Optional[dict], names: dict) -> Optional[dict]:
    """ply / prev: payload ply dicts (both sides analysed). names: {'White': 'you'/'Jerry90', ...}.
    Returns {'sentence', 'better', 'allowed', 'motif_best', 'motif_ref', 'tags'} or None for unflagged moves."""
    sev = ply.get("severity")
    flagged = ply.get("flagged")
    if not flagged:
        return None
    mover = ply["color"]
    other = "Black" if mover == "White" else "White"
    you = names[mover] == "you"
    subj = "you" if you else names[mover]
    poss = "your" if you else f"{names[mover]}'s"
    board_before = chess.Board(ply["fen_before"])
    board_after = chess.Board(ply["fen_after"])
    best_sans = [s["san"] for s in ply.get("best_line") or []]
    ref_sans = [s["san"] for s in ply.get("refutation") or []]
    cpb, mtb = ply.get("cp_before_mover"), ply.get("mate_before_mover")
    cpa, mta = ply.get("cp_after_mover"), ply.get("mate_after_mover")
    best = analyse_line(board_before, best_sans, ben_cp=cpb, ben_mate=mtb if (mtb or 0) > 0 else None) if ply["played_uci"] != ply["best_uci"] else None
    played = chess.Move.from_uci(ply["played_uci"])
    taken = board_before.piece_at(played.to_square) if board_before.is_capture(played) else None
    just_lost = (played.to_square, taken.piece_type) if taken else None
    ref = analyse_line(board_after, ref_sans, ben_cp=(-cpa if cpa is not None else None), ben_mate=(-mta if mta is not None and mta < 0 else None),
                       just_lost=just_lost)
    best_label = (ply["best_line"][0]["label"] if ply.get("best_line") else ply["best_san"])
    reply = ply["refutation"][0]["label"] if ply.get("refutation") else None
    for_whom = "you" if you else names[mover]
    err = sev in ("Inaccuracy", "Mistake", "Blunder")

    # one short verdict line: what went wrong (or what was missed), then tags
    if ref["motif"] in ("mate", "back-rank mate") and reply:
        verdict = f"Walks into {ref['short']} ({reply})"
    elif ref["motif"] in ("hanging piece", "material") and reply and err:
        verdict = f"{ref['short'][0].upper()}{ref['short'][1:]} ({reply})"
    elif ref["motif"] and reply and err:
        verdict = f"Allows {reply}, {_tactic(ref)}"
    elif best is not None and best["motif"] in ("mate", "back-rank mate"):
        verdict = f"Missed {best['short']}: {best_label}"
    elif best is not None and ply.get("missed") and (mtb or 0) > 0:
        verdict = f"Missed mate in {mtb}: {best_label}"
    elif best is not None and best["motif"] in ("hanging piece", "material"):
        verdict = f"Missed {best_label}, winning {_won(best)}"
    elif best is not None and best["motif"]:
        verdict = f"Missed {best_label}, {_tactic(best)}"
    elif err:
        verdict = f"{best_label} was better ({_fmt((cpb or 0) / 100, mtb)} instead of {_fmt((cpa or 0) / 100, mta)} for {for_whom})"
    else:
        verdict = f"Still fine ({_pawns(cpa, mta)}), but {best_label} was stronger"

    tags = []
    if prev and prev.get("flagged") and prev.get("severity") in ("Mistake", "Blunder") and prev["color"] == other:
        tags.append(f"after {'your' if names[other] == 'you' else 'their'} {prev['severity'].lower()}")
    for m in (best, ref):
        if m and m["motif"] and m["motif"] != "material":
            if m["motif"] not in tags:
                tags.append(m["motif"])
    if ply.get("missed") and (mtb or 0) > 0:
        tags.append("missed mate")
    elif ply.get("missed"):
        tags.append("missed chance")
    return {"sentence": verdict, "verdict": verdict, "motif_best": best and best["motif"], "motif_ref": ref["motif"],
            "short_best": best and best["short"], "short_ref": ref["short"], "tags": tags}


def _won(m: dict) -> str:
    """The material a line wins, from its phrase ("wins the exchange", "takes the undefended rook on c5")."""
    ph = m["phrase"] or ""
    if "undefended " in ph:
        return "the " + ph.split("undefended ")[-1].split(" on ")[0]
    return ph.split("wins ")[-1].split(":")[0] if "wins " in ph else "material"


def _tactic(m: dict) -> str:
    """'a knight fork that wins the rook', 'a pin that wins a bishop', 'which promotes'."""
    ph = m["phrase"] or ""
    gain = ph.split("wins ")[-1] if "wins " in ph else ""
    if m["motif"] == "promotion":
        return "which promotes" + (f" and wins {gain}" if gain else "")
    return f"a {m['short']}" + (f" that wins {gain}" if gain else "")


def key_moments(plies: list[dict], names: dict, k: int = 3) -> list[dict]:
    """The k biggest turning points, either side, in game order."""
    cands = []
    for p in plies:
        if not p.get("flagged"):
            continue
        weight = p.get("pp", 0) + (25 if p.get("missed") and (p.get("mate_before_mover") or 0) > 0 else 0)
        cands.append((weight, p))
    top = sorted(cands, key=lambda c: -c[0])[:k]
    out = []
    for _, p in sorted(top, key=lambda c: c[1]["ply"]):
        who = names[p["color"]]
        ex = p.get("explain") or {}
        if ex.get("motif_ref") in ("mate", "back-rank mate"):
            text = f"{'You walk' if who == 'you' else 'Walks'} into {ex['short_ref']}"
        elif ex.get("short_ref") and ex.get("motif_ref") in ("hanging piece", "material", "fork", "pin", "discovered check", "promotion"):
            s = ex["short_ref"]
            if s.startswith("hangs") or s.startswith("loses"):
                text = f"{'You' if who == 'you' else who} {s.replace('hangs', 'hang' if who == 'you' else 'hangs').replace('loses', 'lose' if who == 'you' else 'loses')}"
            else:
                text = f"Allows a {s}"
        elif p.get("missed"):
            text = f"{'You miss' if who == 'you' else who + ' misses'} {p['best_line'][0]['label'] if p.get('best_line') else p['best_san']}"
        else:
            text = f"{'Your' if who == 'you' else who + chr(39) + 's'} win chance drops {p['pp']:.0f} points"
        out.append({"ply": p["ply"], "label": p["label"] + p["san"], "severity": p["severity"], "missed": p.get("missed", False),
                    "mine": p["mine"], "text": text})
    return out
