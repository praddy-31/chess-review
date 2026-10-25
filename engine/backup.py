"""
Backups of the app's database (V7).

  - automatic: when the app starts and the newest backup is a week old
  - "Back up now" in Settings
  - each backup is one gzip-compressed SQLite file in <data folder>/backups,
    made with SQLite's online backup (safe while the app runs)
  - the newest 10 are kept
  - restoring checks the file, keeps a copy of today's database, and swaps
    the files the next time the app starts (nothing is open then)
"""

from __future__ import annotations

import gzip
import os
import shutil
import sqlite3
import tempfile
import threading
import time
from typing import Optional

import store
import system

KEEP = 10
AUTO_DAYS = 7
PENDING = "restore-pending.sqlite"


def folder() -> str:
    d = os.path.join(store.data_dir(), "backups")
    os.makedirs(d, exist_ok=True)
    return d


def _name(kind: str) -> str:
    return time.strftime("chess-%Y-%m-%d-%H%M%S", time.localtime()) + ("-auto" if kind == "auto" else "") + ".sqlite.gz"


def make(kind: str = "manual") -> dict:
    """Writes a backup now; returns its entry."""
    d = folder()
    fd, tmp = tempfile.mkstemp(suffix=".sqlite", dir=d)
    os.close(fd)
    try:
        src = sqlite3.connect(store.db_path(), timeout=30)
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        out = os.path.join(d, _name(kind))
        with open(tmp, "rb") as f, gzip.open(out, "wb", compresslevel=6) as g:
            shutil.copyfileobj(f, g)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    prune()
    store.set_meta("last_backup", repr(time.time()))
    return _entry(out)


def _entry(path: str) -> dict:
    st = os.stat(path)
    name = os.path.basename(path)
    return {"name": name, "bytes": st.st_size, "at": st.st_mtime, "kind": "auto" if "-auto" in name else "manual"}


def list_backups() -> list[dict]:
    d = folder()
    out = [_entry(os.path.join(d, n)) for n in os.listdir(d) if n.endswith(".sqlite.gz")]
    return sorted(out, key=lambda e: -e["at"])


def prune(keep: int = KEEP) -> int:
    gone = 0
    for e in list_backups()[keep:]:
        try:
            os.remove(os.path.join(folder(), e["name"]))
            gone += 1
        except OSError:
            pass
    return gone


def auto_if_due() -> Optional[dict]:
    """Makes an automatic backup when the newest one is a week old (or there is none)."""
    bs = list_backups()
    if bs and time.time() - bs[0]["at"] < AUTO_DAYS * 86400:
        return None
    if store.count_games() == 0:
        return None
    return make("auto")


def auto_in_background() -> None:
    def run():
        try:
            auto_if_due()
        except Exception:
            pass
    threading.Thread(target=run, daemon=True, name="backup").start()


def _safe(name: str) -> str:
    if os.path.basename(name) != name or not name.endswith(".sqlite.gz"):
        raise ValueError("not a backup file")
    p = os.path.join(folder(), name)
    if not os.path.exists(p):
        raise FileNotFoundError(name)
    return p


def stage_restore(name: str) -> dict:
    """Checks a backup and stages it; the swap happens when the app next starts."""
    p = _safe(name)
    dest = os.path.join(store.data_dir(), PENDING)
    with gzip.open(p, "rb") as g, open(dest, "wb") as f:
        shutil.copyfileobj(g, f)
    con = sqlite3.connect(dest)
    try:
        ok = con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        n = con.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    except sqlite3.DatabaseError:
        ok, n = False, 0
    finally:
        con.close()
    if not ok:
        os.remove(dest)
        raise ValueError("that backup is damaged")
    return {"staged": name, "games": n}


def cancel_restore() -> bool:
    p = os.path.join(store.data_dir(), PENDING)
    if os.path.exists(p):
        os.remove(p)
        return True
    return False


def pending() -> bool:
    return os.path.exists(os.path.join(store.data_dir(), PENDING))


def apply_pending() -> Optional[str]:
    """At start-up, before anything opens the database: swap in a staged backup.
    Today's database is kept as a backup first, so a restore can be undone."""
    p = os.path.join(store.data_dir(), PENDING)
    if not os.path.exists(p):
        return None
    db = store.db_path()
    if os.path.exists(db):
        keep = os.path.join(folder(), time.strftime("chess-%Y-%m-%d-%H%M%S-before-restore.sqlite.gz", time.localtime()))
        with open(db, "rb") as f, gzip.open(keep, "wb", compresslevel=6) as g:
            shutil.copyfileobj(f, g)
    for ext in ("-wal", "-shm"):
        try:
            os.remove(db + ext)
        except OSError:
            pass
    os.replace(p, db)
    return db


def reveal() -> bool:
    """Shows the backups folder in Finder / Explorer / the file manager."""
    return system.reveal(folder())
