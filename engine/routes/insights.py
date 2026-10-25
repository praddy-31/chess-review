"""
Insights: the skill profile, by phase, weekly focus, mistakes you repeat, the weekly note, opponents, the study plan.
"""

from __future__ import annotations

import api
from api import ApiError, route
import insights
import opponents
import patterns
import phases
import plan
import skillprofile
import store
import weekly


@route("GET", r"/api/insights")
def api_insights(body, q):
    s = store.get_settings()
    typical = {k: store.typical_moves(k)[0] for k in insights.TC_ORDER}
    return insights.build(store.all_reviews(store.thresholds_from(s), record_only=True), tc=q.get("tc", ["all"])[0], typical=typical)


@route("GET", r"/api/profile")
def api_profile(body, q):
    tc = (q.get("tc") or [""])[0]
    tc = "" if tc == "all" else tc
    days = int((q.get("days") or ["90"])[0] or 90)
    return skillprofile.build(tc, max(7, min(days, 3650)))


@route("GET", r"/api/phases")
def api_phases(body, q):
    """V10: accuracy by phase over the months, and where your errors land."""
    tc = (q.get("tc") or [""])[0]
    tc = "" if tc == "all" else tc
    days = max(7, min(int((q.get("days") or ["90"])[0] or 90), 3650))
    return {**phases.trends(tc, days), "heat": phases.heatmap(tc)}


@route("POST", r"/api/focus")
def api_focus(body, q):
    b = body or {}
    try:
        extra = {k: b[k] for k in ("color", "line", "line_name") if k in b}
        return skillprofile.set_focus(b.get("key", ""), b.get("tc", ""), extra)
    except ValueError as e:
        raise ApiError(400, str(e))


@route("POST", r"/api/focus/clear")
def api_focus_clear(body, q):
    return skillprofile.clear_focus()


@route("POST", r"/api/analyse-recent")
def api_analyse_recent(body, q):
    """Queue your most recent unanalysed games (you start it; never automatic)."""
    b = body or {}
    api.need_stockfish()
    n = max(1, min(int(b.get("n", 50)), 500))
    tc = b.get("tc", "")
    games = [g for g in store.list_games() if not g["analysed"] and g["player_color"] and (not tc or g.get("tc_category") == tc)]
    ids = [g["id"] for g in games[:n]]
    queued = 0
    for gid in ids:
        api.ANALYSER.enqueue(gid)
        queued += 1
    return {"queued": queued, "plies": sum(g.get("n_plies") or 0 for g in games[:n])}


@route("GET", r"/api/patterns")
def api_patterns(body, q):
    return patterns.build()


@route("GET", r"/api/weekly")
def api_weekly(body, q):
    return weekly.note(int((q.get("offset") or ["0"])[0] or 0))


@route("GET", r"/api/opponents")
def api_opponents(body, q):
    return {"opponents": opponents.list_opponents()}


@route("GET", r"/api/opponents/(?P<name>[^/]+)")
def api_opponent(body, q, name):
    try:
        return opponents.profile(name)
    except KeyError:
        raise ApiError(404, "no games against that player")


@route("GET", r"/api/plan")
def api_plan(body, q):
    return plan.build()
