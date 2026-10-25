"""
Core analysis engine for the chess review tool.

Pipeline:
  1. Parse a PGN (pasted text, a Lichess game URL, or a chess.com game URL
     plus your chess.com username).
  2. Walk the game move by move with Stockfish, recording the evaluation
     before and after every move, the engine's best line, and the
     refutation of the move actually played. For the reviewed player's
     moves, two extra shallow "null-move" probes detect threats (is the
     opponent threatening something? does my best move create a threat?).
  3. Optionally query Maia (a human-like, rating-conditioned neural net
     running on lc0) at each of the player's positions for the *policy*
     probability of every move - i.e. how likely a human at that rating is
     to find the engine's best move, and how likely they were to play the
     move actually played.
  4. Classify every move on independent axes, from the raw data alone (no
     engine access needed, so thresholds can be re-applied instantly):

       severity   Best / Good / Inaccuracy / Mistake / Blunder, by the drop
                  in *win probability* (percentage points), not raw
                  centipawns - so losing 2 pawns of eval at +19 is nothing
                  and losing 2 pawns at 0.00 is a mistake.
       missed     a much stronger continuation existed while your move
                  still left you at least equal (or you missed a forced
                  mate). Independent of severity.
       standing   Winning / Balanced / Losing - who was better before the move.
       phase      Attack / Defense / Neutral - who had a concrete threat,
                  from the null-move probes.
       type       Opening / Tactical / Positional / Endgame. Opening and
                  Endgame are the game's phase (Lichess's divider); in the
                  middlegame, for a bad move
                  the type comes from its *refutation* (did the opponent's
                  best reply win material or mate?); for a good or
                  missed-opportunity move, from the best line.

Everything here is engine-agnostic UCI plumbing (python-chess's chess.engine
for Stockfish, a small direct UCI driver for lc0/Maia) plus pure-Python
classification, so it has no Streamlit dependency and can be run from a
script (see selftest.py).
"""

from __future__ import annotations

import dataclasses
import io
import json
import math
import os
import queue
import re
import subprocess
import threading
from datetime import date
from typing import Optional

import chess
import chess.engine
import chess.pgn
import chess.polyglot

from divider import game_phases


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class Thresholds:
    # Severity, in percentage points of win probability lost vs. the best move.
    # Defaults are chess.com's bands (Oct 2026 decision; Lichess uses 10/20/30).
    inaccuracy_pp: float = 5.0
    mistake_pp: float = 10.0
    blunder_pp: float = 20.0
    # Missed opportunity: best move was >= this many cp better than yours ...
    missed_opportunity_cp: int = 150
    # ... and your move still left you at least this good (cp, your point of
    # view; slightly negative allows for engine noise around 0.00).
    missed_still_ok_cp: int = -50
    # Opening: used as the hard cap when a book is loaded, and as the whole
    # rule when it isn't (ply = half-moves; 20 ply = 10 full moves).
    opening_ply: int = 20
    # Endgame: total non-pawn material (Q=9, R=5, B=3, N=3, both sides) at or
    # below this. Only a fallback for a move classified without its game: a
    # game's phases come from Lichess's divider (divider.py).
    endgame_material: int = 14
    # Standing: |eval| >= this (cp) is Winning / Losing rather than Balanced.
    winning_cp: int = 100
    # Threat probes: a "free move" for a side must gain at least this many cp
    # to count as a real threat.
    threat_cp: int = 150
    # Type: an eval swing of at least this many cp is treated as tactical even
    # when no material changes hands within the line's horizon (a 3-pawn
    # swing with "nothing happening" is a hidden tactic, not a positional
    # nuance).
    tactical_swing_cp: int = 300
    # Great (chess.com: "critical to the outcome"), either
    #  - the only good move: the second-best move would have cost at least
    #    great_pp points of win chance (and you weren't already won), or
    #  - it turns the game after the opponent's mistake: losing -> equal or
    #    equal -> winning, and the second-best move would have kept less than
    #    half of that swing.
    great_pp: float = 20.0
    great_max_win: float = 95.0
    # Brilliant (chess.com: "a good piece sacrifice"): the engine's move leaves
    # you at least this much material down after a short capture-only search
    # (Q=9 R=5 B=N=3 P=1), some other move would have kept that material (not
    # forced: no check escapes or pieces lost anyway), you weren't already
    # winning big, and you're not worse afterwards.
    brilliant_sac: int = 2
    brilliant_max_win: float = 90.0


MATERIAL_ENDGAME = {chess.QUEEN: 9, chess.ROOK: 5, chess.BISHOP: 3, chess.KNIGHT: 3}
MATERIAL_FULL = {chess.QUEEN: 9, chess.ROOK: 5, chess.BISHOP: 3, chess.KNIGHT: 3, chess.PAWN: 1}

MATE_VALUE = 100_000  # comparable-scale value of a mate score


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class PlyData:
    """Raw engine facts about one half-move. Everything a classifier needs,
    nothing that depends on thresholds. Evals are from the MOVER's point of
    view (positive = good for the side that made this move)."""
    ply: int
    move_number: int
    color: str                      # "White" | "Black" - who moved
    played_san: str
    played_uci: str
    best_san: str
    best_uci: str
    fen_before: str
    fen_after: str
    cp_before: Optional[int]        # eval of the position before the move (= eval of best play)
    mate_before: Optional[int]
    cp_after: Optional[int]         # eval after the played move
    mate_after: Optional[int]
    best_line_san: list[str]        # engine's PV from the position before the move
    refutation_san: list[str]       # opponent's best line after the played move
    material_before: int            # non-pawn material, both sides (endgame detection)
    in_book: bool
    delivered_mate: bool
    game_over_after: bool
    opp_threat: Optional[bool] = None   # opponent had a concrete threat against me
    my_threat: Optional[bool] = None    # my best move creates a concrete threat
    opp_threat_san: Optional[str] = None  # what the opponent was threatening (their best free move)
    clock_after: Optional[float] = None   # seconds left on the mover's clock after this move ([%clk])
    time_spent: Optional[float] = None    # seconds the mover spent on this move (needs two clocks + increment)
    maia_top_san: Optional[str] = None
    maia_prob_best: Optional[float] = None    # Maia's probability of the engine's best move
    maia_prob_played: Optional[float] = None  # Maia's probability of the move actually played
    tactical_refutation: bool = False        # opponent's best reply wins material / mates
    tactical_best_line: bool = False         # best line wins material / mates
    # added in analysis version 2 (None in older reviews)
    second_cp: Optional[int] = None          # eval of the second-best move, mover's view (MultiPV 2)
    second_mate: Optional[int] = None
    n_legal: Optional[int] = None            # legal moves in the position before the move
    book_move: Optional[bool] = None         # played move is in the Polyglot book (None: no book)
    sac_points: Optional[int] = None         # material the move gives up, still not regained 2 moves later
    recapture: bool = False                  # move takes back on the square the opponent just captured on


@dataclasses.dataclass
class MoveReview:
    """One of the reviewed player's moves, classified."""
    ply: int
    move_number: int
    color: str
    label: str                     # "15." / "15..."
    played_san: str
    best_san: str
    fen_before: str
    played_uci: str
    best_uci: str
    eval_before_cp: Optional[int]  # mover's point of view
    eval_after_cp: Optional[int]
    mate_before: Optional[int]
    mate_after: Optional[int]
    eval_before_white: str         # display strings, White's point of view (chess convention)
    eval_after_white: str
    win_before: float              # win probability (%) for the mover
    win_after: float
    pp_loss: float                 # percentage points of win probability lost
    cp_loss: int                   # raw centipawn loss (capped), kept for the missed-opp gap
    accuracy: float                # Lichess-style per-move accuracy, 0-100
    severity: str                  # Best | Good | Inaccuracy | Mistake | Blunder
    missed_opportunity: bool
    missed_reason: str
    standing: str                  # Winning | Balanced | Losing
    phase: str                     # Attack | Defense | Neutral
    move_type: str                 # Opening | Tactical | Positional | Endgame
    best_line_san: list[str]
    refutation_san: list[str]
    maia_top_san: Optional[str] = None
    maia_prob_best: Optional[float] = None
    maia_prob_played: Optional[float] = None
    phase_why: str = ""
    clock_after: Optional[float] = None
    time_spent: Optional[float] = None
    special_why: str = ""          # why a move is Brilliant / Great, in words
    game_phase: str = ""           # Opening | Middlegame | Endgame (Lichess's divider, divider.py)


@dataclasses.dataclass
class GameReview:
    headers: dict
    player_color: str
    player_rating: Optional[int]
    raw: list[PlyData]             # every ply of the game
    moves: list[MoveReview]        # the reviewed player's moves, classified
    time_control: str              # "bullet" | "blitz" | "rapid" | "classical" | "unknown"
    time_control_raw: str
    maia_used: bool
    maia_error: Optional[str]
    book_used: bool
    engine_name: str
    depth: int
    has_clocks: bool = False
    opp_moves: list = dataclasses.field(default_factory=list)  # the opponent's moves, classified the same way
    analysis_version: int = 1
    maia_band: Optional[int] = None   # V11: the Maia net's rating used (the game's own rating, nearest net)


ANALYSIS_VERSION = 2  # 2 = MultiPV 2, sacrifice/recapture data, threat probes for both sides


# ---------------------------------------------------------------------------
# PGN loading
# ---------------------------------------------------------------------------

# Lichess game ids are 8 chars; a 12-char id includes the player-side token.
LICHESS_ID_RE = re.compile(r"lichess\.org/(?:embed/)?([A-Za-z0-9]{8})(?:[A-Za-z0-9]{4})?(?=[/?#]|$)")
LICHESS_RESERVED = {"analysis", "training", "practice", "tourname", "broadcas", "streamer"}
CHESSCOM_RE = re.compile(r"chess\.com/(?:game/(?:live|daily)|live/game|daily/game|analysis/game/(?:live|daily))/(\d+)")
USER_AGENT = "chess-review-local/1.0 (personal game review tool)"


def load_pgn_text(raw_input: str, chesscom_username: str = "") -> str:
    """Accepts raw PGN text, a bare move list, a Lichess game URL, or a
    chess.com game URL (needs the chess.com username of either player, so
    the game can be found in their public monthly archive). Returns PGN text."""
    raw_input = raw_input.strip()
    m = LICHESS_ID_RE.search(raw_input)
    if m and m.group(1) not in LICHESS_RESERVED and "\n" not in raw_input:
        return _fetch_lichess_pgn(m.group(1))
    m = CHESSCOM_RE.search(raw_input)
    if m and "\n" not in raw_input:
        if not chesscom_username.strip():
            raise ValueError(
                "For a chess.com link, enter your chess.com username in the sidebar "
                "(the game is looked up in your public monthly archive), or paste the PGN "
                "(Share > Download / Copy PGN)."
            )
        return _fetch_chesscom_pgn(m.group(1), chesscom_username.strip())
    return raw_input


def _http_get(url: str, accept: str) -> bytes:
    import urllib.request
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def _fetch_lichess_pgn(game_id: str) -> str:
    url = f"https://lichess.org/game/export/{game_id}?evals=false&clocks=true&opening=true"
    return _http_get(url, "application/x-chess-pgn").decode("utf-8")


def _fetch_chesscom_pgn(game_id: str, username: str) -> str:
    """chess.com has no per-game public endpoint, but the monthly archive
    (official API) carries each game's URL and full PGN. Scan the last few
    months for a game whose URL ends in this id."""
    today = date.today()
    year, month = today.year, today.month
    for _ in range(4):
        url = f"https://api.chess.com/pub/player/{username.lower()}/games/{year}/{month:02d}"
        try:
            data = json.loads(_http_get(url, "application/json").decode("utf-8"))
        except Exception as e:  # 404 for months with no games is normal
            data = {"games": []}
            first_err = e
        for g in data.get("games", []):
            if g.get("url", "").rstrip("/").endswith(game_id) and g.get("pgn"):
                return g["pgn"]
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    raise ValueError(
        f"Game {game_id} not found in the last 4 months of chess.com archives for "
        f"'{username}'. Check the username, or paste the PGN directly."
    )


def parse_games(pgn_text: str) -> list[chess.pgn.Game]:
    """Parses every game in the text (a paste can contain several)."""
    games = []
    stream = io.StringIO(pgn_text)
    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            break
        if game.errors:
            raise ValueError(f"PGN parse problem: {game.errors[0]}")
        games.append(game)
    if not games:
        raise ValueError("Could not parse a game from that input - check the PGN/link.")
    return games


def parse_game(pgn_text: str) -> chess.pgn.Game:
    return parse_games(pgn_text)[0]


def game_label(game: chess.pgn.Game) -> str:
    h = game.headers
    return f"{h.get('White', '?')} vs {h.get('Black', '?')} ({h.get('Result', '*')}, {h.get('Date', '?')})"


def guess_player_color(game: chess.pgn.Game, usernames: list[str]) -> Optional[str]:
    names = {u.strip().lower() for u in usernames if u and u.strip()}
    if not names:
        return None
    if game.headers.get("White", "").lower() in names:
        return "White"
    if game.headers.get("Black", "").lower() in names:
        return "Black"
    return None


def time_control_parts(tc: str) -> tuple[Optional[int], int]:
    """(base seconds, increment seconds) from a PGN TimeControl like '180+2'; (None, 0) if unknown."""
    m = re.match(r"^(\d+)(?:\+(\d+))?$", (tc or "").strip())
    if not m:
        return None, 0
    return int(m.group(1)), int(m.group(2) or 0)


def _maia_band(weights_path: Optional[str]) -> Optional[int]:
    """1300 from '.../maia-1300.pb.gz'."""
    m = re.search(r"maia-(\d{4})", os.path.basename(weights_path or ""))
    return int(m.group(1)) if m else None


def time_control_category(tc: str) -> str:
    """Lichess's categorisation of a PGN TimeControl header ('180+2' etc.):
    estimated game length = base + 40 * increment seconds."""
    if not tc or tc in ("-", "?"):
        return "unknown"
    if re.match(r"^\d+/\d+$", tc.strip()):  # chess.com daily: '1/86400' = 1 move per day
        return "daily"
    m = re.match(r"^(\d+)(?:\+(\d+))?$", tc.strip())
    if not m:
        return "unknown"
    est = int(m.group(1)) + 40 * int(m.group(2) or 0)
    if est < 180:
        return "bullet"
    if est < 480:
        return "blitz"
    if est < 1500:
        return "rapid"
    return "classical"


# ---------------------------------------------------------------------------
# Score helpers
# ---------------------------------------------------------------------------

def _score_to_cp_and_mate(score: chess.engine.PovScore) -> tuple[Optional[int], Optional[int]]:
    """(cp, mate) from the point of view of the side to move when the engine
    was asked. Exactly one is not None."""
    if score.is_mate():
        return None, score.relative.mate()
    return score.relative.score(), None


def comparable(cp: Optional[int], mate: Optional[int]) -> int:
    """One number that orders mates above/below all cp scores, faster mate
    better. mate == 0 means the side to move is checkmated."""
    if mate is not None:
        if mate == 0:
            return -MATE_VALUE
        sign = 1 if mate > 0 else -1
        return sign * (MATE_VALUE - abs(mate) * 100)
    return cp if cp is not None else 0


def win_percent(cp: Optional[int], mate: Optional[int]) -> float:
    """Lichess's centipawn -> win probability mapping (for the side whose
    point of view the score is in). +100cp ~ 59%, +300 ~ 75%, +800 ~ 95%."""
    if mate is not None:
        return 100.0 if mate > 0 else 0.0
    cp = max(-1000, min(1000, cp or 0))
    return 50.0 + 50.0 * (2.0 / (1.0 + math.exp(-0.00368208 * cp)) - 1.0)


def move_accuracy(pp_loss: float) -> float:
    """Lichess's per-move accuracy from win% lost."""
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * pp_loss) - 3.1669))


def fmt_eval_white(cp: Optional[int], mate: Optional[int], mover: str) -> str:
    """Format a mover-relative score as a conventional White-relative string."""
    sign = 1 if mover == "White" else -1
    if mate is not None:
        if mate == 0:
            return "#0"
        m = mate * sign
        return f"#{m}" if m > 0 else f"#-{abs(m)}"
    if cp is None:
        return "-"
    return f"{cp * sign / 100:+.2f}"


def _material(board: chess.Board, values: dict, color: Optional[bool] = None) -> int:
    total = 0
    for pt, v in values.items():
        if color is None:
            total += v * (len(board.pieces(pt, chess.WHITE)) + len(board.pieces(pt, chess.BLACK)))
        else:
            total += v * len(board.pieces(pt, color))
    return total


def _line_is_tactical(board: chess.Board, pv: list[chess.Move], pov: bool,
                      min_material: int = 1, max_plies: int = 8) -> bool:
    """Does this line, from `board`, end in mate or change the material
    balance for `pov` by at least `min_material` points? Equal trades don't
    count: the balance is read at the last quiet moment of the line (after
    the last non-capture), so a line that stops mid-exchange isn't misread."""
    b = board.copy()
    def balance():
        return _material(b, MATERIAL_FULL, pov) - _material(b, MATERIAL_FULL, not pov)
    start = balance()
    last = None
    for mv in pv[:max_plies]:
        if mv not in b.legal_moves:
            break
        last = (mv, b.is_capture(mv))
        b.push(mv)
        if b.is_checkmate():
            return True
    end = balance()
    if last and last[1]:
        # Line stops on a capture: if the capturing piece can be taken back,
        # assume it will be (a pending recapture isn't a material gain).
        mv = last[0]
        piece = b.piece_at(mv.to_square)
        if piece and b.is_attacked_by(b.turn, mv.to_square):
            v = MATERIAL_FULL.get(piece.piece_type, 0)
            end += -v if piece.color == pov else v
    return abs(end - start) >= min_material


def _san_line(board: chess.Board, pv: list[chess.Move], max_plies: int = 8) -> list[str]:
    b = board.copy()
    out = []
    for mv in pv[:max_plies]:
        if mv not in b.legal_moves:
            break
        out.append(b.san(mv))
        b.push(mv)
    return out


# ---------------------------------------------------------------------------
# Maia (lc0) driver
#
# python-chess's engine wrapper only exposes the chosen move. Maia's real
# value is the *policy*: the probability it assigns to every legal move,
# which lc0 prints when VerboseMoveStats is on. So we drive lc0 directly.
# ---------------------------------------------------------------------------

class MaiaError(RuntimeError):
    pass


class MaiaEngine:
    _P_RE = re.compile(r"^info string\s+([a-h][1-8][a-h][1-8][qrbn]?)\b.*?\(P:\s*([\d.]+)%\)")

    def __init__(self, lc0_path: str, weights_path: str, timeout: float = 60.0):
        if not os.path.exists(weights_path):
            raise MaiaError(f"Maia weights file not found: {weights_path}")
        try:
            self.proc = subprocess.Popen(
                [lc0_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1,
            )
        except OSError as e:
            raise MaiaError(f"Could not start lc0 at '{lc0_path}': {e}") from e
        self.timeout = timeout
        self._q: queue.Queue[Optional[str]] = queue.Queue()
        self._log: list[str] = []
        threading.Thread(target=self._reader, daemon=True).start()
        self._send("uci")
        self._wait_for("uciok")
        self._send(f"setoption name WeightsFile value {weights_path}")
        self._send("setoption name VerboseMoveStats value true")
        self._send("isready")
        self._wait_for("readyok")  # network loads here; a bad file kills the process

    def _reader(self):
        try:
            for line in self.proc.stdout:
                self._q.put(line.rstrip("\n"))
        finally:
            self._q.put(None)

    def _send(self, cmd: str):
        if self.proc.poll() is not None:
            raise MaiaError("lc0 exited: " + " | ".join(self._log[-5:]))
        self.proc.stdin.write(cmd + "\n")
        self.proc.stdin.flush()

    def _wait_for(self, token: str) -> list[str]:
        lines = []
        while True:
            try:
                line = self._q.get(timeout=self.timeout)
            except queue.Empty:
                raise MaiaError(f"lc0 did not answer within {self.timeout:.0f}s (waiting for '{token}')")
            if line is None:
                raise MaiaError("lc0 exited unexpectedly: " + " | ".join(self._log[-5:]))
            self._log.append(line)
            self._log = self._log[-50:]
            lines.append(line)
            if line.startswith(token):
                return lines

    def policy(self, board: chess.Board) -> dict[str, float]:
        """{uci move: probability 0..1} for every legal move, from a single
        network evaluation (no search) - i.e. 'what would a human at this
        rating play here'."""
        self._send(f"position fen {board.fen()}")
        self._send("go nodes 1")
        lines = self._wait_for("bestmove")
        pol = {}
        for line in lines:
            m = self._P_RE.match(line)
            if m:
                pol[m.group(1)] = float(m.group(2)) / 100.0
        if not pol:
            raise MaiaError("lc0 returned no per-move policy - is VerboseMoveStats supported by this lc0 build?")
        return pol

    def quit(self):
        try:
            if self.proc.poll() is None:
                self._send("quit")
                self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Engine walk (Stockfish + optional Maia) -> raw PlyData
# ---------------------------------------------------------------------------

def _analyse(engine: chess.engine.SimpleEngine, board: chess.Board, limit: chess.engine.Limit) -> chess.engine.InfoDict:
    info = engine.analyse(board, limit)
    return info[0] if isinstance(info, list) else info


def _analyse2(engine: chess.engine.SimpleEngine, board: chess.Board, limit: chess.engine.Limit) -> tuple[dict, Optional[dict]]:
    """Best and second-best lines (MultiPV 2). Second is None with one legal move."""
    infos = engine.analyse(board, limit, multipv=2)
    if not isinstance(infos, list):
        infos = [infos]
    infos = [i for i in infos if "score" in i]
    return infos[0], (infos[1] if len(infos) > 1 else None)


def _sacrifice(board_before: chess.Board, move: chess.Move, reply_pv: list[chess.Move], horizon: int = 4) -> int:
    """Material (mover's view) the move gives up that is still missing after
    the engine's reply line has run `horizon` plies (two moves each side).
    If the line stops on a capture, one more ply is allowed for the recapture."""
    pov = board_before.turn
    def bal(b):
        return _material(b, MATERIAL_FULL, pov) - _material(b, MATERIAL_FULL, not pov)
    b = board_before.copy()
    start = bal(b)
    b.push(move)
    n = 0
    for mv in reply_pv:
        if mv not in b.legal_moves:
            break
        cap = b.is_capture(mv)
        b.push(mv)
        n += 1
        if n >= horizon and not cap:
            break
        if n >= horizon + 1:
            break
    end = bal(b)
    return max(0, start - end) if end < start else 0


def analyze_game(
    game: chess.pgn.Game,
    engine_path: str,
    player_color: str,
    player_rating: Optional[int] = None,
    thresholds: Optional[Thresholds] = None,
    depth: int = 16,
    threads: int = 2,
    hash_mb: int = 256,
    maia_engine_path: Optional[str] = None,
    maia_weights_path: Optional[str] = None,
    book_path: Optional[str] = None,
    probe_threats: bool = True,
    progress_cb=None,
) -> GameReview:
    """Runs Stockfish over every move of `game`; returns a GameReview with
    raw per-ply data and the reviewed player's moves classified with
    `thresholds`. Re-classify later with `classify_review(review, new_thresholds)`
    - no engine needed."""
    thresholds = thresholds or Thresholds()
    board = game.board()
    mainline = list(game.mainline_moves())
    clocks = [node.clock() for node in game.mainline()]  # seconds left after each move, or None
    base_secs, increment = time_control_parts(game.headers.get("TimeControl", ""))
    limit = chess.engine.Limit(depth=depth)
    probe_limit = chess.engine.Limit(depth=max(8, depth - 6))
    player_is_white = player_color == "White"

    stockfish = chess.engine.SimpleEngine.popen_uci(engine_path)
    engine_name = stockfish.id.get("name", "engine")
    try:
        stockfish.configure({"Threads": max(1, threads), "Hash": hash_mb})
    except Exception:
        pass

    maia, maia_error = None, None
    if maia_engine_path:
        try:
            maia = MaiaEngine(maia_engine_path, maia_weights_path or "")
        except MaiaError as e:
            maia_error = str(e)

    book = None
    if book_path and os.path.exists(book_path):
        try:
            book = chess.polyglot.open_reader(book_path)
        except Exception:
            book = None

    raw: list[PlyData] = []
    still_in_book = book is not None
    try:
        pre_info, pre_second = _analyse2(stockfish, board, limit)

        for i, move in enumerate(mainline):
            mover_white = board.turn == chess.WHITE
            mover_color = "White" if mover_white else "Black"
            is_player = mover_white == player_is_white
            fen_before = board.fen()
            board_before = board.copy()
            san = board.san(move)
            move_number = board.fullmove_number

            pv = pre_info.get("pv") or []
            best_move = pv[0] if pv and pv[0] in board.legal_moves else move
            cp_before, mate_before = _score_to_cp_and_mate(pre_info["score"])
            best_val = comparable(cp_before, mate_before)

            book_move = None
            if book is not None:
                try:
                    book_move = any(e.move == move for e in book.find_all(board))
                except Exception:
                    book_move = False
            in_book = False
            if still_in_book:
                try:
                    book.find(board)
                    in_book = True
                except (IndexError, KeyError):
                    still_in_book = False

            board.push(move)
            delivered_mate = board.is_checkmate()
            game_over = board.is_game_over(claim_draw=True)

            if delivered_mate:
                # No legal moves to search, and nothing to compute: this is
                # mate. Score it as "mover has mate in 0 more moves" - the
                # classifier treats it as the best possible outcome.
                cp_after, mate_after = None, 0
                post_info = {"score": chess.engine.PovScore(chess.engine.Mate(0), board.turn), "pv": []}
                post_second = None
                refutation = []
            elif game_over:
                cp_after, mate_after = 0, None
                post_info = {"score": chess.engine.PovScore(chess.engine.Cp(0), board.turn), "pv": []}
                post_second = None
                refutation = []
            else:
                post_info, post_second = _analyse2(stockfish, board, limit)
                a_cp, a_mate = _score_to_cp_and_mate(post_info["score"])
                # post_info is from the opponent's point of view - flip to the mover's.
                cp_after = -a_cp if a_cp is not None else None
                mate_after = -a_mate if a_mate is not None else None
                refutation = post_info.get("pv") or []

            ply = PlyData(
                ply=i + 1, move_number=move_number, color=mover_color,
                played_san=san, played_uci=move.uci(),
                best_san=board_before.san(best_move), best_uci=best_move.uci(),
                fen_before=fen_before, fen_after=board.fen(),
                cp_before=cp_before, mate_before=mate_before,
                cp_after=cp_after, mate_after=mate_after,
                best_line_san=_san_line(board_before, pv),
                refutation_san=_san_line(board, refutation),
                material_before=_material(board_before, MATERIAL_ENDGAME),
                in_book=in_book, delivered_mate=delivered_mate, game_over_after=game_over,
                tactical_refutation=_line_is_tactical(board, refutation, pov=mover_white) if refutation else False,
                tactical_best_line=_line_is_tactical(board_before, pv, pov=mover_white) if pv else False,
                n_legal=board_before.legal_moves.count(), book_move=book_move,
                sac_points=_sacrifice(board_before, move, refutation),
                recapture=bool(i > 0 and board_before.move_stack and board_before.is_capture(move)
                               and _was_capture_on(board_before, move.to_square)),
            )
            if pre_second is not None:
                s_cp, s_mate = _score_to_cp_and_mate(pre_second["score"])
                ply.second_cp, ply.second_mate = s_cp, s_mate

            if probe_threats and not delivered_mate:
                ply.opp_threat, ply.my_threat, ply.opp_threat_san = _threat_probes(
                    stockfish, board_before, best_move, pv, best_val, probe_limit, thresholds.threat_cp
                )

            if is_player and maia is not None:
                try:
                    pol = maia.policy(board_before)
                    top = max(pol.items(), key=lambda kv: kv[1])[0]
                    ply.maia_top_san = board_before.san(chess.Move.from_uci(top))
                    ply.maia_prob_best = pol.get(best_move.uci(), 0.0)
                    ply.maia_prob_played = pol.get(move.uci(), 0.0)
                except MaiaError as e:
                    maia_error = str(e)
                    maia.quit()
                    maia = None
                except Exception as e:  # never let the optional layer break the review
                    maia_error = f"Maia error: {e}"
                    maia.quit()
                    maia = None

            ply.clock_after = clocks[i] if i < len(clocks) else None
            if ply.clock_after is not None:
                prev = clocks[i - 2] if i >= 2 else (float(base_secs) if base_secs else None)
                if prev is not None:
                    ply.time_spent = max(0.0, prev - ply.clock_after + increment)
            raw.append(ply)
            pre_info, pre_second = post_info, post_second
            if progress_cb:
                progress_cb(i + 1, len(mainline))
    finally:
        try:
            stockfish.quit()
        except Exception:
            pass
        if maia is not None:
            maia.quit()
        if book is not None:
            book.close()

    headers = dict(game.headers)
    tc_raw = headers.get("TimeControl", "")
    review = GameReview(
        headers=headers, player_color=player_color, player_rating=player_rating,
        raw=raw, moves=[], time_control=time_control_category(tc_raw), time_control_raw=tc_raw,
        has_clocks=any(p.clock_after is not None for p in raw),
        maia_used=any(p.maia_prob_best is not None for p in raw), maia_error=maia_error,
        book_used=book_path is not None and os.path.exists(book_path),
        engine_name=engine_name, depth=depth, analysis_version=ANALYSIS_VERSION,
        maia_band=_maia_band(maia_weights_path) if any(p.maia_prob_best is not None for p in raw) else None,
    )
    classify_review(review, thresholds)
    return review


def _was_capture_on(board_before: chess.Board, square: int) -> bool:
    """Did the opponent's last move capture on `square`?"""
    last = board_before.pop()
    try:
        return last.to_square == square and board_before.is_capture(last)
    finally:
        board_before.push(last)


def _threat_probes(
    engine: chess.engine.SimpleEngine,
    board_before: chess.Board,
    best_move: chess.Move,
    best_pv: list[chess.Move],
    best_val: int,
    limit: chess.engine.Limit,
    threat_cp: int,
) -> tuple[bool, bool, Optional[str]]:
    """Null-move probes.
    opp_threat: give the opponent a free move (I pass). If their best line
                then wins material or mates, or their eval jumps by
                >= threat_cp over what they get against my best move, they
                were threatening something. Being in check counts automatically.
    my_threat:  after my best move, give the opponent a free move. If my
                best line then wins material/mates or my eval jumps by
                >= threat_cp, my best move carries a threat. A checking best
                move counts automatically.
    The material/mate test is what makes this robust when a forced mate is
    on the board (where raw eval gaps are meaningless)."""

    def free_move_gains(b: chess.Board, baseline_val: Optional[int], min_material: int) -> tuple[bool, Optional[str]]:
        # A fresh board (no null move in the stack) so python-chess sends a
        # plain FEN rather than warning about null-move history.
        b = chess.Board(b.fen())
        try:
            info = _analyse(engine, b, limit)
        except Exception:
            return False, None
        cp, mate = _score_to_cp_and_mate(info["score"])  # point of view: the side with the free move
        pv = info.get("pv") or []
        first = b.san(pv[0]) if pv and pv[0] in b.legal_moves else None
        if pv and _line_is_tactical(b, pv, pov=b.turn, min_material=min_material):
            return True, first
        if baseline_val is not None and mate is None and abs(baseline_val) < 5000:
            return comparable(cp, None) - baseline_val >= threat_cp, first
        return False, first

    # --- opponent's threat: in check, or a free move wins >= a pawn / mates /
    #     gains >= threat_cp. (A hanging pawn is a real defensive concern.)
    if board_before.is_check():
        opp_threat, opp_san = True, "check"
    else:
        b = board_before.copy()
        b.push(chess.Move.null())
        opp_threat, opp_san = free_move_gains(b, -best_val, min_material=1)
    # --- my threat: best move gives check, or the best line wins >= a piece /
    #     mates by force. Deliberately stricter than the defensive test, and
    #     not a null-move probe: a free tempo can almost always pick up a pawn
    #     somewhere, and a capture "threatens" to keep the piece, neither of
    #     which is attacking in any useful sense.
    b = board_before.copy()
    b.push(best_move)
    if b.is_check() or b.is_checkmate():
        my_threat = True
    else:
        my_threat = bool(best_pv) and _line_is_tactical(board_before, best_pv, pov=board_before.turn, min_material=2)
    return opp_threat, my_threat, (opp_san if opp_threat else None)


# ---------------------------------------------------------------------------
# Classification (pure; re-runnable with new thresholds)
# ---------------------------------------------------------------------------

def classify_ply(p: PlyData, t: Thresholds, book_used: bool, game_phase: str = "") -> MoveReview:
    best_val = comparable(p.cp_before, p.mate_before)
    played_val = comparable(p.cp_after, p.mate_after)
    win_before = win_percent(p.cp_before, p.mate_before)
    win_after = win_percent(p.cp_after, p.mate_after)
    if p.delivered_mate:
        win_after, played_val = 100.0, MATE_VALUE
    pp_loss = max(0.0, win_before - win_after)
    cp_loss = max(0, min(best_val - played_val, 2000))
    if p.played_uci == p.best_uci:
        # You played the engine's move: any eval change between the two
        # searches is depth noise, not a loss.
        pp_loss, cp_loss = 0.0, 0

    # --- severity: win-probability drop ---
    if p.delivered_mate or p.played_uci == p.best_uci or pp_loss < 1.0:
        severity = "Best"
    elif pp_loss < t.inaccuracy_pp:
        severity = "Good"
    elif pp_loss < t.mistake_pp:
        severity = "Inaccuracy"
    elif pp_loss < t.blunder_pp:
        severity = "Mistake"
    else:
        severity = "Blunder"

    special = ""
    # --- special labels for good moves: Book / Brilliant / Great ---
    if (severity in ("Best", "Good") and p.ply <= 2 * t.opening_ply and not p.delivered_mate
            and (p.book_move or _named_opening(p.fen_after))):
        severity = "Book"            # known theory (Polyglot book or a named opening position)
    elif severity == "Best" and p.played_uci == p.best_uci and not p.delivered_mate:
        # sacrifice measured on the board right after the move (exchange count),
        # not from an engine line cut after a fixed number of moves
        # (grading v4: after the forced captures, and only when another move kept the material)
        from sacrifice import sacrifice
        sac, avoidable = sacrifice(p.fen_before, p.played_uci) if not p.recapture else (0, 0)
        if (sac >= t.brilliant_sac and avoidable >= t.brilliant_sac
                and win_before < t.brilliant_max_win and win_after >= 45.0):
            severity = "Brilliant"   # a sound sacrifice the engine also plays
            special = (f"a sound sacrifice: after the captures you are {sac} point{'s' if sac != 1 else ''} "
                       "of material down, and other moves would have kept it")
        elif ((p.n_legal or 0) > 2 and (p.second_cp is not None or p.second_mate is not None)
                and "x" not in p.played_san           # taking material (back) is "only move" but obvious
                and not chess.Board(p.fen_before).is_check()  # so is getting out of check
                and win_before < t.great_max_win
                and win_before - win_percent(p.second_cp, p.second_mate) >= t.great_pp):
            severity = "Great"       # the only good move: everything else loses a lot
            special = "the only good move: the next best would have cost " \
                      f"{win_before - win_percent(p.second_cp, p.second_mate):.0f} points of win chance"

    # --- missed opportunity (independent of severity) ---
    missed, reason = False, ""
    had_mate = p.mate_before is not None and p.mate_before > 0
    kept_mate = p.delivered_mate or (p.mate_after is not None and p.mate_after > 0)
    if had_mate and not kept_mate:
        missed, reason = True, f"forced mate in {p.mate_before} was available"
    elif not had_mate and p.mate_after is None and p.cp_after is not None and p.cp_before is not None:
        # Evals are capped at +-10.00 (as in the win% mapping): beyond that
        # the game is decided and a "better" move is not an opportunity.
        clamp = lambda v: max(-1000, min(1000, v))
        gap = clamp(p.cp_before) - clamp(p.cp_after)
        if gap >= t.missed_opportunity_cp and p.cp_after >= t.missed_still_ok_cp:
            missed = True
            reason = f"{p.best_san} was {gap / 100:.1f} pawns better ({p.cp_before / 100:+.2f} vs {p.cp_after / 100:+.2f} for you)"

    # --- standing: who was better before the move ---
    if best_val >= t.winning_cp:
        standing = "Winning"
    elif best_val <= -t.winning_cp:
        standing = "Losing"
    else:
        standing = "Balanced"

    # --- phase: who had a concrete threat ---
    opp_why = ("you were in check" if p.opp_threat_san == "check" else f"opponent threatened {p.opp_threat_san}") if p.opp_threat_san else "opponent had a threat"
    my_why = f"your best move {p.best_san} carries a threat"
    if p.delivered_mate:
        phase, phase_why = "Attack", "checkmate"
    elif p.opp_threat is None and p.my_threat is None:
        phase, phase_why = "Neutral", "threat probes not run"
    elif p.opp_threat and not p.my_threat:
        phase, phase_why = "Defense", opp_why
    elif p.my_threat and not p.opp_threat:
        phase, phase_why = "Attack", my_why
    elif p.opp_threat and p.my_threat:
        phase = "Defense" if standing == "Losing" else "Attack"
        phase_why = f"both sides had threats: {opp_why}; {my_why}"
    else:
        phase, phase_why = "Neutral", "no concrete threat either way"

    # --- type ---
    if p.delivered_mate:
        move_type = "Tactical"
    elif game_phase == "Endgame" or (not game_phase and p.material_before <= t.endgame_material):
        move_type = "Endgame"
    elif game_phase == "Opening" or (not game_phase and ((book_used and p.in_book and p.ply <= 2 * t.opening_ply)
                                                         or (not book_used and p.ply <= t.opening_ply))):
        move_type = "Opening"
    elif severity in ("Inaccuracy", "Mistake", "Blunder"):
        move_type = "Tactical" if (p.tactical_refutation or cp_loss >= t.tactical_swing_cp) else "Positional"
    elif missed:
        move_type = "Tactical" if (p.tactical_best_line or cp_loss >= t.tactical_swing_cp) else "Positional"
    else:
        move_type = "Tactical" if p.tactical_best_line else "Positional"

    return MoveReview(
        ply=p.ply, move_number=p.move_number, color=p.color,
        label=f"{p.move_number}{'.' if p.color == 'White' else '...'}",
        played_san=p.played_san, best_san=p.best_san, fen_before=p.fen_before,
        played_uci=p.played_uci, best_uci=p.best_uci,
        eval_before_cp=p.cp_before, eval_after_cp=p.cp_after,
        mate_before=p.mate_before, mate_after=p.mate_after,
        eval_before_white=fmt_eval_white(p.cp_before, p.mate_before, p.color),
        eval_after_white=("1-0" if p.color == "White" else "0-1") if p.delivered_mate else fmt_eval_white(p.cp_after, p.mate_after, p.color),
        win_before=win_before, win_after=win_after, pp_loss=pp_loss, cp_loss=cp_loss,
        accuracy=move_accuracy(pp_loss),
        severity=severity, missed_opportunity=missed, missed_reason=reason,
        standing=standing, phase=phase, move_type=move_type,
        best_line_san=p.best_line_san, refutation_san=p.refutation_san,
        maia_top_san=p.maia_top_san, maia_prob_best=p.maia_prob_best, maia_prob_played=p.maia_prob_played,
        phase_why=phase_why, clock_after=p.clock_after, time_spent=p.time_spent,
        special_why=special, game_phase=game_phase,
    )


def classify_review(review: GameReview, thresholds: Thresholds) -> GameReview:
    """(Re)classifies both sides' moves in place. Pure - no engine.
    review.moves = the reviewed player's, review.opp_moves = the opponent's."""
    review.moves, review.opp_moves = [], []
    prev = None
    phases = game_phases([p.fen_before for p in review.raw])
    for p, ph in zip(review.raw, phases):
        m = classify_ply(p, thresholds, review.book_used, ph)
        if prev is not None:
            _turns_the_game(p, m, prev)
        (review.moves if p.color == review.player_color else review.opp_moves).append(m)
        prev = m
    return review


def _turns_the_game(p: PlyData, m: MoveReview, prev: MoveReview) -> None:
    """Great, second case (chess.com: "critical to the outcome"): the best
    move right after the opponent's mistake that takes the game from losing to
    equal, or from equal to winning - and the next best move would keep less
    than half of that swing, so it had to be found."""
    if m.severity != "Best" or p.played_uci != p.best_uci or p.delivered_mate:
        return
    if prev.severity not in ("Mistake", "Blunder") or (p.n_legal or 0) <= 2 or p.recapture:
        return
    if p.second_cp is None and p.second_mate is None:
        return
    before = 100.0 - prev.win_before     # our chances before their mistake
    after = m.win_after
    crosses = (before < 35 and after >= 45) or (before < 65 and after >= 80)
    if not crosses:
        return
    second = win_percent(p.second_cp, p.second_mate)
    if second - before >= 0.5 * (after - before):
        return                           # other moves cash in too: not critical
    m.severity = "Great"
    swing = "from losing to equal" if before < 35 and after < 80 else (
        "from losing to winning" if before < 35 else "from equal to winning")
    m.special_why = (f"turns the game {swing} after their {prev.severity.lower()}: "
                     f"{before:.0f}% → {after:.0f}% win chance, and the next best move "
                     f"would only reach {second:.0f}%")


_OPENINGS: Optional[dict] = None


def _openings_path() -> str:
    import sys
    for base in (getattr(sys, "_MEIPASS", ""), os.path.dirname(os.path.abspath(__file__))):
        p = os.path.join(base, "data", "openings.tsv")
        if base and os.path.exists(p):
            return p
    return ""


def openings() -> dict:
    """EPD -> (ECO, name) for every position on a named opening line (Lichess
    list, CC0); the value is None for positions on the way to a named line."""
    global _OPENINGS
    if _OPENINGS is None:
        _OPENINGS = {}
        path = _openings_path()
        if path:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("#"):
                        continue
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) == 3:
                        _OPENINGS[parts[0]] = (parts[1], parts[2]) if parts[2] else None
    return _OPENINGS


def _epd(fen: str) -> str:
    return " ".join(fen.split(" ")[:4])


def _named_opening(fen: str) -> bool:
    return _epd(fen) in openings()


def opening_name(review: GameReview) -> Optional[tuple[str, str]]:
    """Deepest named opening position reached in the game: (ECO, name)."""
    best = None
    for p in review.raw[:40]:
        hit = openings().get(_epd(p.fen_after))  # None for in-between theory positions
        if hit:
            best = hit
    return best


# ---------------------------------------------------------------------------
# Summary helpers (used by both the Streamlit UI and the LLM report layer)
# ---------------------------------------------------------------------------

def summarize(review: GameReview, opponent: bool = False) -> dict:
    from collections import Counter
    from statistics import median

    ms = review.opp_moves if opponent else review.moves
    sev = Counter(m.severity for m in ms)
    missed = [m for m in ms if m.missed_opportunity]
    maia_scored = [m for m in ms if m.maia_prob_best is not None]
    return {
        "total_moves": len(ms),
        "severity_counts": dict(sev),
        "standing_counts": dict(Counter(m.standing for m in ms)),
        "phase_counts": dict(Counter(m.phase for m in ms)),
        "type_counts": dict(Counter(m.move_type for m in ms)),
        "missed_opportunities": len(missed),
        "accuracy": (sum(m.accuracy for m in ms) / len(ms)) if ms else 0.0,
        "median_cp_loss": median(m.cp_loss for m in ms) if ms else 0,
        "avg_pp_loss": (sum(m.pp_loss for m in ms) / len(ms)) if ms else 0.0,
        "maia_top_match_rate": (
            sum(1 for m in maia_scored if m.maia_top_san == m.played_san) / len(maia_scored)
            if maia_scored else None
        ),
        "maia_avg_prob_played": (
            sum(m.maia_prob_played for m in maia_scored) / len(maia_scored) if maia_scored else None
        ),
        # cross-tabs the coaching layer cares about
        "errors_by_standing": dict(Counter(m.standing for m in ms if m.severity in ("Mistake", "Blunder"))),
        "errors_by_phase": dict(Counter(m.phase for m in ms if m.severity in ("Mistake", "Blunder"))),
        "errors_by_type": dict(Counter(m.move_type for m in ms if m.severity in ("Mistake", "Blunder"))),
        "time_control": review.time_control,
    }
