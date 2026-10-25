"""
Markdown export of a review, for pasting into an Obsidian note.

The moves go in a fenced ```chess block in the format the Chess Tree plugin
renders (optional `r:true` to show the board from Black's side, optional
[FEN "..."] header, then PGN movetext). Engine lines can be included as PGN
variations in parentheses and short {comments} - Chess Tree is a variation
tree viewer, so the best line and the refutation become clickable branches
at each flagged move. Switch them off if your plugin version does not show
them.

No tags, no links: you manage those in Obsidian.
"""

from __future__ import annotations

import chess

from chess_analysis import GameReview, summarize

NOTABLE = {"Inaccuracy", "Mistake", "Blunder"}
# a move's initiative (stored as phase: Attack / Defense / Neutral, from the threat probes)
INITIATIVE = {"Attack": "attacking", "Defense": "defending", "Neutral": "no threats either way"}


def _movetext(review: GameReview, with_lines: bool, with_comments: bool) -> str:
    by_ply = {m.ply: m for m in review.moves}
    out = []
    for p in review.raw:
        m = by_ply.get(p.ply)
        flagged = m is not None and (m.severity in NOTABLE or m.missed_opportunity)
        # move number: always for White; for Black only after a comment/variation broke the pair
        needs_num = p.color == "White" or (out and out[-1].endswith((")", "}")))
        tok = f"{p.move_number}." + ("" if p.color == "White" else "..") + " " + p.played_san if needs_num else p.played_san
        if m is not None:  # PGN annotation glyphs: ?! ? ?? for errors, ! great, !! brilliant
            tok += {"Inaccuracy": "?!", "Mistake": "?", "Blunder": "??", "Great": "!", "Brilliant": "!!"}.get(m.severity, "")
        out.append(tok)
        if flagged and with_comments:
            bits = [m.severity if m.severity in NOTABLE else "", f"{m.eval_before_white} → {m.eval_after_white}"]
            if m.missed_opportunity:
                bits.append("missed: " + m.missed_reason)
            out.append("{" + "; ".join(b for b in bits if b) + "}")
        if flagged and with_lines and m.best_line_san and m.played_uci != m.best_uci:
            out.append("(" + _line_text(m.fen_before, m.best_line_san[:6]) + ")")
    return " ".join(out)


def _line_text(fen: str, sans: list[str]) -> str:
    b = chess.Board(fen)
    toks = []
    for i, san in enumerate(sans):
        if b.turn == chess.WHITE:
            toks.append(f"{b.fullmove_number}. {san}")
        elif i == 0:
            toks.append(f"{b.fullmove_number}... {san}")
        else:
            toks.append(san)
        try:
            b.push_san(san)
        except ValueError:
            break
    return " ".join(toks)


def game_markdown(review: GameReview, with_lines: bool = True, with_comments: bool = True,
                  writeup: str | None = None) -> str:
    h = review.headers
    s = summarize(review)
    you = review.player_color
    opp = h.get("Black" if you == "White" else "White", "?")
    my_elo = h.get("WhiteElo" if you == "White" else "BlackElo", "")
    opp_elo = h.get("BlackElo" if you == "White" else "WhiteElo", "")
    result = h.get("Result", "*")
    won = (result == "1-0" and you == "White") or (result == "0-1" and you == "Black")
    outcome = "won" if won else ("lost" if result in ("1-0", "0-1") else "drew")
    lines = [
        f"## {h.get('White', '?')} vs {h.get('Black', '?')} — {result}",
        f"{(h.get('Date', '') + ' · ') if h.get('Date') and '?' not in h.get('Date', '') else ''}{you} · {outcome} vs {opp}{f' ({opp_elo})' if opp_elo else ''}"
        + (f" · rated {my_elo}" if my_elo else "")
        + (f" · {review.time_control} {review.time_control_raw}" if review.time_control != "unknown" else ""),
        "",
        f"Accuracy {s['accuracy']:.0f}% · "
        + ", ".join(f"{s['severity_counts'].get(k, 0)} " + (k.lower() if s['severity_counts'].get(k, 0) == 1 else ("inaccuracies" if k == "Inaccuracy" else k.lower() + "s"))
                    for k in ("Blunder", "Mistake", "Inaccuracy"))
        + f" · {s['missed_opportunities']} missed opportunit{'y' if s['missed_opportunities'] == 1 else 'ies'}",
        "",
    ]
    flagged = [m for m in review.moves if m.severity in NOTABLE or m.missed_opportunity]
    if flagged:
        lines.append("**Flagged moves**")
        for m in flagged:
            tag = m.severity if m.severity in NOTABLE else ""
            if m.missed_opportunity:
                tag = (tag + ", " if tag else "") + "missed opportunity"
            line = f"- {m.label}{m.played_san} ({tag}) — {m.eval_before_white} → {m.eval_after_white}, −{m.pp_loss:.0f} pp. Engine: {m.best_san}"
            if m.missed_opportunity:
                line += f" — {m.missed_reason}"
            line += f". {m.standing}, {INITIATIVE.get(m.phase, m.phase.lower())}, {m.move_type.lower()}."
            if m.maia_prob_best is not None:
                line += f" Maia: {m.maia_prob_best*100:.0f}% find it."
            lines.append(line)
        lines.append("")
    lines.append("```chess")
    if you == "Black":
        lines.append("r:true")
    start = review.raw[0].fen_before if review.raw else chess.STARTING_FEN
    if start != chess.STARTING_FEN:
        lines.append(f'[FEN "{start}"]')
    lines.append(_movetext(review, with_lines, with_comments) + (f" {result}" if result != "*" else ""))
    lines.append("```")
    if writeup:
        lines += ["", "**Coach's write-up**", "", writeup.strip()]
    return "\n".join(lines) + "\n"
