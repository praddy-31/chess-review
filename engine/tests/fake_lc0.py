#!/usr/bin/env python3
"""Fake lc0 for tests. FAKE_LC0_MODE=die -> exits on first 'go' (bad weights); ok -> prints VerboseMoveStats-style policy."""
import os, sys, random, chess
mode = os.environ.get("FAKE_LC0_MODE", "ok")
board = chess.Board()
random.seed(1)
for line in sys.stdin:
    line = line.strip()
    if line == "uci":
        print("id name Lc0 v0.31.2"); print("option name WeightsFile type string default <autodiscover>")
        print("option name VerboseMoveStats type check default false"); print("uciok"); sys.stdout.flush()
    elif line == "isready":
        if mode == "die":
            sys.stderr.write("Cannot open weights file\n"); sys.exit(1)
        print("readyok"); sys.stdout.flush()
    elif line.startswith("position fen "):
        board = chess.Board(line[len("position fen "):])
    elif line.startswith("go"):
        moves = list(board.legal_moves)
        w = [random.random() for _ in moves]; s = sum(w)
        best = None; bp = -1
        for mv, wi in zip(moves, w):
            p = 100 * wi / s
            if p > bp: bp, best = p, mv
            print(f"info string {mv.uci()}  (405 ) N:       0 (+ 0) (P: {p:5.2f}%) (WL:  0.00000) (D:  0.000) (M:  0.0) (Q:  0.00000) (U: 0.30016) (S:  0.30016) (V:  -.----)")
        print("info string node  (405 ) N:       1 (+ 0) (P:   -.--%) (WL:  0.00000)")
        print(f"info depth 1 seldepth 1 time 5 nodes 1 score cp 0 nps 200 pv {best.uci()}")
        print(f"bestmove {best.uci()}"); sys.stdout.flush()
    elif line == "quit":
        sys.exit(0)
