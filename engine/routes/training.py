"""
Training: the Board's live engine, puzzles and saved variations, convert-the-win drills, Play against Maia.
"""

from __future__ import annotations

import urllib.parse

from api import ApiError, route
import convert
import engines
import live
import play
import puzzles
import store


@route("GET", r"/api/play")
def api_play(body, q):
    """V10: what Play can offer (Maia bands installed, last choices, recent games)."""
    return play.options()


@route("POST", r"/api/play/start")
def api_play_start(body, q):
    b = body or {}
    try:
        return play.start(int(b.get("band") or 0), b.get("color", "random"), b.get("clock", "none"))
    except RuntimeError as e:
        raise ApiError(400, str(e))


@route("POST", r"/api/play/(?P<pid>[0-9a-f]+)/move")
def api_play_move(body, q, pid):
    b = body or {}
    try:
        return play.move(pid, b.get("uci", ""), b.get("spent") or 0)
    except KeyError as e:
        raise ApiError(404, str(e).strip("'\""))
    except ValueError as e:
        raise ApiError(400, str(e))


@route("POST", r"/api/play/(?P<pid>[0-9a-f]+)/(?P<act>resign|flag|pause|resume)")
def api_play_end(body, q, pid, act):
    """Resign, flag, or pause / resume (V11: the game is saved and the clocks stop)."""
    try:
        if act in ("pause", "resume"):
            return play.pause(pid, (body or {}).get("spent") or 0) if act == "pause" else play.resume(pid)
        return play.resign(pid) if act == "resign" else play.flag(pid)
    except KeyError as e:
        raise ApiError(404, str(e).strip("'\""))
    except (ValueError, RuntimeError) as e:     # RuntimeError: lc0 or the net went missing since
        raise ApiError(400, str(e))


@route("GET", r"/api/convert")
def api_convert(body, q):
    convert.scan()
    return convert.queue((q.get("more") or ["0"])[0] == "1")


@route("POST", r"/api/convert/(?P<did>[^/]+)/start")
def api_convert_start(body, q, did):
    try:
        return convert.start(did)
    except KeyError:
        raise ApiError(404, "no such drill")
    except RuntimeError as e:
        raise ApiError(409, str(e))


@route("POST", r"/api/convert/(?P<did>[^/]+)/move")
def api_convert_move(body, q, did):
    try:
        return convert.move(did, (body or {}).get("uci", ""))
    except KeyError as e:
        raise ApiError(409, str(e).strip("'"))
    except ValueError as e:
        raise ApiError(400, str(e))


@route("POST", r"/api/convert/(?P<did>[^/]+)/resign")
def api_convert_resign(body, q, did):
    return convert.resign(did)


def _live_opts():
    s = store.get_settings()
    return {"Threads": max(1, int(s.get("threads", 2))), "Hash": 128}


LIVE = live.Live(lambda: engines._which("stockfish", store.get_settings().get("stockfish_path", "")), _live_opts)


STRENGTH = {   # analysis-board engine: how deep, how many cores, how long per position
    "low": {"depth": 14, "threads": 1, "time": 15},
    "medium": {"depth": 20, "threads": 2, "time": 45},
    "high": {"depth": 30, "threads": 0, "time": 90},   # 0 = the Threads setting
}


@route("POST", r"/api/live/start")
def api_live_start(body, q):
    b = body or {}
    s = store.get_settings()
    st = STRENGTH.get(b.get("strength") or s.get("live_strength") or "medium", STRENGTH["medium"])
    threads = st["threads"] or max(1, int(s.get("threads", 2)))
    try:
        return LIVE.start(b.get("fen", ""), int(b.get("multipv", 3)), depth=st["depth"], threads=threads, seconds=st["time"])
    except ValueError:
        raise ApiError(400, "bad FEN")
    except RuntimeError as e:
        raise ApiError(400, str(e))


@route("GET", r"/api/live")
def api_live_poll(body, q):
    return LIVE.poll((q.get("fen") or [None])[0])


@route("POST", r"/api/live/stop")
def api_live_stop(body, q):
    LIVE.stop()
    return {"ok": True}


@route("GET", r"/api/puzzles")
def api_puzzles(body, q):
    puzzles.scan()
    ids = [x for x in (q.get("ids") or [""])[0].split(",") if x]
    return puzzles.queue((q.get("motif") or [""])[0], (q.get("more") or ["0"])[0] == "1", (q.get("kind") or [""])[0], ids=ids)


@route("POST", r"/api/puzzles/(?P<pid>[^/]+)/result")
def api_puzzle_result(body, q, pid):
    b = body or {}
    try:
        return puzzles.record(urllib.parse.unquote(pid), b.get("result", ""), int(b.get("hints", 0)), b.get("judged"))
    except KeyError:
        raise ApiError(404, "no such puzzle")
    except ValueError as e:
        raise ApiError(400, str(e))


@route("GET", r"/api/puzzles/stats")
def api_puzzle_stats(body, q):
    puzzles.scan()
    return puzzles.stats()


@route("GET", r"/api/variations")
def api_variations(body, q):
    return {"variations": puzzles.variations()}


@route("POST", r"/api/variations")
def api_variation_save(body, q):
    b = body or {}
    try:
        vid = puzzles.save_variation(b.get("name", ""), b.get("fen", ""), list(b.get("moves") or []), b.get("game_id"), b.get("ply"))
    except ValueError as e:
        raise ApiError(400, str(e))
    return {"id": vid}


@route("DELETE", r"/api/variations/(?P<vid>\d+)")
def api_variation_delete(body, q, vid):
    puzzles.delete_variation(int(vid))
    return {"ok": True}
