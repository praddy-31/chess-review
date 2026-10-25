"""
The app's one SQLite file: ~/Library/Application Support/Chess Review/chess.sqlite
(CHESS_REVIEW_DATA overrides the folder, for tests).

  games     every game in the Library, analysed or not, with its PGN
  reviews   the engine data for analysed games (all PlyData as JSON, so labels
            can be recomputed with new thresholds without the engine), plus
            a few cached numbers for the Library list
  settings  key -> JSON value
  meta      schema version, migration markers

Game ids are stable across imports: 'chesscom:<id>' / 'lichess:<id>' when the
PGN says where it came from, otherwise 'pgn:<hash of players, date, moves>'.
Importing the same game twice is a no-op.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import zlib
import os
import re
import sqlite3
import threading
import time
from typing import Optional

import chess
import chess.pgn

import system

from chess_analysis import (
    CHESSCOM_RE, LICHESS_ID_RE, LICHESS_RESERVED, GameReview, PlyData, Thresholds,
    classify_review, openings, time_control_category,
)
from payload import summary_columns

SCHEMA_VERSION = 1


def data_dir() -> str:
    d = os.environ.get("CHESS_REVIEW_DATA") or system.data_dir()
    os.makedirs(d, exist_ok=True)
    return d


def db_path() -> str:
    return os.path.join(data_dir(), "chess.sqlite")


SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id           TEXT PRIMARY KEY,
    source       TEXT NOT NULL,          -- chesscom | lichess | pgn | maia (V10: played in the app against Maia)
    url          TEXT,
    imported_at  REAL NOT NULL,
    played_at    TEXT,                   -- 'YYYY-MM-DD HH:MM' (UTC when known) for sorting
    white        TEXT, black TEXT,
    white_elo    INTEGER, black_elo INTEGER,
    result       TEXT,
    time_control TEXT, tc_category TEXT,
    eco          TEXT, opening TEXT,
    player_color TEXT,                   -- White | Black | NULL (not known yet)
    n_plies      INTEGER,
    pgn          TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    game_id      TEXT PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
    analysed_at  REAL NOT NULL,
    player_color TEXT NOT NULL,
    depth        INTEGER, engine TEXT, maia_used INTEGER,
    review_json  TEXT NOT NULL,
    accuracy REAL, blunders INTEGER, mistakes INTEGER, inaccuracies INTEGER, missed INTEGER
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS retries (       -- "retry this move" attempts; V4 turns failed ones into puzzles
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT, ply INTEGER, fen TEXT NOT NULL, uci TEXT NOT NULL, label TEXT, pp REAL,
    solved INTEGER NOT NULL, gave_up INTEGER NOT NULL DEFAULT 0, at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS games_played ON games(played_at);
CREATE TABLE IF NOT EXISTS puzzles (       -- V4: positions from your analysed games
    id TEXT PRIMARY KEY,                    -- '<game id>:<ply>'
    game_id TEXT NOT NULL, ply INTEGER NOT NULL,
    fen TEXT NOT NULL, color TEXT NOT NULL,   -- the side you play in the puzzle
    prev_fen TEXT, last_uci TEXT,           -- the move before, played in when the puzzle opens
    source TEXT NOT NULL,                   -- mine (your error) | opp (punish their error)
    kind TEXT NOT NULL DEFAULT 'tactic',    -- tactic (one clear answer) | better (any move near the best)
    solution TEXT NOT NULL,                 -- JSON list of UCI moves: yours, reply, yours, ...
    solution_san TEXT NOT NULL,
    motif TEXT, severity TEXT, played_san TEXT, label TEXT, win_gap REAL,
    from_retry INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL,
    due TEXT,                               -- 'YYYY-MM-DD' (local); NULL = new
    interval REAL NOT NULL DEFAULT 0, ease REAL NOT NULL DEFAULT 2.5,
    reps INTEGER NOT NULL DEFAULT 0, lapses INTEGER NOT NULL DEFAULT 0,
    last_result TEXT, last_at REAL,
    why TEXT                                -- JSON: the full line, what it does, your game move and what it allowed
);
CREATE TABLE IF NOT EXISTS puzzle_log (puzzle_id TEXT NOT NULL, day TEXT NOT NULL, result TEXT NOT NULL, hints INTEGER, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS puzzle_scan (game_id TEXT PRIMARY KEY, version TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS game_notes (     -- V7: your notes; ply 0 = the whole game
    game_id TEXT NOT NULL, ply INTEGER NOT NULL, text TEXT NOT NULL, updated REAL NOT NULL,
    PRIMARY KEY (game_id, ply)
);
CREATE TABLE IF NOT EXISTS game_tags (game_id TEXT NOT NULL, tag TEXT NOT NULL, PRIMARY KEY (game_id, tag));
CREATE TABLE IF NOT EXISTS deleted_games (   -- deleted on purpose: Sync skips these unless asked to restore
    id TEXT PRIMARY KEY, at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS variations (    -- lines saved from the analysis board
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, fen TEXT NOT NULL, moves TEXT NOT NULL,
    game_id TEXT, ply INTEGER, created REAL NOT NULL
);
"""

_lock = threading.RLock()


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(db_path(), timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(reviews)")}
    for col, typ in (("opp_accuracy", "REAL"), ("brilliant", "INTEGER"), ("great", "INTEGER"), ("version", "INTEGER")):
        if col not in cols:  # added in v3 V2; older files get the column, filled on the next recompute
            con.execute(f"ALTER TABLE reviews ADD COLUMN {col} {typ}")
    pcols = {r[1] for r in con.execute("PRAGMA table_info(puzzles)")}
    if "why" not in pcols:   # added after V4 shipped
        con.execute("ALTER TABLE puzzles ADD COLUMN why TEXT")
    con.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
    return con


@contextlib.contextmanager
def db():
    """One short-lived connection: commit on success, always close."""
    with _lock:
        con = connect()
        try:
            yield con
            con.commit()
        finally:
            con.close()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS = {
    "chesscom_user": "", "lichess_user": "",
    "rating": 1200,              # your rating typed by hand: used when rating_auto is off, or before any game shows one
    "rating_auto": True,         # V11: take your rating from your latest game of each time control (my_rating)
    "rating_tc": "",             # V11: the time control whose rating counts where none is given ("" = the one you analyse most)
    "theme": "mocha", "board": "green", "pieces": "cburnett", "sidebar_collapsed": False,
    "depth": 16, "threads": 2, "hash_mb": 256,
    "use_maia": True, "probe_threats": True,
    "stockfish_path": "", "lc0_path": "", "maia_dir": "", "book_path": "",
    "thresholds": dataclasses.asdict(Thresholds()),
    "export_lines": True, "export_comments": True,
    # used from the Puzzles milestone on; stored now so the choice is kept
    "puzzles_per_day": 10, "puzzles_include_opponent": True,
    # both sides are analysed, so both can be puzzles
    "live_strength": "medium",   # analysis board engine: low | medium | high (depth, threads, time)
    "drills_per_day": 10,        # (before Oct 4) per-move drills; replaced by new_lines_per_day
    "new_lines_per_day": 3,      # opening study: new lines to learn a day; every due review comes on top
    "learn_depth": 3,            # line length when you learn an opening: 1-5, 3 = recommended for your rating
    "explorer_lookup": False,    # opening study: ask the Lichess explorer what's played at your level (network)
    "explorer_token": "",        # a Lichess personal token; the explorer needs one since 2025
    "coach_ollama": False,       # V7: let a local Ollama model put the coach's engine facts into words
    "coach_model": "",           # which Ollama model (Settings lists the ones installed)
    "puzzle_clock": False,       # V7 polish: a clock per puzzle, your per-move time for the game's time control
    "puzzle_judgement": True,    # V7 polish: "one move or several?" before each puzzle
    "convert_per_day": 3,        # V8: convert-the-win drills a day
    "plan_minutes": None,        # V8: weekly study plan in minutes; None = not asked yet, 0 = off
    "insights_include_maia": False,   # V10: count games played against Maia in Insights, opponents and the weekly note
    "play_maia_band": None,      # V10: last Maia rating picked on Play (None = nearest your rating)
    "play_clock": "none",        # V10: Play's clock: none | "base+inc" in minutes and seconds, e.g. "10+0"
    "follow_palette": False,     # V11: take the app's colours from the Palette theme switcher (engine/palette.py)
    "tips_seen": [],             # V11: screens whose first-visit note you dismissed (Settings > Appearance brings them back)
    "restore_deleted": False,    # next Sync brings back games you deleted (then switches itself off)
    # selective sync: games outside these are never downloaded
    "sync_window": "all",        # all | 3m | 6m | 12m | 24m | since
    "sync_since": "",            # YYYY-MM-DD, used when sync_window == "since"
    "sync_tcs": [],              # [] = every time control; else any of bullet blitz rapid classical daily
    "sync_opp_min": None, "sync_opp_max": None,   # opponent rating range (None = no limit)
}


def get_settings() -> dict:
    with db() as con:
        rows = con.execute("SELECT key, value FROM settings").fetchall()
    s = json.loads(json.dumps(DEFAULT_SETTINGS))
    for r in rows:
        try:
            s[r["key"]] = json.loads(r["value"])
        except ValueError:
            pass
    th = dataclasses.asdict(Thresholds())
    th.update({k: v for k, v in (s.get("thresholds") or {}).items() if k in th})
    s["thresholds"] = th
    return s


def set_settings(changes: dict) -> dict:
    allowed = set(DEFAULT_SETTINGS)
    old = get_settings()
    with db() as con:
        for k, v in changes.items():
            if k in allowed:
                con.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (k, json.dumps(v)))
    new = get_settings()
    if new["thresholds"] != old["thresholds"]:
        recompute_all(thresholds_from(new))
    return new


# ---------------------------------------------------------------------------
# V11: your rating, from your own games
# ---------------------------------------------------------------------------

TC_ORDER = ["bullet", "blitz", "rapid", "classical", "daily"]


def my_ratings() -> dict:
    """{time control: {"elo", "at", "site", "games"}}: your rating in your latest game of each
    time control. Per time control only the site where you play it most counts (chess.com and
    Lichess ratings differ); games against Maia don't count (their rating is the setting)."""
    out: dict = {}
    with db() as con:
        rows = con.execute(
            "SELECT tc_category AS tc, source, played_at, CASE WHEN player_color = 'White' THEN white_elo ELSE black_elo END AS elo "
            "FROM games WHERE source != ? AND player_color IN ('White', 'Black') AND tc_category IN (%s) "
            "ORDER BY played_at DESC" % ",".join("?" * len(TC_ORDER)), (BOT_SOURCE, *TC_ORDER)).fetchall()
    by: dict = {}
    for r in rows:
        if r["elo"] and 100 <= r["elo"] <= 3500:
            by.setdefault(r["tc"], []).append(r)
    for tc, rs in by.items():
        counts: dict = {}
        for r in rs:
            counts[r["source"]] = counts.get(r["source"], 0) + 1
        site = max(counts, key=counts.get)
        last = next(r for r in rs if r["source"] == site)        # rows are newest first
        out[tc] = {"elo": int(last["elo"]), "at": (last["played_at"] or "")[:10], "site": site, "games": counts[site]}
    return out


def main_tc(ratings: Optional[dict] = None, settings: Optional[dict] = None) -> Optional[str]:
    """The time control whose rating counts where a game doesn't say: the setting, else the one
    you analyse most, else the one you play most."""
    s = settings or get_settings()
    ratings = my_ratings() if ratings is None else ratings
    if s.get("rating_tc") in ratings:
        return s["rating_tc"]
    with db() as con:
        rows = con.execute("SELECT g.tc_category AS tc, COUNT(r.game_id) AS analysed, COUNT(*) AS n FROM games g "
                           "LEFT JOIN reviews r ON r.game_id = g.id WHERE g.source != ? GROUP BY g.tc_category", (BOT_SOURCE,)).fetchall()
    rows = [r for r in rows if r["tc"] in ratings]
    if not rows:
        return None
    return max(rows, key=lambda r: (r["analysed"], r["n"]))["tc"]


def my_rating(tc: Optional[str] = None, settings: Optional[dict] = None) -> int:
    """Your rating for a time control (or your main one), from your games when rating_auto is on;
    the typed rating otherwise, or when no game shows one."""
    s = settings or get_settings()
    manual = int(s.get("rating") or 1200)
    if not s.get("rating_auto", True):
        return manual
    rs = my_ratings()
    key = tc if tc in rs else main_tc(rs, s)
    return rs[key]["elo"] if key in rs else manual


def thresholds_from(settings: dict) -> Thresholds:
    return Thresholds(**settings["thresholds"])


def get_meta(key: str) -> Optional[str]:
    with db() as con:
        r = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return r["value"] if r else None


def set_meta(key: str, value: str) -> None:
    with db() as con:
        con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))


# ---------------------------------------------------------------------------
# Games
# ---------------------------------------------------------------------------

def _int(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def source_of(headers: dict) -> tuple[str, Optional[str], Optional[str]]:
    """(source, source id, url) from a PGN's Link / Site headers."""
    for key in ("Link", "Site"):
        v = headers.get(key, "") or ""
        m = CHESSCOM_RE.search(v)
        if m:
            return "chesscom", m.group(1), f"https://www.chess.com/game/live/{m.group(1)}"
        m = LICHESS_ID_RE.search(v)
        if m and m.group(1) not in LICHESS_RESERVED:
            return "lichess", m.group(1), f"https://lichess.org/{m.group(1)}"
    return "pgn", None, None


def _played_at(h: dict) -> str:
    d = h.get("UTCDate") or h.get("Date") or ""
    t = h.get("UTCTime") or h.get("StartTime") or ""
    if not re.match(r"^\d{4}\.\d{2}\.\d{2}$", d):
        return ""
    out = d.replace(".", "-")
    m = re.match(r"^(\d{1,2}):(\d{2})", t)
    if m:
        out += f" {int(m.group(1)):02d}:{m.group(2)}"
    return out


def game_id_for(game: chess.pgn.Game) -> str:
    h = game.headers
    src, sid, _ = source_of(dict(h))
    if sid:
        return f"{src}:{sid}"
    moves = " ".join(m.uci() for m in game.mainline_moves())
    key = "|".join([h.get("White", ""), h.get("Black", ""), h.get("Date", ""), h.get("FEN", ""), moves])
    return "pgn:" + hashlib.sha1(key.encode()).hexdigest()[:16]


def player_color_for(headers: dict, usernames: list[str]) -> Optional[str]:
    names = {u.strip().lower() for u in usernames if u and u.strip()}
    if headers.get("White", "").lower() in names:
        return "White"
    if headers.get("Black", "").lower() in names:
        return "Black"
    return None


def usernames(settings: dict) -> list[str]:
    return [settings.get("chesscom_user", ""), settings.get("lichess_user", "")]


def add_game(game: chess.pgn.Game, settings: dict, con: Optional[sqlite3.Connection] = None) -> tuple[str, bool]:
    """Stores one parsed game. Returns (id, newly_added)."""
    h = dict(game.headers)
    gid = game_id_for(game)
    src, _, url = source_of(h)
    eco, opening = h.get("ECO", ""), h.get("Opening", "")
    if not opening:  # chess.com and pasted games: name it from the Lichess opening list
        b, hit = game.board(), None
        for k, mv in enumerate(game.mainline_moves()):
            if k >= 40:
                break
            b.push(mv)
            hit = openings().get(b.epd()) or hit
        if hit:
            eco, opening = hit
    exporter = chess.pgn.StringExporter(headers=True, variations=False, comments=True)
    pgn = game.accept(exporter)
    row = (gid, src, url, time.time(), _played_at(h), h.get("White", ""), h.get("Black", ""),
           _int(h.get("WhiteElo")), _int(h.get("BlackElo")), h.get("Result", "*"),
           h.get("TimeControl", ""), time_control_category(h.get("TimeControl", "")),
           eco, opening, player_color_for(h, usernames(settings)),
           len(list(game.mainline_moves())), pgn)
    own = con is None
    con = con or connect()
    try:
        with _lock:
            cur = con.execute("INSERT OR IGNORE INTO games (id, source, url, imported_at, played_at, white, black, white_elo, black_elo, "
                              "result, time_control, tc_category, eco, opening, player_color, n_plies, pgn) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
            added = cur.rowcount == 1
            if own:
                con.commit()
    finally:
        if own:
            con.close()
    return gid, added


def _game_row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d.pop("pgn", None)
    d.pop("review_json", None)
    d["analysed"] = d.get("analysed_at") is not None
    if "tags" in d:
        d["tags"] = sorted(d["tags"].split("|")) if d.get("tags") else []
    me = d.get("review_color") or d.get("player_color")
    d["me"] = me
    if me:
        d["opponent"] = d["black"] if me == "White" else d["white"]
        d["my_elo"] = d["white_elo"] if me == "White" else d["black_elo"]
        d["opp_elo"] = d["black_elo"] if me == "White" else d["white_elo"]
        res = d.get("result") or "*"
        d["outcome"] = ("draw" if res == "1/2-1/2" else
                        "win" if (res == "1-0") == (me == "White") and res in ("1-0", "0-1") else
                        "loss" if res in ("1-0", "0-1") else "unknown")
    else:
        d["opponent"] = None
        d["outcome"] = "unknown"
    return d


LIST_SQL = """
SELECT g.*, r.analysed_at, r.player_color AS review_color, r.depth, r.accuracy, r.blunders, r.mistakes,
       r.inaccuracies, r.missed, r.maia_used, r.opp_accuracy, r.brilliant, r.great, r.version,
       (SELECT group_concat(t.tag, '|') FROM game_tags t WHERE t.game_id = g.id) AS tags,
       (SELECT COUNT(*) FROM game_notes n WHERE n.game_id = g.id) AS notes
FROM games g LEFT JOIN reviews r ON r.game_id = g.id
"""


BOT_SOURCE = "maia"


def maia_counted() -> bool:
    """Games against Maia are training, not your record: Insights leave them out unless this setting is on."""
    return bool(get_settings().get("insights_include_maia"))


def list_games(record_only: bool = False) -> list[dict]:
    """Every Library game, newest first. record_only: leave out games against Maia (unless counted)."""
    skip = record_only and not maia_counted()
    with db() as con:
        rows = con.execute(LIST_SQL + (" WHERE g.source != 'maia'" if skip else "")
                           + " ORDER BY CASE WHEN g.played_at = '' THEN 1 ELSE 0 END, g.played_at DESC, g.imported_at DESC").fetchall()
    return [_game_row(r) for r in rows]


def get_game(gid: str) -> Optional[dict]:
    with db() as con:
        r = con.execute(LIST_SQL + " WHERE g.id = ?", (gid,)).fetchone()
        pgn = con.execute("SELECT pgn FROM games WHERE id = ?", (gid,)).fetchone()
    if not r:
        return None
    d = _game_row(r)
    d["pgn"] = pgn["pgn"]
    return d


def game_pgn(gid: str) -> Optional[str]:
    with db() as con:
        r = con.execute("SELECT pgn FROM games WHERE id = ?", (gid,)).fetchone()
    return r["pgn"] if r else None


MIN_GAMES_FOR_MEDIAN = 30


def typical_moves(tc_category: str) -> tuple[Optional[float], int]:
    """Your median game length (moves per player) in this time control, from
    the Library, once there are enough games; else (None, count)."""
    with db() as con:
        rows = [r[0] for r in con.execute("SELECT n_plies FROM games WHERE tc_category = ? AND n_plies >= 10", (tc_category,)).fetchall()]
    if len(rows) < MIN_GAMES_FOR_MEDIAN:
        return None, len(rows)
    rows.sort()
    mid = rows[len(rows) // 2] if len(rows) % 2 else (rows[len(rows) // 2 - 1] + rows[len(rows) // 2]) / 2
    return mid / 2, len(rows)


def save_retry(game_id: Optional[str], ply: Optional[int], fen: str, uci: str, label: Optional[str], pp: Optional[float],
               solved: bool, gave_up: bool = False) -> None:
    with db() as con:
        con.execute("INSERT INTO retries (game_id, ply, fen, uci, label, pp, solved, gave_up, at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (game_id, ply, fen, uci, label, pp, int(solved), int(gave_up), time.time()))


def retries_for(game_id: str) -> list[dict]:
    with db() as con:
        rows = con.execute("SELECT ply, uci, label, solved, gave_up, at FROM retries WHERE game_id = ? ORDER BY at", (game_id,)).fetchall()
    return [dict(r) for r in rows]


def set_player_color(gid: str, color: Optional[str]) -> None:
    with db() as con:
        con.execute("UPDATE games SET player_color = ? WHERE id = ?", (color, gid))


def delete_games(ids: list[str], remember: bool = True) -> int:
    """Deletes games with everything built from them. remember: Sync won't bring them back."""
    n = 0
    now = time.time()
    with db() as con:
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            q = ",".join("?" * len(chunk))
            try:
                con.execute(f"DELETE FROM op_moves WHERE g IN (SELECT okey FROM games WHERE id IN ({q}))", chunk)
            except sqlite3.OperationalError:
                pass
            for t, col in (("reviews", "game_id"), ("puzzles", "game_id"), ("puzzle_scan", "game_id"), ("retries", "game_id"),
                           ("op_games", "game_id"), ("game_notes", "game_id"), ("game_tags", "game_id")):
                try:
                    con.execute(f"DELETE FROM {t} WHERE {col} IN ({q})", chunk)
                except sqlite3.OperationalError:
                    pass
            n += con.execute(f"DELETE FROM games WHERE id IN ({q})", chunk).rowcount
            if remember:
                con.executemany("INSERT OR REPLACE INTO deleted_games VALUES (?, ?)", [(g, now) for g in chunk])
    return n


# ---------------------------------------------------------------------------
# V7: notes and tags
# ---------------------------------------------------------------------------

def _clean_tag(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").strip().lower())[:32]


def get_notes(gid: str) -> dict:
    with db() as con:
        notes = {r["ply"]: r["text"] for r in con.execute("SELECT ply, text FROM game_notes WHERE game_id = ?", (gid,))}
        tags = sorted(r["tag"] for r in con.execute("SELECT tag FROM game_tags WHERE game_id = ?", (gid,)))
    return {"notes": notes, "tags": tags}


def set_note(gid: str, ply: int, text: str) -> None:
    text = (text or "").strip()
    with db() as con:
        if text:
            con.execute("INSERT OR REPLACE INTO game_notes VALUES (?,?,?,?)", (gid, int(ply), text[:4000], time.time()))
        else:
            con.execute("DELETE FROM game_notes WHERE game_id = ? AND ply = ?", (gid, int(ply)))


def set_tags(gid: str, tags: list) -> list:
    clean = sorted({_clean_tag(t) for t in tags or [] if _clean_tag(t)})[:12]
    with db() as con:
        con.execute("DELETE FROM game_tags WHERE game_id = ?", (gid,))
        con.executemany("INSERT INTO game_tags VALUES (?, ?)", [(gid, t) for t in clean])
    return clean


def all_tags() -> list:
    with db() as con:
        return [{"tag": r[0], "n": r[1]} for r in con.execute("SELECT tag, COUNT(*) FROM game_tags GROUP BY tag ORDER BY COUNT(*) DESC, tag")]


def search_notes(words: list) -> set:
    """Game ids whose notes contain every word."""
    if not words:
        return set()
    with db() as con:
        rows = con.execute("SELECT game_id, group_concat(text, ' ') t FROM game_notes GROUP BY game_id").fetchall()
    return {r["game_id"] for r in rows if all(w in (r["t"] or "").lower() for w in words)}


def deleted_ids() -> set:
    with db() as con:
        return {r[0] for r in con.execute("SELECT id FROM deleted_games")}


def forget_deleted() -> int:
    with db() as con:
        return con.execute("DELETE FROM deleted_games").rowcount


def vacuum() -> None:
    """Gives the space of deleted rows back to the disk."""
    with _lock:
        con = sqlite3.connect(db_path(), timeout=30)
        try:
            con.execute("VACUUM")
        finally:
            con.close()


def storage() -> dict:
    with db() as con:
        g = con.execute("SELECT COUNT(*), COALESCE(SUM(LENGTH(pgn)), 0) FROM games").fetchone()
        r = con.execute("SELECT COUNT(*), COALESCE(SUM(LENGTH(review_json)), 0) FROM reviews").fetchone()
        d = con.execute("SELECT COUNT(*) FROM deleted_games").fetchone()[0]
    try:
        size = os.path.getsize(db_path())
    except OSError:
        size = 0
    return {"bytes": size, "games": g[0], "pgn_bytes": g[1], "analysed": r[0], "review_bytes": r[1], "deleted": d}


def compress_old_reviews() -> int:
    """One-off: store reviews saved as plain text compressed."""
    n = 0
    with db() as con:
        for r in con.execute("SELECT game_id, review_json FROM reviews WHERE typeof(review_json) = 'text'").fetchall():
            con.execute("UPDATE reviews SET review_json = ? WHERE game_id = ?", (zlib.compress(r[1].encode("utf-8"), 6), r[0]))
            n += 1
    return n


def delete_game(gid: str) -> None:
    delete_games([gid])


def count_games() -> int:
    with db() as con:
        return con.execute("SELECT COUNT(*) FROM games").fetchone()[0]


def fill_player_colors(settings: dict) -> int:
    """After the usernames change: work out 'my side' for games that lack it."""
    names = usernames(settings)
    n = 0
    with db() as con:
        for r in con.execute("SELECT id, white, black FROM games WHERE player_color IS NULL").fetchall():
            c = player_color_for({"White": r["white"], "Black": r["black"]}, names)
            if c:
                con.execute("UPDATE games SET player_color = ? WHERE id = ?", (c, r["id"]))
                n += 1
    return n


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------

def review_to_json(review: GameReview) -> str:
    return json.dumps({
        "headers": review.headers, "player_color": review.player_color, "player_rating": review.player_rating,
        "raw": [dataclasses.asdict(p) for p in review.raw],
        "time_control": review.time_control, "time_control_raw": review.time_control_raw,
        "maia_used": review.maia_used, "maia_error": review.maia_error, "book_used": review.book_used, "maia_band": review.maia_band,
        "engine_name": review.engine_name, "depth": review.depth, "has_clocks": review.has_clocks,
        "analysis_version": review.analysis_version,
    })


def _unpack(s) -> str:
    """Reviews are stored zlib-compressed (about 9x smaller); old rows are plain JSON text."""
    if isinstance(s, (bytes, memoryview)):
        return zlib.decompress(bytes(s)).decode("utf-8")
    return s


def review_from_json(s, thresholds: Thresholds) -> GameReview:
    d = json.loads(_unpack(s))
    fields = {f.name for f in dataclasses.fields(PlyData)}
    raw = [PlyData(**{k: v for k, v in p.items() if k in fields}) for p in d["raw"]]
    review = GameReview(
        headers=d["headers"], player_color=d["player_color"], player_rating=d.get("player_rating"),
        raw=raw, moves=[], time_control=d.get("time_control", "unknown"), time_control_raw=d.get("time_control_raw", ""),
        maia_used=d.get("maia_used", False), maia_error=d.get("maia_error"), book_used=d.get("book_used", False),
        engine_name=d.get("engine_name", ""), depth=d.get("depth", 0), has_clocks=d.get("has_clocks", False),
        analysis_version=d.get("analysis_version", 1), maia_band=d.get("maia_band"),
    )
    return classify_review(review, thresholds)


def save_review(gid: str, review: GameReview, con: Optional[sqlite3.Connection] = None, analysed_at: Optional[float] = None) -> None:
    c = summary_columns(review)
    row = (gid, analysed_at or time.time(), review.player_color, review.depth, review.engine_name, int(review.maia_used),
           zlib.compress(review_to_json(review).encode("utf-8"), 6), c["accuracy"], c["blunders"], c["mistakes"], c["inaccuracies"], c["missed"],
           c["opp_accuracy"], c["brilliant"], c["great"], review.analysis_version)
    own = con is None
    con = con or connect()
    try:
        with _lock:
            con.execute("INSERT OR REPLACE INTO reviews (game_id, analysed_at, player_color, depth, engine, maia_used, review_json, "
                        "accuracy, blunders, mistakes, inaccuracies, missed, opp_accuracy, brilliant, great, version) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
            con.execute("UPDATE games SET player_color = ? WHERE id = ?", (review.player_color, gid))
            if own:
                con.commit()
    finally:
        if own:
            con.close()


def load_review(gid: str, thresholds: Thresholds) -> Optional[GameReview]:
    with db() as con:
        r = con.execute("SELECT review_json FROM reviews WHERE game_id = ?", (gid,)).fetchone()
    return review_from_json(r["review_json"], thresholds) if r else None


def all_reviews(thresholds: Thresholds, record_only: bool = False) -> list[dict]:
    """Every analysed game, oldest first: {id, game (row), review}. record_only: as in list_games."""
    skip = record_only and not maia_counted()
    with db() as con:
        rows = con.execute(LIST_SQL + " WHERE r.game_id IS NOT NULL" + (" AND g.source != 'maia'" if skip else "")
                           + " ORDER BY g.played_at, g.imported_at").fetchall()
        js = {r["game_id"]: r["review_json"] for r in con.execute("SELECT game_id, review_json FROM reviews").fetchall()}
    out = []
    for r in rows:
        try:
            out.append({"id": r["id"], "game": _game_row(r), "review": review_from_json(js[r["id"]], thresholds)})
        except Exception:
            continue
    return out


GRADING_VERSION = "5"   # bump when labels change (3: chess.com bands 5/10/20, exchange-count Brilliant, turns-the-game Great; 4: Brilliant by capture search + avoidable; 5: phases and Opening/Endgame types by Lichess's divider)


def refresh_grading() -> int:
    if get_meta("grading_version") == GRADING_VERSION:
        return 0
    n = recompute_all(thresholds_from(get_settings()))
    set_meta("grading_version", GRADING_VERSION)
    return n


def recompute_all(thresholds: Thresholds) -> int:
    """New thresholds: refresh the cached Library numbers (no engine needed)."""
    n = 0
    with db() as con:
        for r in con.execute("SELECT game_id, review_json FROM reviews").fetchall():
            try:
                c = summary_columns(review_from_json(r["review_json"], thresholds))
            except Exception:
                continue
            con.execute("UPDATE reviews SET accuracy=?, blunders=?, mistakes=?, inaccuracies=?, missed=?, opp_accuracy=?, brilliant=?, great=? WHERE game_id=?",
                        (c["accuracy"], c["blunders"], c["mistakes"], c["inaccuracies"], c["missed"], c["opp_accuracy"], c["brilliant"], c["great"], r["game_id"]))
            n += 1
    return n
