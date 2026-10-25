"""
Openings: the tree, repertoire, theory search, drills and line-by-line study.
"""

from __future__ import annotations

import json
import time

from api import ApiError, route
import repertoire
import store
import study
import theory


def _opfilters(q):
    g = lambda k, d="": (q.get(k) or [d])[0]
    color = g("color", "White")
    if color not in ("White", "Black"):
        raise ApiError(400, "color must be White or Black")
    period = g("period")
    since = ""
    if period.isdigit():
        since = time.strftime("%Y-%m-%d", time.gmtime(time.time() - int(period) * 86400))
    return color, g("tc"), since


@route("GET", r"/api/openings/tree")
def api_op_tree(body, q):
    color, tc, since = _opfilters(q)
    moves = [m for m in ((q.get("moves") or [""])[0]).split(",") if m]
    if repertoire.INDEXER.status["state"] != "running":
        repertoire.INDEXER.start()
    try:
        return repertoire.tree(moves, color, tc, since)
    except ValueError as e:
        raise ApiError(400, str(e))


@route("GET", r"/api/openings/scan")
def api_op_scan(body, q):
    color, tc, since = _opfilters(q)
    return repertoire.scan(color, tc, since)


@route("GET", r"/api/openings/index")
def api_op_index(body, q):
    return repertoire.INDEXER.status


@route("POST", r"/api/repertoire")
def api_rep_set(body, q):
    b = body or {}
    try:
        return repertoire.set_move(b.get("color", ""), list(b.get("moves") or []), b.get("uci"))
    except ValueError as e:
        raise ApiError(400, str(e))


@route("POST", r"/api/repertoire/build")
def api_rep_build(body, q):
    b = body or {}
    color = b.get("color", "White")
    repertoire.INDEXER.run()
    period = str(b.get("period") or "")
    since = time.strftime("%Y-%m-%d", time.gmtime(time.time() - int(period) * 86400)) if period.isdigit() else ""
    return repertoire.build_from_games(color, store.my_rating(), b.get("tc", ""), since)


@route("GET", r"/api/theory/search")
def api_theory_search(body, q):
    return {"results": theory.search((q.get("q") or [""])[0])}


@route("GET", r"/api/theory/recent")
def api_theory_recent(body, q):
    color = (q.get("color") or ["White"])[0]
    days = int((q.get("days") or ["90"])[0] or 90)
    return {"recent": theory.recent(color, days), "days": days}


@route("POST", r"/api/repertoire/learn")
def api_rep_learn(body, q):
    b = body or {}
    try:
        return theory.learn(b.get("color", ""), list(b.get("moves") or []), store.my_rating(),
                            use_engine=bool(b.get("engine", True)), level=b.get("level"))
    except ValueError as e:
        raise ApiError(400, str(e))


@route("GET", r"/api/repertoire/openings")
def api_rep_openings(body, q):
    return {"openings": theory.my_openings((q.get("color") or [""])[0])}


@route("POST", r"/api/repertoire/forget")
def api_rep_forget(body, q):
    b = body or {}
    return {"removed": theory.forget_opening(b.get("color", ""), b.get("name", ""))}


@route("GET", r"/api/repertoire/coverage")
def api_rep_coverage(body, q):
    color = (q.get("color") or ["White"])[0]
    return repertoire.coverage(color)


@route("GET", r"/api/drills")
def api_drills(body, q):
    return repertoire.drill_queue((q.get("color") or [""])[0], (q.get("more") or ["0"])[0] == "1", (q.get("opening") or [""])[0])


@route("POST", r"/api/drills/result")
def api_drill_result(body, q):
    b = body or {}
    try:
        return repertoire.drill_result(b.get("color", ""), b.get("epd", ""), b.get("result", ""))
    except KeyError:
        raise ApiError(404, "no such repertoire move")
    except ValueError as e:
        raise ApiError(400, str(e))


@route("GET", r"/api/study")
def api_study(body, q):
    try:
        study.apply_games()          # new games that left a reviewed line move it one step back
    except Exception:
        pass
    ov = study.overview()
    ov["levels"] = study.levels(store.my_rating())
    return ov


@route("GET", r"/api/study/queue")
def api_study_queue(body, q):
    g = lambda k, d="": (q.get(k) or [d])[0]
    return study.queue(g("color"), g("opening"), int(g("more", "0") or 0), g("practice") == "1")


@route("POST", r"/api/study/result")
def api_study_result(body, q):
    b = body or {}
    try:
        return study.result(b.get("color", ""), b.get("key", ""), bool(b.get("clean")), bool(b.get("practice")))
    except KeyError:
        raise ApiError(404, "no such line")


@route("GET", r"/api/study/lines")
def api_study_lines(body, q):
    return {"lines": study.lines_of((q.get("color") or ["White"])[0], (q.get("opening") or [""])[0])}


@route("POST", r"/api/study/due")
def api_study_due(body, q):
    b = body or {}
    return {"lines": study.make_due(b.get("color", ""), b.get("key", ""), b.get("prefix"))}


@route("POST", r"/api/study/level")
def api_study_level(body, q):
    """Changes how long an opening you learn goes (1-5) and rebuilds its lines."""
    b = body or {}
    color, name, level = b.get("color", ""), b.get("opening", ""), int(b.get("level") or 3)
    entry = theory.by_name(name)
    moves = entry["moves"] if entry else None
    if moves is None:
        with store.db() as con:
            study.ensure_schema(con)
            r = con.execute("SELECT moves FROM study_openings WHERE color = ? AND opening = ?", (color, name)).fetchone()
        moves = json.loads(r["moves"]) if r else []
    try:
        return theory.learn(color, moves, store.my_rating(), level=level)
    except ValueError as e:
        raise ApiError(400, str(e))


@route("GET", r"/api/study/deviations")
def api_study_deviations(body, q):
    return {"deviations": study.deviations(int((q.get("days") or ["30"])[0]))}


@route("GET", r"/api/study/explorer")
def api_study_explorer(body, q):
    return {"explorer": study.explorer((q.get("fen") or [""])[0])}


@route("GET", r"/api/study/insights")
def api_study_insights(body, q):
    return {"openings": study.insights()}
