"""
Status, settings, following Palette, the Library's games, Sync, the analysis queue, saving to Downloads, opening links.
"""

from __future__ import annotations

import json
import os
import re
import threading

import api
from api import ApiError, route
import engines
import importer
import palette
import plan
import repertoire
import store
import system
import sync
from payload import review_payload


@route("GET", r"/api/palette")
def api_palette(body, q):
    """V11: Palette's colours for this app (a local file) and the setup check. The page asks
    every couple of seconds only while "Follow Palette" is on."""
    return {"following": bool(store.get_settings().get("follow_palette")), **palette.status()}


@route("GET", r"/api/status")
def api_status(body, q):
    s = store.get_settings()
    return {"version": api.VERSION, "platform": system.NAME, "file_manager": system.file_manager(), "engines": engines.status(s), "games": store.count_games(),
            "last_sync": json.loads(store.get_meta("last_sync") or "null"),
            "setup_done": store.get_meta("setup_done") == "1"}


@route("POST", r"/api/setup-done")
def api_setup_done(body, q):
    store.set_meta("setup_done", "1")
    return {"ok": True}


def _with_ratings(s: dict) -> dict:
    """V11: the settings plus your ratings from your games (read-only keys: saving them back is ignored)."""
    rs = store.my_ratings()
    return {**s, "ratings": rs, "rating_main_tc": store.main_tc(rs, s), "rating_used": store.my_rating(settings=s)}


@route("GET", r"/api/settings")
def api_settings(body, q):
    return _with_ratings(store.get_settings())


@route("POST", r"/api/settings")
def api_settings_set(body, q):
    old = store.get_settings()
    new = store.set_settings(body or {})
    if (old["chesscom_user"], old["lichess_user"]) != (new["chesscom_user"], new["lichess_user"]):
        store.fill_player_colors(new)
    return _with_ratings(new)


@route("GET", r"/api/games")
def api_games(body, q):
    jobs = {j["id"]: j for j in api.ANALYSER.snapshot()}
    out = store.list_games()
    for g in out:
        j = jobs.get(g["id"])
        g["job"] = j if j and j["state"] in ("queued", "running", "error") else None
    return {"games": out}


@route("POST", r"/api/import")
def api_import(body, q):
    try:
        return importer.import_text((body or {}).get("text", ""))
    except ValueError as e:
        raise ApiError(400, str(e))


@route("GET", r"/api/games/(?P<gid>[^/]+)")
def api_game(body, q, gid):
    g = store.get_game(gid)
    if not g:
        raise ApiError(404, "game not found")
    jobs = {j["id"]: j for j in api.ANALYSER.snapshot()}
    g["job"] = jobs.get(gid)
    if g["analysed"]:
        rv = store.load_review(gid, store.thresholds_from(store.get_settings()))
        n, count = store.typical_moves(g.get("tc_category") or "")
        g["review"] = review_payload(rv, n, f"your {count} {g.get('tc_category')} games (median {n:.0f} moves)" if n else "")
        _mark_repertoire(g["review"])
        try:
            plan.log_review(gid)          # counts toward the weekly plan's "review your games"
        except Exception:
            pass
    return g


def _mark_repertoire(rp: dict) -> None:
    """Your moves in a position you starred: did you play your repertoire move? The first time you
    didn't is marked on that move (V5)."""
    from chess_analysis import _epd
    color = rp.get("player")
    if not color:
        return
    rep = repertoire.rep_map(color)
    if not rep:
        return
    for p in rp.get("plies", []):
        if not p.get("mine"):
            continue
        hit = rep.get(_epd(p["fen_before"]))
        if not hit:
            continue
        p["rep"] = {"planned_uci": hit[0], "planned": hit[1], "followed": hit[0] == p["played_uci"]}
        if hit[0] != p["played_uci"]:
            rp["left_repertoire"] = {"ply": p["ply"], "planned": hit[1], "played": p["san"], "label": p["label"]}
            break


@route("DELETE", r"/api/games/(?P<gid>[^/]+)")
def api_game_delete(body, q, gid):
    api.ANALYSER.cancel(gid)
    store.delete_game(gid)
    return {"ok": True}


@route("POST", r"/api/games/delete-many")
def api_delete_many(body, q):
    ids = [str(x) for x in (body or {}).get("ids") or []]
    for gid in ids:
        api.ANALYSER.cancel(gid)
    n = store.delete_games(ids, remember=bool((body or {}).get("remember", True)))
    threading.Thread(target=store.vacuum, daemon=True, name="vacuum").start()
    return {"deleted": n}


@route("GET", r"/api/storage")
def api_storage(body, q):
    return store.storage()


@route("POST", r"/api/storage/forget-deleted")
def api_forget_deleted(body, q):
    return {"forgotten": store.forget_deleted()}


@route("POST", r"/api/games/(?P<gid>[^/]+)/side")
def api_game_side(body, q, gid):
    color = (body or {}).get("color")
    if color not in ("White", "Black"):
        raise ApiError(400, "color must be White or Black")
    store.set_player_color(gid, color)
    return {"ok": True}


@route("POST", r"/api/games/(?P<gid>[^/]+)/analyse")
def api_analyse(body, q, gid):
    if not store.get_game(gid):
        raise ApiError(404, "game not found")
    b = body or {}
    if b.get("color") in ("White", "Black"):
        store.set_player_color(gid, b["color"])
    api.need_stockfish()
    return api.ANALYSER.enqueue(gid, b.get("color"), b.get("depth"))


@route("POST", r"/api/analyse-many")
def api_analyse_many(body, q):
    """Queues the games you selected (never anything you didn't pick)."""
    ids = (body or {}).get("ids") or []
    api.need_stockfish()
    n, skipped = 0, 0
    for gid in ids:
        g = store.get_game(gid)
        if g and g["player_color"]:
            api.ANALYSER.enqueue(gid)
            n += 1
        else:
            skipped += 1
    return {"queued": n, "skipped": skipped}


@route("POST", r"/api/sync")
def api_sync(body, q):
    try:
        return api.SYNCER.start()
    except ValueError as e:
        raise ApiError(400, str(e))


@route("GET", r"/api/sync")
def api_sync_status(body, q):
    return api.SYNCER.snapshot()


@route("GET", r"/api/sync/outside")
def api_sync_outside(body, q):
    """How many synced games the selective-sync filters exclude."""
    f = sync.sync_filter(store.get_settings())
    out = sync.outside(f) if f["active"] else []
    return {"active": f["active"], "since": f["since"], "games": len(out),
            "analysed": sum(1 for g in out if g.get("analysed"))}


@route("POST", r"/api/sync/trim")
def api_sync_trim(body, q):
    """Removes synced games outside the filters. Not remembered as deleted:
    widen the filters and the next Sync brings them back."""
    f = sync.sync_filter(store.get_settings())
    if not f["active"]:
        raise ApiError(400, "Set a sync filter first.")
    ids = [g["id"] for g in sync.outside(f) if (body or {}).get("include_analysed") or not g.get("analysed")]
    for gid in ids:
        api.ANALYSER.cancel(gid)
    n = store.delete_games(ids, remember=False) if ids else 0
    if n:
        threading.Thread(target=store.vacuum, daemon=True, name="vacuum").start()
    return {"deleted": n}


@route("POST", r"/api/sync/cancel")
def api_sync_cancel(body, q):
    api.SYNCER.cancel()
    return {"ok": True}


@route("POST", r"/api/games/(?P<gid>[^/]+)/cancel")
def api_cancel(body, q, gid):
    api.ANALYSER.cancel(gid)
    return {"ok": True}


@route("GET", r"/api/jobs")
def api_jobs(body, q):
    return {"jobs": api.ANALYSER.snapshot()}


@route("POST", r"/api/save-download")
def api_save_download(body, q):
    """Writes a text file into Downloads (the webview can't download files)."""
    b = body or {}
    name = re.sub(r"[^\w .-]", "_", b.get("name") or "chess-review.md").strip() or "chess-review.md"
    folder = system.downloads_dir()
    os.makedirs(folder, exist_ok=True)
    stem, ext = os.path.splitext(name)
    path, i = os.path.join(folder, name), 1
    while os.path.exists(path):
        path = os.path.join(folder, f"{stem} ({i}){ext}")
        i += 1
    with open(path, "w", encoding="utf-8") as f:
        f.write(b.get("text", ""))
    return {"path": path}


@route("POST", r"/api/open")
def api_open(body, q):
    url = (body or {}).get("url", "")
    if not re.match(r"^https://[\w.-]+(/[\w\-./?=&%#:+~]*)?$", url):
        raise ApiError(400, "only https links can be opened")
    system.open_url(url)
    return {"ok": True}
