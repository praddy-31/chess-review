"""
Getting games into the Library from a paste: PGN text (one or many games),
a bare move list, or one or more chess.com / Lichess game links (one per line).
Network is used only to fetch linked games.
"""

from __future__ import annotations

import chess.pgn

import store
from chess_analysis import CHESSCOM_RE, LICHESS_ID_RE, LICHESS_RESERVED, load_pgn_text, parse_games


def _is_link(line: str) -> bool:
    if CHESSCOM_RE.search(line):
        return True
    m = LICHESS_ID_RE.search(line)
    return bool(m and m.group(1) not in LICHESS_RESERVED)


def import_text(text: str) -> dict:
    """Returns {added: [ids], existing: [ids], errors: [str]}."""
    settings = store.get_settings()
    text = (text or "").strip()
    if not text:
        raise ValueError("Paste a PGN, a move list or a game link first.")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    added, existing, errors = [], [], []
    chunks: list[str] = []
    if lines and all(_is_link(l) and " " not in l for l in lines):
        for l in lines:
            try:
                chunks.append(load_pgn_text(l, chesscom_username=settings.get("chesscom_user", "")))
            except Exception as e:
                errors.append(f"{l}: {_clean(e)}")
    else:
        chunks.append(text)
    for chunk in chunks:
        try:
            games = parse_games(chunk)
        except Exception as e:
            errors.append(_clean(e))
            continue
        for g in games:
            if not list(g.mainline_moves()):
                errors.append("A game with no moves was skipped.")
                continue
            gid, new = store.add_game(g, settings)
            (added if new else existing).append(gid)
    return {"added": added, "existing": existing, "errors": errors}


def _clean(e: Exception) -> str:
    s = str(e)
    if "HTTP Error 404" in s:
        return "not found (check the link)"
    if "HTTP Error 429" in s:
        return "the site is rate-limiting requests; try again in a minute"
    if "urlopen error" in s or "timed out" in s:
        return "could not reach the site (are you online?)"
    return s.replace("in the sidebar", "in Settings")
