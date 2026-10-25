"""
Account sync: pulls your game list from chess.com and Lichess into the Library.

Runs only when you press Sync (never on its own), and only adds games - it
never analyses them. Public APIs, no login:

  chess.com  /pub/player/<user>/games/archives -> one request per month.
             The first sync reads every month; later syncs re-read the last
             synced month and anything newer.
  Lichess    /api/games/user/<user> as NDJSON with clocks and opening names,
             since the newest game already synced. Anonymous rate is about
             20 games a second, so a first sync of thousands of games takes
             a few minutes.

Only standard chess is kept (no variants). Games already in the Library are
skipped (ids come from the game URL, so a pasted chess.com game and a synced
one are the same game).

Selective sync (Settings > Sync): a time window, time controls and an
opponent rating range. chess.com months before the window are not fetched at
all; Lichess gets `since` and `perfType`; everything else is filtered per
game. Changing the filters re-reads the months in range once (games already
in the Library are skipped). `outside()` lists Library games the filters
exclude, for the "trim" button.
"""

from __future__ import annotations

import io
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

import datetime as dt

import chess.pgn

import store
from chess_analysis import USER_AGENT, time_control_category

CHESSCOM = "https://api.chess.com/pub/player/{user}/games/archives"
LICHESS = "https://lichess.org/api/games/user/{user}"


def _open(url: str, accept: str):
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=60)


def http_json(url: str) -> dict:
    with _open(url, "application/json") as r:
        return json.loads(r.read().decode("utf-8"))


def http_lines(url: str):
    with _open(url, "application/x-ndjson") as r:
        for raw in r:
            raw = raw.strip()
            if raw:
                yield raw.decode("utf-8")


class SyncCancelled(Exception):
    pass


TCS = ("bullet", "blitz", "rapid", "classical", "daily")
LICHESS_PERF = {"bullet": "ultraBullet,bullet", "blitz": "blitz", "rapid": "rapid",
                "classical": "classical", "daily": "correspondence"}
WINDOW_MONTHS = {"3m": 3, "6m": 6, "12m": 12, "24m": 24}


def sync_filter(settings: dict, today: Optional[dt.date] = None) -> dict:
    """The selective-sync filter from Settings: since (YYYY-MM-DD or ''),
    tcs (list, empty = all), opp_min / opp_max (int or None), key (changes
    only when you change the settings, not as a rolling window moves)."""
    today = today or dt.date.today()
    w = settings.get("sync_window") or "all"
    since = ""
    if w in WINDOW_MONTHS:
        m = today.year * 12 + today.month - 1 - WINDOW_MONTHS[w]
        since = dt.date(m // 12, m % 12 + 1, min(today.day, 28)).isoformat()
    elif w == "since" and settings.get("sync_since"):
        since = str(settings["sync_since"])[:10]
    tcs = [t for t in (settings.get("sync_tcs") or []) if t in TCS]
    if set(tcs) == set(TCS):
        tcs = []

    def num(v):
        try:
            return int(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None
    lo, hi = num(settings.get("sync_opp_min")), num(settings.get("sync_opp_max"))
    key = json.dumps([w, settings.get("sync_since") if w == "since" else "", sorted(tcs), lo, hi])
    return {"since": since, "tcs": tcs, "opp_min": lo, "opp_max": hi, "key": key,
            "active": bool(since or tcs or lo is not None or hi is not None)}


def keep(f: dict, played_at: str, tc_category: str, opp_elo) -> bool:
    if f["since"] and played_at and played_at[:10] < f["since"]:
        return False
    if f["tcs"] and tc_category not in f["tcs"]:
        return False
    if opp_elo is not None:
        if f["opp_min"] is not None and opp_elo < f["opp_min"]:
            return False
        if f["opp_max"] is not None and opp_elo > f["opp_max"]:
            return False
    return True


def outside(f: dict) -> list:
    """Synced Library games the filter excludes (pasted / imported games are never trimmed)."""
    return [g for g in store.list_games()
            if g.get("source") in ("chesscom", "lichess")
            and not keep(f, g.get("played_at") or "", g.get("tc_category") or "", g.get("opp_elo"))]


class Syncer:
    """One sync at a time, in a background thread. `status` is polled by the UI."""

    def __init__(self):
        self.lock = threading.Lock()
        self.status = {"state": "idle"}
        self.cancel_flag = threading.Event()
        # injectable for tests
        self.get_json: Callable[[str], dict] = http_json
        self.get_lines: Callable[[str], object] = http_lines

    def start(self) -> dict:
        with self.lock:
            if self.status.get("state") == "running":
                return dict(self.status)
            s = store.get_settings()
            users = {"chesscom": s.get("chesscom_user", "").strip(), "lichess": s.get("lichess_user", "").strip()}
            if not any(users.values()):
                raise ValueError("Add your chess.com and/or Lichess username in Settings first.")
            self.cancel_flag.clear()
            self.status = {"state": "running", "started": time.time(), "added": 0, "seen": 0,
                           "step": "Starting…", "errors": [], "sources": {}}
        threading.Thread(target=self._run, args=(users,), daemon=True, name="sync").start()
        return dict(self.status)

    def cancel(self):
        self.cancel_flag.set()

    def snapshot(self) -> dict:
        with self.lock:
            st = dict(self.status)
        st["last"] = json.loads(store.get_meta("last_sync") or "null")
        return st

    # ------------------------------------------------------------------
    def _check(self):
        if self.cancel_flag.is_set():
            raise SyncCancelled()

    def _add_pgns(self, pgns: list[str], source: str) -> None:
        settings = store.get_settings()
        f = getattr(self, "_filter", None)
        names = store.usernames(settings)
        added = filtered = 0
        with store.db() as con:
            for pgn in pgns:
                try:
                    g = chess.pgn.read_game(io.StringIO(pgn))
                except Exception:
                    continue
                if g is None or g.errors or not list(g.mainline_moves()):
                    continue
                if getattr(self, "_deleted", None) and store.game_id_for(g) in self._deleted:
                    continue   # you deleted this one on purpose
                if f and f["active"]:
                    h = g.headers
                    me = store.player_color_for(h, names)
                    opp = store._int(h.get("BlackElo" if me == "White" else "WhiteElo")) if me else None
                    if not keep(f, store._played_at(h), time_control_category(h.get("TimeControl", "")), opp):
                        filtered += 1
                        continue
                _, new = store.add_game(g, settings, con)
                added += new
        with self.lock:
            self.status["added"] += added
            self.status["seen"] += len(pgns)
            self.status["filtered"] = self.status.get("filtered", 0) + filtered
            src = self.status["sources"].setdefault(source, {"added": 0, "seen": 0})
            src["added"] += added
            src["seen"] += len(pgns)

    def _run(self, users: dict):
        if store.get_settings().get("restore_deleted"):
            # bring deleted games back: forget them and fetch every month again (existing games are skipped)
            store.forget_deleted()
            store.set_meta("sync_state", "{}")
            store.set_settings({"restore_deleted": False})
        self._deleted = store.deleted_ids()
        state = json.loads(store.get_meta("sync_state") or "{}")
        self._filter = sync_filter(store.get_settings())
        if state.get("filter_key", self._filter["key"]) != self._filter["key"]:
            # filters changed: read the months in range again (existing games are skipped)
            state = {}
        state["filter_key"] = self._filter["key"]
        started = self.status["started"]
        try:
            if users["chesscom"]:
                self._chesscom(users["chesscom"], state)
            if users["lichess"]:
                self._lichess(users["lichess"], state)
            final = "done"
        except SyncCancelled:
            final = "cancelled"
        except Exception as e:  # unexpected - keep what was added
            with self.lock:
                self.status["errors"].append(f"{e.__class__.__name__}: {e}")
            final = "error"
        store.set_meta("sync_state", json.dumps(state))
        with self.lock:
            self.status["state"] = final
            self.status["finished"] = time.time()
            self.status["step"] = ""
            summary = {"at": started, "finished": self.status["finished"], "added": self.status["added"],
                       "seen": self.status["seen"], "filtered": self.status.get("filtered", 0), "state": final, "errors": self.status["errors"][:5],
                       "sources": self.status["sources"]}
        store.set_meta("last_sync", json.dumps(summary))

    def _step(self, text: str):
        with self.lock:
            self.status["step"] = text

    def _chesscom(self, user: str, state: dict):
        st = state.get("chesscom") or {}
        if st.get("user", "").lower() != user.lower():
            st = {"user": user}
        self._step(f"chess.com: finding {user}'s months…")
        try:
            archives = self.get_json(CHESSCOM.format(user=urllib.parse.quote(user.lower())))["archives"]
        except urllib.error.HTTPError as e:
            msg = f"chess.com: no player called '{user}'" if e.code in (404, 410) else f"chess.com: HTTP {e.code}"
            with self.lock:
                self.status["errors"].append(msg)
            return
        except Exception as e:
            with self.lock:
                self.status["errors"].append(f"chess.com: could not connect ({e.__class__.__name__})")
            return
        last = st.get("last_month")  # 'YYYY/MM'
        first = self._filter["since"][:7].replace("-", "/") if self._filter["since"] else ""
        todo = [u for u in archives if (not last or u.rstrip("/")[-7:] >= last) and u.rstrip("/")[-7:] >= first]
        for k, url in enumerate(todo, 1):
            self._check()
            month = url.rstrip("/")[-7:]
            self._step(f"chess.com: {month.replace('/', '-')} ({k} of {len(todo)} months)")
            try:
                data = self.get_json(url)
            except Exception as e:
                with self.lock:
                    self.status["errors"].append(f"chess.com {month}: {e.__class__.__name__}")
                continue
            pgns = [g["pgn"] for g in data.get("games", []) if g.get("rules", "chess") == "chess" and g.get("pgn")]
            self._add_pgns(pgns, "chess.com")
            st["last_month"] = month
            state["chesscom"] = st
            if k < len(todo):
                time.sleep(0.15)  # chess.com asks for serial, unhurried requests

    def _lichess(self, user: str, state: dict):
        st = state.get("lichess") or {}
        if st.get("user", "").lower() != user.lower():
            st = {"user": user}
        since = st.get("since")
        q = {"pgnInJson": "true", "clocks": "true", "opening": "true", "sort": "dateAsc"}
        if since:
            q["since"] = str(int(since) + 1)
        f = self._filter
        if f["since"]:
            start = int(dt.datetime.fromisoformat(f["since"]).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
            q["since"] = str(max(int(q.get("since", 0)), start))
        if f["tcs"]:
            q["perfType"] = ",".join(LICHESS_PERF[t] for t in f["tcs"])
        url = LICHESS.format(user=urllib.parse.quote(user)) + "?" + urllib.parse.urlencode(q)
        self._step(f"Lichess: downloading {user}'s games…")
        batch, n = [], 0
        try:
            for line in self.get_lines(url):
                self._check()
                try:
                    g = json.loads(line)
                except ValueError:
                    continue
                if g.get("variant", "standard") == "standard" and g.get("pgn"):
                    batch.append(g["pgn"])
                st["since"] = max(int(st.get("since") or 0), int(g.get("createdAt") or 0))
                n += 1
                if len(batch) >= 100:
                    self._add_pgns(batch, "Lichess")
                    batch = []
                    self._step(f"Lichess: {n} games read…")
                    state["lichess"] = st
        except SyncCancelled:
            raise
        except urllib.error.HTTPError as e:
            msg = f"Lichess: no player called '{user}'" if e.code == 404 else (
                "Lichess is rate-limiting; try again in a minute" if e.code == 429 else f"Lichess: HTTP {e.code}")
            with self.lock:
                self.status["errors"].append(msg)
        except Exception as e:
            with self.lock:
                self.status["errors"].append(f"Lichess: could not connect ({e.__class__.__name__})")
        finally:
            if batch:
                self._add_pgns(batch, "Lichess")
            state["lichess"] = st
