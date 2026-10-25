"""
Finding the user-installed engines, and the analysis queue.

Nothing heavy is bundled: Stockfish and lc0 come from Homebrew, Maia weights
and the opening book are downloaded once into the app's data folder (the
Setup page shows the exact commands). Settings can point at other paths.
"""

from __future__ import annotations

import glob
import os
import queue
import re
import shutil
import threading
import time
import traceback
from typing import Optional

import chess.pgn
import io

import store
import system
from chess_analysis import analyze_game



def _runnable(p: str) -> bool:
    return os.path.isfile(p) and os.access(p, os.X_OK) and (not system.WINDOWS or p.lower().endswith(".exe"))


def _which(name: str, configured: str = "") -> Optional[str]:
    """Settings' path, then the PATH, the usual folders (system.engine_dirs) and
    the data folder's engines/ (e.g. stockfish-windows-x86-64-avx2.exe unzipped there)."""
    if configured and _runnable(configured):
        return configured
    p = shutil.which(name)
    if p:
        return p
    for d in system.engine_dirs():
        c = os.path.join(d, name + system.EXE)
        if _runnable(c):
            return c
    found = sorted(c for c in glob.glob(os.path.join(store.data_dir(), "engines", "**", name + "*"), recursive=True) if _runnable(c))
    return found[0] if found else None


def maia_dirs(settings: dict) -> list[str]:
    dirs = [settings.get("maia_dir") or "", os.path.join(store.data_dir(), "maia")]
    return [d for d in dirs if d and os.path.isdir(d)]


def maia_weights(settings: dict) -> dict[int, str]:
    """{rating band: path} for every maia-XXXX.pb.gz found."""
    out: dict[int, str] = {}
    for d in reversed(maia_dirs(settings)):  # earlier dirs win
        for f in glob.glob(os.path.join(d, "maia-*.pb.gz")):
            m = re.search(r"maia-(\d{4})\.pb\.gz$", f)
            if m:
                out[int(m.group(1))] = f
    return dict(sorted(out.items()))


def book_path(settings: dict) -> Optional[str]:
    cands = [settings.get("book_path") or ""] + sorted(glob.glob(os.path.join(store.data_dir(), "book", "*.bin")))
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def status(settings: dict) -> dict:
    weights = maia_weights(settings)
    return {
        "stockfish": _which("stockfish", settings.get("stockfish_path", "")),
        "lc0": _which("lc0", settings.get("lc0_path", "")),
        "maia_weights": {str(k): v for k, v in weights.items()},
        "book": book_path(settings),
        "data_dir": store.data_dir(),
        "maia_missing": [b for b in system.MAIA_BANDS if b not in weights],
        "setup": system.setup(store.data_dir(), [b for b in system.MAIA_BANDS if b not in weights]),
    }


def pick_maia(settings: dict, rating: Optional[int] = None) -> tuple[Optional[str], Optional[str]]:
    """(lc0 path, weights path) for the band nearest a rating (a game's own, else yours), or (None, None)."""
    if not settings.get("use_maia", True):
        return None, None
    lc0 = _which("lc0", settings.get("lc0_path", ""))
    weights = maia_weights(settings)
    if not lc0 or not weights:
        return None, None
    rating = int(rating or store.my_rating(settings=settings))
    band = min(weights, key=lambda b: abs(b - rating))
    return lc0, weights[band]


# ---------------------------------------------------------------------------
# Analysis queue: one game at a time, in a background thread
# ---------------------------------------------------------------------------

class Analyser:
    def __init__(self):
        self.q: "queue.Queue[str]" = queue.Queue()
        self.jobs: dict[str, dict] = {}     # game id -> {state, done, total, error, queued_at}
        self.lock = threading.Lock()
        self.cancelled: set[str] = set()
        threading.Thread(target=self._worker, daemon=True, name="analyser").start()

    def enqueue(self, gid: str, color: Optional[str] = None, depth: Optional[int] = None) -> dict:
        with self.lock:
            j = self.jobs.get(gid)
            if j and j["state"] in ("queued", "running"):
                return j
            self.cancelled.discard(gid)
            j = {"id": gid, "state": "queued", "done": 0, "total": 0, "error": None,
                 "color": color, "depth": depth, "queued_at": time.time()}
            self.jobs[gid] = j
        self.q.put(gid)
        return j

    def cancel(self, gid: str) -> None:
        with self.lock:
            j = self.jobs.get(gid)
            if j and j["state"] == "queued":
                j["state"] = "cancelled"
            self.cancelled.add(gid)

    def snapshot(self) -> list[dict]:
        with self.lock:
            # drop finished jobs older than 10 minutes
            now = time.time()
            for k in [k for k, j in self.jobs.items() if j["state"] in ("done", "error", "cancelled") and now - j.get("ended", now) > 600]:
                del self.jobs[k]
            return [dict(j) for j in self.jobs.values()]

    def _worker(self):
        while True:
            gid = self.q.get()
            with self.lock:
                j = self.jobs.get(gid)
                if not j or j["state"] != "queued" or gid in self.cancelled:
                    continue
                j["state"] = "running"
            try:
                self._run(gid, j)
                j["state"] = "done"
            except _Cancelled:
                j["state"] = "cancelled"
            except Exception as e:
                j["state"] = "error"
                j["error"] = str(e) or e.__class__.__name__
                if not isinstance(e, RuntimeError):  # RuntimeErrors are messages for the user
                    traceback.print_exc()
            j["ended"] = time.time()

    def _run(self, gid: str, j: dict):
        settings = store.get_settings()
        g = store.get_game(gid)
        if not g:
            raise RuntimeError("game not found")
        color = j.get("color") or g.get("player_color")
        if color not in ("White", "Black"):
            raise RuntimeError("Which side are you? Pick White or Black for this game.")
        sf = _which("stockfish", settings.get("stockfish_path", ""))
        if not sf:
            raise RuntimeError(system.install_hint("stockfish"))
        game = chess.pgn.read_game(io.StringIO(g["pgn"]))
        my_elo = (g["white_elo"] if color == "White" else g["black_elo"]) or store.my_rating(g.get("tc_category"), settings)
        lc0, weights = pick_maia(settings, my_elo)    # V11: Maia at this game's rating, not one typed number

        def progress(done, total):
            j["done"], j["total"] = done, total
            if gid in self.cancelled:
                raise _Cancelled()

        # low priority, so the Mac stays responsive while a queue runs
        engine_cmd = system.low_priority(sf)
        review = analyze_game(
            game, engine_cmd, color, my_elo, store.thresholds_from(settings),
            depth=int(j.get("depth") or settings["depth"]), threads=int(settings["threads"]), hash_mb=int(settings["hash_mb"]),
            maia_engine_path=lc0, maia_weights_path=weights, book_path=book_path(settings),
            probe_threats=bool(settings.get("probe_threats", True)), progress_cb=progress,
        )
        store.save_review(gid, review)


class _Cancelled(Exception):
    pass
