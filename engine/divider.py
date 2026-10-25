"""
Lichess's game divider (ported from scalachess `Divider.scala`, MIT): where a
game's middlegame and endgame start. Used for every "phase" in the app: the
Review's bands, phase accuracy and clock split, move types, the Endgame skill
and Insights by phase.

  - the middlegame starts at the first position with 10 or fewer queens, rooks,
    bishops and knights on the board, or a thinned back rank (fewer than 4 of a
    side's pieces on its home rank), or pieces of both sides mixed together
    ("mixedness" over 2x2 squares above 150)
  - the endgame starts at the first position with 6 or fewer of those pieces
  - a middlegame that would start at or after the endgame is dropped

Pure: python-chess only, no store, so chess_analysis can import it.
"""

from __future__ import annotations

from typing import Optional

import chess

PHASES = ("Opening", "Middlegame", "Endgame")

_REGIONS = [0x0303 << (x + 8 * y) for y in range(7) for x in range(7)]


def _score(y: int, white: int, black: int) -> int:
    if white == 0:
        return {1: 1 + y, 2: 2 + (6 - y) if y < 6 else 0, 3: 3 + (7 - y) if y < 7 else 0,
                4: 3 + (7 - y) if y < 7 else 0}.get(black, 0)
    if white == 1:
        return {0: 1 + (8 - y), 1: 5 + abs(4 - y), 2: 4 + (7 - y), 3: 5 + (7 - y)}.get(black, 0)
    if white == 2:
        return {0: 2 + (y - 2) if y > 2 else 0, 1: 4 + (y - 1), 2: 7}.get(black, 0)
    if white == 3:
        return {0: 3 + (y - 1) if y > 1 else 0, 1: 5 + (y - 1)}.get(black, 0)
    if white == 4:
        return 3 + (y - 1) if black == 0 and y > 1 else 0
    return 0


def _mixedness(b: chess.Board) -> int:
    w, k = b.occupied_co[chess.WHITE], b.occupied_co[chess.BLACK]
    return sum(_score(i // 7 + 1, chess.popcount(w & r), chess.popcount(k & r)) for i, r in enumerate(_REGIONS))


def _majors_minors(b: chess.Board) -> int:
    return chess.popcount(b.occupied & ~(b.kings | b.pawns))


def _backrank_sparse(b: chess.Board) -> bool:
    return (chess.popcount(chess.BB_RANK_1 & b.occupied_co[chess.WHITE]) < 4
            or chess.popcount(chess.BB_RANK_8 & b.occupied_co[chess.BLACK]) < 4)


def divide(fens: list[str]) -> tuple[Optional[int], Optional[int]]:
    """(index where the middlegame starts, index where the endgame starts) in a list of positions; None = never."""
    boards = [chess.Board(f) for f in fens]
    mid = next((i for i, b in enumerate(boards)
                if _majors_minors(b) <= 10 or _backrank_sparse(b) or _mixedness(b) > 150), None)
    end = next((i for i, b in enumerate(boards) if _majors_minors(b) <= 6), None) if mid is not None else None
    if mid is not None and end is not None and mid >= end:
        mid = None
    return mid, end


def phase_at(i: int, mid: Optional[int], end: Optional[int]) -> str:
    if end is not None and i >= end:
        return "Endgame"
    if mid is not None and i >= mid:
        return "Middlegame"
    return "Opening"


def game_phases(fens: list[str]) -> list[str]:
    """The phase of each position in a game, in order."""
    mid, end = divide(fens)
    return [phase_at(i, mid, end) for i in range(len(fens))]
