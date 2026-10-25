"""
Annotated PGN export (V10): a reviewed game as standard PGN that Lichess
studies, ChessBase, En Croissant or any PGN reader can open.

  - the game's own PGN is the base, so headers and [%clk] clocks are kept
  - every analysed move gets [%eval] (White's point of view, Lichess's format,
    so a Lichess study draws the eval graph)
  - labelled moves, both sides, get a NAG: !! Brilliant, ! Great, ?! Inaccuracy,
    ? Mistake, ?? Blunder; missed chances get none (they aren't errors)
  - flagged moves get the Review's verdict line as a comment and, when the
    engine preferred another move, its line as a variation
  - your notes (game note before the first move, move notes on their move) and
    tags (an Annotator-style "Tags" header) travel along
  - unanalysed games export as they are, plus notes and tags

Nothing here evaluates anything: it only writes out what the review stored.
"""

from __future__ import annotations

import io
from typing import Optional

import chess
import chess.engine
import chess.pgn

import store
from payload import review_payload

NAGS = {"Brilliant": chess.pgn.NAG_BRILLIANT_MOVE, "Great": chess.pgn.NAG_GOOD_MOVE,
        "Inaccuracy": chess.pgn.NAG_DUBIOUS_MOVE, "Mistake": chess.pgn.NAG_MISTAKE, "Blunder": chess.pgn.NAG_BLUNDER}
LINE_PLIES = 8   # how much of the engine's better line goes into a variation


def _white_score(cp: Optional[int], mate: Optional[int], mover: str, delivered_mate: bool) -> Optional[chess.engine.PovScore]:
    """The eval after a move (mover's view in PlyData) as a White-view score."""
    turn = chess.WHITE if mover == "White" else chess.BLACK
    if delivered_mate:
        return None                         # the game is over; no eval to show
    if mate is not None:
        sc = chess.engine.Mate(mate)
    elif cp is not None:
        sc = chess.engine.Cp(cp)
    else:
        return None
    return chess.engine.PovScore(sc, turn)


def _add_line(parent: chess.pgn.GameNode, fen: str, sans: list[str]) -> None:
    """Adds the engine's line as a variation after `parent` (stops at the first move that doesn't parse)."""
    b = chess.Board(fen)
    node = parent
    for san in sans[:LINE_PLIES]:
        try:
            mv = b.parse_san(san)
        except ValueError:
            break
        node = node.add_variation(mv) if node is parent else node.add_main_variation(mv)
        b.push(mv)


def annotate(gid: str, with_lines: bool = True, with_comments: bool = True) -> Optional[str]:
    """One game as annotated PGN, or None if the game isn't in the Library."""
    text = store.game_pgn(gid)
    if text is None:
        return None
    game = chess.pgn.read_game(io.StringIO(text))
    if game is None:
        return None
    s = store.get_settings()
    rv = store.load_review(gid, store.thresholds_from(s))
    nt = store.get_notes(gid)
    if nt["tags"]:
        game.headers["Tags"] = ", ".join(nt["tags"])
    if nt["notes"].get(0):
        game.comment = (game.comment + " " if game.comment else "") + nt["notes"][0]

    plies = {}
    raw = {}
    if rv is not None and rv.raw:
        game.headers["Annotator"] = f"Chess Review ({rv.engine_name or 'Stockfish'}, depth {rv.depth})"
        plies = {p["ply"]: p for p in review_payload(rv)["plies"]}
        raw = {p.ply: p for p in rv.raw}

    node = game
    ply = (rv.raw[0].ply - 1) if rv is not None and rv.raw else 0
    while node.variations:
        parent, node = node, node.variations[0]
        ply += 1
        p, r = plies.get(ply), raw.get(ply)
        if r is not None and r.played_uci != node.move.uci():
            plies, raw = {}, {}             # the review doesn't match this game's moves: export plain from here
            p = r = None
        if r is not None:
            sc = _white_score(r.cp_after, r.mate_after, r.color, r.delivered_mate)
            if sc is not None:
                node.set_eval(sc)
        if p is not None and p.get("severity") in NAGS:
            node.nags.add(NAGS[p["severity"]])
        bits = []
        if p is not None and p.get("flagged") and with_comments:
            ex = p.get("explain") or {}
            lead = p["severity"] if p.get("severity") in ("Inaccuracy", "Mistake", "Blunder") else ("Missed chance" if p.get("missed") else p.get("severity", ""))
            sentence = ex.get("verdict") or ""
            bits.append(f"{lead}. {sentence}".strip(". ") + ("." if sentence else ""))
        elif p is not None and p.get("severity") in ("Brilliant", "Great") and with_comments and p.get("special"):
            bits.append(f"{p['severity']}: {p['special']}.")
        if nt["notes"].get(ply):
            bits.append("Note: " + nt["notes"][ply])
        if bits:
            node.comment = (node.comment + " " if node.comment else "") + " ".join(bits)
        if p is not None and p.get("flagged") and with_lines and r is not None and r.best_uci != r.played_uci and r.best_line_san:
            _add_line(parent, r.fen_before, r.best_line_san)
    exporter = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
    return game.accept(exporter)


def export_many(ids: list[str], with_lines: bool = True, with_comments: bool = True) -> dict:
    """Several games in one PGN file (blank line between games)."""
    out, analysed = [], 0
    for gid in ids:
        pgn = annotate(gid, with_lines, with_comments)
        if pgn:
            out.append(pgn.strip())
            analysed += "[%eval" in pgn
    return {"pgn": "\n\n".join(out) + ("\n" if out else ""), "count": len(out), "analysed": analysed}
