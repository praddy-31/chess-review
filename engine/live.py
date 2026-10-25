"""
Live engine lines for the analysis board (V4).

One Stockfish, separate from the review queue and from the grader, thinks
about one position at a time with MultiPV 3. The UI starts it for a FEN and
polls; a new FEN replaces the old one. It stops by itself when nobody has
polled for IDLE_STOP seconds, or after MAX_SECONDS on one position, so a
forgotten window doesn't keep a core busy.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

import chess
import chess.engine

import system

IDLE_STOP = 12.0
MAX_SECONDS = 90.0
MAX_DEPTH = 32


def _label(board: chess.Board, i: int) -> str:
    n = board.fullmove_number + (i + (0 if board.turn else 1)) // 2
    white = (i % 2 == 0) == board.turn
    if i == 0:
        return f"{n}." if white else f"{n}..."
    return f"{n}." if white else ""


class Live:
    def __init__(self, engine_path_fn, options_fn):
        self._path_fn = engine_path_fn
        self._opts_fn = options_fn
        self.lock = threading.Lock()
        self.engine: Optional[chess.engine.SimpleEngine] = None
        self.analysis = None
        self.gen = 0
        self.fen = None
        self.state: dict = {"running": False}
        self.last_poll = 0.0

    # -- engine ---------------------------------------------------------------
    def _engine(self) -> chess.engine.SimpleEngine:
        if self.engine is None:
            path = self._path_fn()
            if not path:
                raise RuntimeError(system.install_hint("stockfish"))
            self.engine = chess.engine.SimpleEngine.popen_uci(path)
            try:
                self.engine.configure(self._opts_fn())
            except Exception:
                pass
        return self.engine

    def close(self) -> None:
        self.stop()
        with self.lock:
            if self.engine is not None:
                try:
                    self.engine.quit()
                except Exception:
                    pass
                self.engine = None

    # -- control --------------------------------------------------------------
    def start(self, fen: str, multipv: int = 3, depth: int = MAX_DEPTH, threads: Optional[int] = None,
              seconds: float = MAX_SECONDS) -> dict:
        board = chess.Board(fen)      # ValueError on a bad FEN
        self.stop()
        with self.lock:
            self.gen += 1
            gen = self.gen
            self.fen = board.fen()
            self.last_poll = time.time()
            if board.is_game_over():
                res = board.result(claim_draw=False)
                self.state = {"running": False, "fen": self.fen, "depth": 0, "lines": [], "game_over": res,
                              "reason": "checkmate" if board.is_checkmate() else "draw"}
                return self.state
            self.state = {"running": True, "fen": self.fen, "depth": 0, "lines": [], "gen": gen, "target_depth": depth}
            try:
                eng = self._engine()
                if threads and threads != getattr(self, "_threads", None):
                    try:
                        eng.configure({"Threads": int(threads)})
                        self._threads = threads
                    except Exception:
                        pass
                self.analysis = eng.analysis(board, chess.engine.Limit(depth=depth, time=seconds),
                                             multipv=min(5, max(1, multipv)))
            except (chess.engine.EngineError, chess.engine.EngineTerminatedError, OSError):
                self.engine = None
                raise
        threading.Thread(target=self._run, args=(gen, board, self.analysis), daemon=True).start()
        return self.state

    def stop(self) -> None:
        with self.lock:
            a, self.analysis = self.analysis, None
            if self.state.get("running"):
                self.state = dict(self.state, running=False)
        if a is not None:
            try:
                a.stop()
            except Exception:
                pass

    def poll(self, fen: Optional[str] = None) -> dict:
        self.last_poll = time.time()
        with self.lock:
            st = dict(self.state)
        if fen and st.get("fen") and chess.Board(fen).fen() != st["fen"]:
            return {"running": False, "fen": st.get("fen"), "stale": True, "lines": [], "depth": 0}
        st.pop("gen", None)
        return st

    # -- worker ---------------------------------------------------------------
    def _run(self, gen: int, board: chess.Board, analysis) -> None:
        lines: dict[int, dict] = {}
        try:
            for info in analysis:
                if gen != self.gen:
                    break
                if time.time() - self.last_poll > IDLE_STOP:
                    analysis.stop()
                    break
                if "pv" not in info or "score" not in info:
                    continue
                k = info.get("multipv", 1)
                pv = info["pv"]
                score = info["score"].white()
                cp = None if score.is_mate() else score.score()
                mate = score.mate() if score.is_mate() else None
                b = board.copy()
                sans, ucis = [], []
                for i, mv in enumerate(pv[:12]):
                    if mv not in b.legal_moves:
                        break
                    sans.append(_label(board, i) + b.san(mv))
                    ucis.append(mv.uci())
                    b.push(mv)
                if not ucis:
                    continue
                lines[k] = {"rank": k, "cp": cp, "mate": mate, "san": sans, "uci": ucis, "depth": info.get("depth", 0)}
                with self.lock:
                    if gen != self.gen:
                        break
                    self.state = {"running": True, "fen": board.fen(), "gen": gen, "target_depth": self.state.get("target_depth"),
                                  "depth": min(l["depth"] for l in lines.values()) if lines else 0,
                                  "nodes": info.get("nodes"), "nps": info.get("nps"),
                                  "lines": [lines[i] for i in sorted(lines)]}
        except Exception as e:  # engine died: report it and drop the process
            with self.lock:
                if gen == self.gen:
                    self.state = dict(self.state, running=False, error=str(e) or e.__class__.__name__)
                self.engine = None
            return
        with self.lock:
            if gen == self.gen:
                self.state = dict(self.state, running=False)
