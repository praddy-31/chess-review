"""
Position features for the coach (V7 polish): what a position is like, in
chess terms, not just the engine's number.

features(board, side) describes the position from `side`'s point of view:
material and imbalances, king safety, pawn structure, loose pieces,
development, open files, mobility and centre. compare(a, b, side) lists what
differs between two positions (after your move vs after the best move), most
important first. plan(board, pv, side) turns an engine line into a plan:
which pieces go where, pawn breaks, trades, checks.

All of it is rule-based (python-chess); nothing is guessed.
"""

from __future__ import annotations

from typing import Optional

import chess

VAL = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
NAME = {chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop", chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king"}
CENTRE = [chess.D4, chess.E4, chess.D5, chess.E5]


def _sq(s: int) -> str:
    return chess.square_name(s)


def _material(board: chess.Board, side: bool) -> int:
    return sum(VAL[p.piece_type] for p in board.piece_map().values() if p.color == side)


def _phase(board: chess.Board) -> str:
    non_pawn = sum(VAL[p.piece_type] for p in board.piece_map().values() if p.piece_type not in (chess.PAWN, chess.KING))
    if non_pawn <= 14:
        return "endgame"
    if board.fullmove_number <= 12:
        return "opening"
    return "middlegame"


def _king_zone(board: chess.Board, side: bool) -> list[int]:
    k = board.king(side)
    if k is None:
        return []
    return [s for s in chess.SQUARES if chess.square_distance(s, k) <= 1]


def _king_safety(board: chess.Board, side: bool) -> dict:
    k = board.king(side)
    if k is None:
        return {}
    file, rank = chess.square_file(k), chess.square_rank(k)
    forward = 1 if side == chess.WHITE else -1
    shield = 0
    for df in (-1, 0, 1):
        f = file + df
        if not 0 <= f <= 7:
            continue
        for dr in (1, 2):
            r = rank + forward * dr
            if 0 <= r <= 7:
                p = board.piece_at(chess.square(f, r))
                if p and p.piece_type == chess.PAWN and p.color == side:
                    shield += 1
                    break
    open_files = []
    for df in (-1, 0, 1):
        f = file + df
        if not 0 <= f <= 7:
            continue
        own = any((p := board.piece_at(chess.square(f, r))) and p.piece_type == chess.PAWN and p.color == side for r in range(8))
        if not own:
            open_files.append(chess.FILE_NAMES[f])
    attackers = 0
    for s in _king_zone(board, side):
        attackers += len(board.attackers(not side, s))
    home_rank = 0 if side == chess.WHITE else 7
    castled = rank == home_rank and file in (0, 1, 2, 6, 7)
    in_centre = file in (3, 4, 5) and _phase(board) != "endgame"
    escapes = 0                      # squares off the back rank the king could step to (luft)
    for s in chess.SQUARES:
        if chess.square_distance(s, k) == 1 and chess.square_rank(s) != rank:
            q = board.piece_at(s)
            if (q is None or q.color != side) and not board.attackers(not side, s):
                escapes += 1
    back = rank == home_rank
    return {"square": _sq(k), "shield": shield, "open_files": open_files, "attackers": attackers, "escapes": escapes,
            "back_rank": bool(back and escapes == 0 and shield >= 2
                              and (board.pieces(chess.ROOK, not side) or board.pieces(chess.QUEEN, not side))),
            "castled": bool(castled), "centre": in_centre, "can_castle": bool(board.has_castling_rights(side))}


def _pawns(board: chess.Board, side: bool) -> dict:
    mine = [s for s, p in board.piece_map().items() if p.piece_type == chess.PAWN and p.color == side]
    theirs = [s for s, p in board.piece_map().items() if p.piece_type == chess.PAWN and p.color != side]
    files = [chess.square_file(s) for s in mine]
    isolated = sorted({chess.FILE_NAMES[f] for f in files if (f - 1 not in files and f + 1 not in files)})
    doubled = sorted({chess.FILE_NAMES[f] for f in files if files.count(f) > 1})
    passed = []
    for s in mine:
        f, r = chess.square_file(s), chess.square_rank(s)
        ahead = range(r + 1, 8) if side == chess.WHITE else range(0, r)
        if not any(chess.square_file(t) in (f - 1, f, f + 1) and chess.square_rank(t) in ahead for t in theirs):
            passed.append(_sq(s))
    islands, prev = 0, -2
    for f in sorted(set(files)):
        if f != prev + 1:
            islands += 1
        prev = f
    return {"count": len(mine), "isolated": isolated, "doubled": doubled, "passed": sorted(passed), "islands": islands}


def _loose(board: chess.Board, side: bool) -> list[dict]:
    """Your pieces (not pawns or king) that are attacked and not defended, or attacked by something cheaper."""
    out = []
    for s, p in board.piece_map().items():
        if p.color != side or p.piece_type in (chess.KING, chess.PAWN):
            continue
        att = board.attackers(not side, s)
        if not att:
            continue
        defended = bool(board.attackers(side, s))
        cheapest = min(VAL[board.piece_at(a).piece_type] or 100 for a in att)
        if not defended or cheapest < VAL[p.piece_type]:
            out.append({"piece": NAME[p.piece_type], "square": _sq(s), "defended": defended})
    return out


def _undeveloped(board: chess.Board, side: bool) -> list[str]:
    home = {chess.WHITE: {chess.B1: chess.KNIGHT, chess.G1: chess.KNIGHT, chess.C1: chess.BISHOP, chess.F1: chess.BISHOP},
            chess.BLACK: {chess.B8: chess.KNIGHT, chess.G8: chess.KNIGHT, chess.C8: chess.BISHOP, chess.F8: chess.BISHOP}}[side]
    return [f"{NAME[t]} on {_sq(s)}" for s, t in home.items() if (p := board.piece_at(s)) and p.piece_type == t and p.color == side]


def _rooks_on_open(board: chess.Board, side: bool) -> list[str]:
    out = []
    for s, p in board.piece_map().items():
        if p.color == side and p.piece_type == chess.ROOK:
            f = chess.square_file(s)
            pawns = [board.piece_at(chess.square(f, r)) for r in range(8)]
            own = any(q and q.piece_type == chess.PAWN and q.color == side for q in pawns)
            opp = any(q and q.piece_type == chess.PAWN and q.color != side for q in pawns)
            if not own:
                out.append(f"{chess.FILE_NAMES[f]}-file ({'open' if not opp else 'half-open'})")
    return out


def _mobility(board: chess.Board, side: bool) -> int:
    b = board.copy(stack=False)
    b.turn = side
    if b.is_check() and b.turn != board.turn:
        return 0
    return sum(1 for m in b.legal_moves if b.piece_at(m.from_square).piece_type != chess.PAWN)


def features(board: chess.Board, side: bool) -> dict:
    other = not side
    mine, theirs = _material(board, side), _material(board, other)
    bishops = lambda c: len(board.pieces(chess.BISHOP, c))
    return {
        "phase": _phase(board),
        "material": {"you": mine, "them": theirs, "diff": mine - theirs,
                     "bishop_pair": bishops(side) >= 2 and bishops(other) < 2, "their_bishop_pair": bishops(other) >= 2 and bishops(side) < 2},
        "king": _king_safety(board, side), "their_king": _king_safety(board, other),
        "pawns": _pawns(board, side), "their_pawns": _pawns(board, other),
        "loose": _loose(board, side), "their_loose": _loose(board, other),
        "undeveloped": _undeveloped(board, side) if _phase(board) == "opening" else [],
        "their_undeveloped": _undeveloped(board, other) if _phase(board) == "opening" else [],
        "rooks_open": _rooks_on_open(board, side), "their_rooks_open": _rooks_on_open(board, other),
        "mobility": _mobility(board, side), "their_mobility": _mobility(board, other),
        "centre": sum(len(board.attackers(side, s)) for s in CENTRE) - sum(len(board.attackers(other, s)) for s in CENTRE),
        "in_check": board.is_check(),
    }


def describe(f: dict) -> list[str]:
    """A few sentences on what stands out in a position (from your side)."""
    out = []
    m = f["material"]
    if m["diff"]:
        out.append(f"Material: you are {abs(m['diff'])} point{'s' if abs(m['diff']) != 1 else ''} {'up' if m['diff'] > 0 else 'down'} ({m['you']} vs {m['them']}).")
    else:
        out.append("Material is level.")
    if m["bishop_pair"]:
        out.append("You have the bishop pair.")
    if m["their_bishop_pair"]:
        out.append("They have the bishop pair.")
    for who, k in (("Your", f["king"]), ("Their", f["their_king"])):
        if not k:
            continue
        bits = []
        if k["centre"] and not k["castled"] and (f["phase"] != "opening" or k["open_files"]):
            bits.append("still in the centre" + (" (castling is still possible)" if k["can_castle"] else ", no castling left"))
        if k["shield"] <= 1 and f["phase"] != "endgame":
            bits.append(f"only {k['shield']} pawn{'s' if k['shield'] != 1 else ''} in front of it")
        if k["open_files"] and f["phase"] != "endgame":
            bits.append(f"open file{'s' if len(k['open_files']) > 1 else ''} next to it ({', '.join(k['open_files'])})")
        if k["attackers"] >= 4:
            bits.append(f"{k['attackers']} attacks on the squares around it")
        if k.get("back_rank") and f["phase"] != "opening":
            bits.append("no escape square: a check on the back rank could be mate")
        if bits:
            out.append(f"{who} king on {k['square']}: " + "; ".join(bits) + ".")
    for who, p in (("You", f["pawns"]), ("They", f["their_pawns"])):
        bits = []
        if p["passed"]:
            bits.append(f"a passed pawn on {', '.join(p['passed'])}" if len(p["passed"]) == 1 else f"passed pawns on {', '.join(p['passed'])}")
        if p["isolated"]:
            bits.append(f"isolated pawn{'s' if len(p['isolated']) > 1 else ''} on the {', '.join(p['isolated'])}-file{'s' if len(p['isolated']) > 1 else ''}")
        if p["doubled"]:
            bits.append(f"doubled pawns on the {', '.join(p['doubled'])}-file")
        if bits:
            out.append(f"{who} have " + ", ".join(bits) + ".")
    if f["loose"]:
        out.append("Loose: your " + ", ".join(f"{x['piece']} on {x['square']}" + ("" if x["defended"] else " (undefended)") for x in f["loose"]) + ".")
    if f["their_loose"]:
        out.append("Loose for them: their " + ", ".join(f"{x['piece']} on {x['square']}" + ("" if x["defended"] else " (undefended)") for x in f["their_loose"]) + ".")
    if f["undeveloped"]:
        out.append("Still at home: your " + ", ".join(f["undeveloped"]) + ".")
    if f["their_undeveloped"] and len(f["their_undeveloped"]) >= 2:
        out.append(f"They still have {len(f['their_undeveloped'])} minor pieces at home.")
    if f["rooks_open"]:
        out.append("Your rooks on " + ", ".join(f["rooks_open"]) + ".")
    if f["mobility"] and f["their_mobility"] and (f["mobility"] >= 1.4 * f["their_mobility"] or f["their_mobility"] >= 1.4 * f["mobility"]):
        out.append(f"Piece activity: {f['mobility']} piece moves for you, {f['their_mobility']} for them.")
    if abs(f["centre"]) >= 3:
        out.append(f"{'You' if f['centre'] > 0 else 'They'} control more of the centre.")
    return out


def compare(after_cand: dict, after_best: dict, cand: str, best: str) -> list[str]:
    """What your move changes compared with the best move, most important first."""
    a, b = after_cand, after_best
    out = []
    d = a["material"]["diff"] - b["material"]["diff"]
    if d:
        out.append(f"Right after the moves, {cand} leaves you {abs(d)} point{'s' if abs(d) != 1 else ''} of material {'better' if d > 0 else 'worse'} off than {best}.")
    la = {(x["piece"], x["square"]) for x in a["loose"]}
    lb = {(x["piece"], x["square"]) for x in b["loose"]}
    new_loose = la - lb
    if new_loose:
        out.append(f"After {cand} your " + ", ".join(f"{p} on {s}" for p, s in sorted(new_loose)) + f" {'is' if len(new_loose) == 1 else 'are'} loose; after {best} {'it is' if len(new_loose) == 1 else 'they are'} not.")
    ta = {(x["piece"], x["square"]) for x in a["their_loose"]}
    tb = {(x["piece"], x["square"]) for x in b["their_loose"]}
    if tb - ta:
        out.append(f"{best} leaves their " + ", ".join(f"{p} on {s}" for p, s in sorted(tb - ta)) + " loose; " + cand + " doesn't.")
    ka, kb = a["king"], b["king"]
    if ka and kb:
        if kb["castled"] and not ka["castled"]:
            out.append(f"{best} gets your king to safety; after {cand} it is still on {ka['square']}.")
        if ka["shield"] < kb["shield"] and a["phase"] != "endgame":
            out.append(f"{cand} leaves fewer pawns in front of your king ({ka['shield']} vs {kb['shield']}).")
        if ka["attackers"] >= kb["attackers"] + 2:
            out.append(f"After {cand} their pieces hit the squares around your king more ({ka['attackers']} vs {kb['attackers']} attacks).")
    qa, qb = a["their_king"], b["their_king"]
    if qa and qb and qb["attackers"] >= qa["attackers"] + 2:
        out.append(f"{best} puts more pressure on their king ({qb['attackers']} vs {qa['attackers']} attacks around it).")
    pa, pb = a["pawns"], b["pawns"]
    for key, word in (("isolated", "isolated"), ("doubled", "doubled")):
        if len(pa[key]) > len(pb[key]):
            out.append(f"{cand} gives you {word} pawns ({', '.join(pa[key])}-file); {best} doesn't.")
    if len(pb["passed"]) > len(pa["passed"]):
        out.append(f"{best} creates a passed pawn ({', '.join(sorted(set(pb['passed']) - set(pa['passed'])))}).")
    if len(a["their_pawns"]["passed"]) > len(b["their_pawns"]["passed"]):
        out.append(f"{cand} lets them get a passed pawn ({', '.join(sorted(set(a['their_pawns']['passed']) - set(b['their_pawns']['passed'])))}).")
    if len(a["undeveloped"]) > len(b["undeveloped"]):
        out.append(f"{best} develops a piece; {cand} leaves more of them at home.")
    if b["mobility"] >= a["mobility"] + 6:
        out.append(f"Your pieces have more moves after {best} ({b['mobility']} vs {a['mobility']}).")
    if b["centre"] >= a["centre"] + 3:
        out.append(f"{best} gives you more control of the centre.")
    return out


def plan(board: chess.Board, pv: list, side: bool, plies: int = 10) -> list[str]:
    """An engine line as a plan for `side`: piece routes, pawn breaks, trades, checks."""
    b = board.copy()
    routes: dict = {}        # square a piece started on -> [squares]
    order = []
    trades, checks, breaks, castles = [], 0, [], None
    for k, mv in enumerate(pv[:plies]):
        if mv not in b.legal_moves:
            break
        p = b.piece_at(mv.from_square)
        mover = b.turn
        cap = b.piece_at(mv.to_square)
        if b.is_castling(mv) and mover == side:
            castles = "castles " + ("kingside" if chess.square_file(mv.to_square) == 6 else "queenside")
        elif p and mover == side:
            start = next((s for s, r in routes.items() if r[-1] == mv.from_square), mv.from_square)
            if start not in routes:
                routes[start] = [mv.from_square]
                order.append(start)
            routes[start].append(mv.to_square)
            if p.piece_type == chess.PAWN:
                to = mv.to_square
                nb = b.copy(stack=False); nb.push(mv)
                if any((q := nb.piece_at(t)) and q.piece_type == chess.PAWN and q.color != side for t in nb.attacks(to)) or cap:
                    breaks.append(b.san(mv))
        if cap and mover == side:
            trades.append(f"takes the {NAME[cap.piece_type]} on {_sq(mv.to_square)}")
        if b.gives_check(mv) and mover == side:
            checks += 1
        b.push(mv)
    out = []
    pieces = []
    for start in order:
        r = routes[start]
        p = b.piece_at(r[-1])
        if not p or p.color != side:
            continue
        if p.piece_type == chess.PAWN:
            continue
        if len(r) >= 3:
            pieces.append(f"the {NAME[p.piece_type]} goes {' → '.join(_sq(s) for s in r)}")
        elif len(r) == 2:
            pieces.append(f"the {NAME[p.piece_type]} to {_sq(r[-1])}")
    if castles:
        out.append(f"You {castles.replace('castles', 'castle')}.")
    if pieces:
        out.append("Piece moves: " + "; ".join(pieces[:4]) + ".")
    if breaks:
        out.append("Pawn breaks: " + ", ".join(breaks[:3]) + ".")
    if trades:
        out.append("On the way you " + ", ".join(trades[:3]) + ".")
    if checks >= 2:
        out.append(f"It's forcing: {checks} checks.")
    return out
