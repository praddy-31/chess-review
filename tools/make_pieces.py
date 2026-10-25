"""Writes web/pieces/cburnett/*.svg, the classic piece set python-chess ships
(Colin M.L. Burnett, GPLv2+). The other sets in web/pieces/ come from the
Lichess repository: Merida (GPLv2+), Chessnut (Apache 2.0), Fantasy (MIT)."""
import os
import chess
import chess.svg

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web", "pieces", "cburnett")
os.makedirs(out, exist_ok=True)
for sym in "PNBRQKpnbrqk":
    p = chess.Piece.from_symbol(sym)
    name = ("w" if p.color else "b") + sym.upper()
    with open(os.path.join(out, name + ".svg"), "w") as f:
        f.write(chess.svg.piece(p, size=90))
print("wrote 12 pieces to", out)
