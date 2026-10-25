"""
The coach, backups and the first-run welcome.
"""

from __future__ import annotations

import time

from api import ApiError, route
import backup
import coach
import engines
import store


@route("GET", r"/api/coach/status")
def api_coach_status(body, q):
    s = store.get_settings()
    return {**coach.ollama_status(), "enabled": bool(s.get("coach_ollama")), "model": s.get("coach_model") or ""}


@route("POST", r"/api/coach/ask")
def api_coach_ask(body, q):
    b = body or {}
    try:
        return coach.explain(b.get("fen", ""), b.get("uci", ""), b.get("question", ""), b.get("game"))
    except ValueError as e:
        raise ApiError(400, str(e))
    except RuntimeError as e:
        raise ApiError(409, str(e))


@route("POST", r"/api/coach/chat")
def api_coach_chat(body, q):
    b = body or {}
    if not (b.get("question") or "").strip():
        raise ApiError(400, "ask a question")
    return coach.chat(list(b.get("facts") or []), list(b.get("history") or []), b.get("question", ""))


@route("GET", r"/api/backups")
def api_backups(body, q):
    return {"backups": backup.list_backups(), "folder": backup.folder(), "pending": backup.pending()}


@route("POST", r"/api/backups")
def api_backup_now(body, q):
    return backup.make("manual")


@route("POST", r"/api/backups/restore")
def api_backup_restore(body, q):
    try:
        return backup.stage_restore((body or {}).get("name", ""))
    except FileNotFoundError:
        raise ApiError(404, "no such backup")
    except ValueError as e:
        raise ApiError(400, str(e))


@route("POST", r"/api/backups/cancel")
def api_backup_cancel(body, q):
    return {"cancelled": backup.cancel_restore()}


@route("POST", r"/api/backups/reveal")
def api_backup_reveal(body, q):
    return {"ok": backup.reveal()}


@route("GET", r"/api/welcome")
def api_welcome(body, q):
    s = store.get_settings()
    return {"done": bool(store.get_meta("onboarded")), "users": bool(s.get("chesscom_user") or s.get("lichess_user")),
            "games": store.count_games(), "engines": engines.status(s)}


@route("POST", r"/api/welcome/done")
def api_welcome_done(body, q):
    store.set_meta("onboarded", repr(time.time()))
    return {"ok": True}
