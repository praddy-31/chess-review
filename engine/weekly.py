"""
Weekly note (V7): one Markdown note per week, to copy into Obsidian.

Copy only - the app never writes into your vault. Monday to Sunday, local
time. Everything in it comes from your games and the app's own numbers.
"""

from __future__ import annotations

import datetime as _dt
from collections import Counter
from typing import Optional

import store


def week_bounds(offset: int = 0, today: Optional[_dt.date] = None) -> tuple[_dt.date, _dt.date]:
    """Monday and Sunday of this week (offset 0) or an earlier one (offset -1, -2 ...)."""
    t = today or _dt.date.today()
    mon = t - _dt.timedelta(days=t.weekday()) + _dt.timedelta(weeks=offset)
    return mon, mon + _dt.timedelta(days=6)


def note(offset: int = 0) -> dict:
    mon, sun = week_bounds(offset)
    a, b = mon.isoformat(), (sun + _dt.timedelta(days=1)).isoformat()
    games = [g for g in store.list_games(record_only=True) if g.get("me") and a <= (g.get("played_at") or "")[:10] < b]
    games.sort(key=lambda g: g.get("played_at") or "")
    iso = mon.isocalendar()
    title = f"Chess week {iso[0]}-W{iso[1]:02d}"
    span = f"{mon.strftime('%b')} {mon.day} – {sun.strftime('%b')} {sun.day}, {sun.year}"
    lines = [f"# {title}", "", f"*{span}*", ""]
    if not games:
        lines += ["No games this week."]
        return {"title": title, "span": span, "markdown": "\n".join(lines) + "\n", "games": 0}
    res = Counter(g["outcome"] for g in games)
    lines.append(f"- **Games:** {len(games)} ({res['win']} won, {res['draw']} drawn, {res['loss']} lost)")
    by_tc: dict = {}
    for g in games:
        if g.get("my_elo") and g.get("tc_category") not in (None, "unknown"):
            by_tc.setdefault(g["tc_category"], []).append(g["my_elo"])
    for tc, elos in sorted(by_tc.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"- **{tc.capitalize()} rating:** {elos[0]} → {elos[-1]} ({elos[-1] - elos[0]:+d}) over {len(elos)} game{'s' if len(elos) != 1 else ''}")
    an = [g for g in games if g.get("analysed") and g.get("accuracy") is not None]
    if an:
        acc = sum(g["accuracy"] for g in an) / len(an)
        bl = sum(g.get("blunders") or 0 for g in an)
        lines.append(f"- **Accuracy:** {acc:.1f} average over {len(an)} analysed game{'s' if len(an) != 1 else ''}, "
                     f"{bl / len(an):.1f} blunders a game")
        best = max(an, key=lambda g: g["accuracy"])
        lines.append(f"- **Best game:** {best['accuracy']:.1f} vs {best.get('opponent') or '?'} ({(best.get('played_at') or '')[:10]}, {best['outcome']})")
        worst = _worst_move(an)
        if worst:
            lines.append(f"- **Costliest move:** {worst}")
        bril = sum(g.get("brilliant") or 0 for g in an)
        great = sum(g.get("great") or 0 for g in an)
        if bril or great:
            lines.append(f"- **Highlights:** {bril} brilliant, {great} great move{'s' if great != 1 else ''}")
    tagged = Counter(t for g in games for t in g.get("tags") or [])
    if tagged:
        lines.append("- **Tags:** " + ", ".join(f"{t} ×{n}" for t, n in tagged.most_common(6)))
    lines += _focus(), _study(a, b), _openings(games)
    lines = [x for x in lines if x]
    notes = _game_notes([g["id"] for g in games])
    if notes:
        lines += ["", "## Your notes"] + notes
    return {"title": title, "span": span, "markdown": "\n".join(lines) + "\n", "games": len(games)}


def _worst_move(games: list[dict]) -> Optional[str]:
    th = store.thresholds_from(store.get_settings())
    worst = None
    for g in games:
        rv = store.load_review(g["id"], th)
        if not rv:
            continue
        for m in rv.moves:
            if m.severity == "Blunder" and (worst is None or m.pp_loss > worst[0]):
                worst = (m.pp_loss, f"{m.label}{m.played_san} vs {g.get('opponent') or '?'} ({m.pp_loss:.0f} points of win chance; {m.best_san} was best)")
    return worst[1] if worst else None


def _focus() -> str:
    try:
        import skillprofile
        f = skillprofile.focus_status().get("active")
    except Exception:
        return ""
    if not f:
        return ""
    now = f.get("now") or {}
    v = now.get("value")
    if v is None:
        return f"- **Weekly focus:** {f['title']} (no games to measure yet)"
    return f"- **Weekly focus:** {f['title']}: now {v} ({f['how']}; {now.get('games', 0)} games since you started)"


def _study(a: str, b: str) -> str:
    try:
        with store.db() as con:
            rows = con.execute("SELECT kind, result FROM study_log WHERE day >= ? AND day < ?", (a, b)).fetchall()
    except Exception:
        return ""
    if not rows:
        return ""
    learn = sum(1 for r in rows if r["kind"] == "learn")
    rev = [r for r in rows if r["kind"] in ("step", "review")]
    clean = sum(1 for r in rev if r["result"] == "clean")
    return f"- **Opening study:** {learn} new line{'s' if learn != 1 else ''}, {len(rev)} reviews ({round(100 * clean / len(rev)) if rev else 0}% clean)"


def _openings(games: list[dict]) -> str:
    c = Counter((g.get("opening") or "").split(":")[0] for g in games if g.get("opening"))
    if not c:
        return ""
    return "- **Openings played:** " + ", ".join(f"{o} ×{n}" for o, n in c.most_common(4))


def _game_notes(ids: list[str]) -> list[str]:
    if not ids:
        return []
    q = ",".join("?" * len(ids))
    with store.db() as con:
        rows = con.execute(f"SELECT n.game_id, n.ply, n.text, g.white, g.black, g.player_color FROM game_notes n JOIN games g ON g.id = n.game_id "
                           f"WHERE n.game_id IN ({q}) ORDER BY g.played_at, n.ply", tuple(ids)).fetchall()
    out = []
    for r in rows:
        opp = r["black"] if r["player_color"] == "White" else r["white"]
        where = "game" if r["ply"] == 0 else f"move {(r['ply'] + 1) // 2}"
        out.append(f"- vs {opp}, {where}: {r['text']}")
    return out
