"""
Is a move a sacrifice? Decided on the board right after the move, with a
static exchange count (SEE), not by replaying an engine line for a fixed
number of moves (a line cut in the middle of an exchange looked like a
sacrifice: 9...Nc6 in the keirofearth game).

offered(board_before, move) = the most material the opponent could win by
capturing straight away, counting the full exchange on that square:
  - one of your pieces left where it can be taken at a profit, or
  - your capture itself losing material when they take back.
A move is a sacrifice when that is >= 2 points (a piece or the exchange,
not a pawn) - the engine still choosing it means taking is a mistake.

Grading v4 (Brilliant) uses `sacrifice()` instead, which fixes two kinds of
false sacrifice that `offered()` saw:
  - counter-threats and trades: the piece "hangs" but you win the material
    straight back (12.e5 dxc5 exf6). A short capture-only search (both sides
    may capture anywhere, or stop) counts what you are really down.
  - forced: escaping check, or a piece that is lost whatever you do. The loss
    only counts when some other legal move would have kept that material.
"""

from __future__ import annotations

from functools import lru_cache

import chess

VAL = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}


def _least_attacker(board: chess.Board, side: bool, sq: int):
    best = None
    for a in board.attackers(side, sq):
        p = board.piece_at(a)
        if best is None or VAL[p.piece_type] < VAL[board.piece_at(best).piece_type]:
            best = a
    return best


def _swap(board: chess.Board, sq: int, side: bool) -> int:
    """Gain for `side` from the best sequence of captures on `sq` (it may stop)."""
    a = _least_attacker(board, side, sq)
    if a is None:
        return 0
    target = board.piece_at(sq)
    attacker = board.piece_at(a)
    if attacker.piece_type == chess.KING and board.attackers(not side, sq):
        return 0  # the king can't take a defended piece
    b = board.copy(stack=False)
    b.remove_piece_at(a)
    b.set_piece_at(sq, attacker)
    return max(0, VAL[target.piece_type] - _swap(b, sq, not side))


def see_capture(board: chess.Board, move: chess.Move) -> int:
    """Net gain for the side to move from capturing with `move`, if the other
    side then recaptures as well as it can."""
    target = board.piece_at(move.to_square)
    if target is None:
        return 0
    attacker = board.piece_at(move.from_square)
    b = board.copy(stack=False)
    b.remove_piece_at(move.from_square)
    b.set_piece_at(move.to_square, attacker)
    return VAL[target.piece_type] - _swap(b, move.to_square, not board.turn)


def offered(board_before: chess.Board, move: chess.Move) -> int:
    """Points of material the move offers the opponent (0 = no sacrifice)."""
    us = board_before.turn
    captured = board_before.piece_at(move.to_square) if board_before.is_capture(move) else None
    if captured is None and board_before.is_en_passant(move):
        captured = chess.Piece(chess.PAWN, not us)
    after = board_before.copy(stack=False)
    after.push(move)
    if after.is_game_over():
        return 0
    best = 0
    for sq, piece in after.piece_map().items():
        if piece.color != us or piece.piece_type == chess.KING:
            continue
        # the opponent's best legal first capture on this square
        gains = []
        for mv in after.legal_moves:
            if mv.to_square == sq and after.is_capture(mv):
                gains.append(see_capture(after, mv))
        if not gains:
            continue
        g = max(gains)
        if sq == move.to_square and captured is not None:
            g -= VAL[captured.piece_type]   # we already took something for it
        best = max(best, g)
    return best


# --- grading v4: short capture-only search -----------------------------------
QV = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
MATED = 1000


def _material(b: chess.Board, side: bool) -> int:
    return sum(QV[p.piece_type] if p.color == side else -QV[p.piece_type] for p in b.piece_map().values())


def _qs(b: chess.Board, side: bool, alpha: int, beta: int, depth: int) -> int:
    """Material from `side`'s view after captures only (all replies when in
    check); either side may stop capturing when that suits it."""
    if b.is_checkmate():
        return -MATED if b.turn == side else MATED
    stand = _material(b, side)
    if depth == 0:
        return stand
    maxing = b.turn == side
    in_check = b.is_check()
    if not in_check:
        if maxing:
            if stand >= beta:
                return stand
            alpha = max(alpha, stand)
        else:
            if stand <= alpha:
                return stand
            beta = min(beta, stand)
    moves = [m for m in b.legal_moves if in_check or b.is_capture(m) or m.promotion]
    if not moves:
        return stand
    moves.sort(key=lambda m: -(QV[b.piece_at(m.to_square).piece_type] if b.piece_at(m.to_square) else 0))
    best = stand if not in_check else (-10 ** 6 if maxing else 10 ** 6)
    for m in moves:
        b.push(m)
        v = _qs(b, side, alpha, beta, depth - 1)
        b.pop()
        if maxing:
            best, alpha = max(best, v), max(alpha, v)
        else:
            best, beta = min(best, v), min(beta, v)
        if alpha >= beta:
            break
    return best


def material_loss(board: chess.Board, move: chess.Move, depth: int = 6) -> int:
    """Points of material you are down (relative to now) after `move` and the
    best capture sequence that follows. Negative = you come out ahead."""
    side = board.turn
    before = _material(board, side)
    b = board.copy(stack=False)
    b.push(move)
    if b.is_checkmate():
        return -MATED
    return before - _qs(b, side, -10 ** 6, 10 ** 6, depth)


@lru_cache(maxsize=4096)
def sacrifice(fen: str, uci: str) -> tuple[int, int]:
    """(loss, avoidable): material the move really gives up, and how much of
    that some other legal move would have kept. Brilliant needs both >= 2."""
    board = chess.Board(fen)
    move = chess.Move.from_uci(uci)
    loss = material_loss(board, move)
    if loss < 2:
        return loss, 0
    alts = [material_loss(board, m) for m in board.legal_moves if m != move]
    if not alts:
        return loss, 0
    return loss, max(0, loss - min(alts))
