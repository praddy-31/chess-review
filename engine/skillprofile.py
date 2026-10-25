"""
V6 Insights: where your points go, across all your games.

Two sources:
  - every game in the Library (PGN headers and clock comments): results,
    ratings, performance rating, tilt, sessions, clock and flagging - no engine;
  - analysed games: the six skill scores and endgame conversion.

Each number carries how many games it rests on. Periods compare the last N
days with the N days before. The weekly focus picks one of three suggested
leaks, stores a baseline, and measures the same number on the games since.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import chess

import store
from chess_analysis import time_control_parts, win_percent

CLK = re.compile(r"\[%clk\s+(\d+):(\d+):(\d+(?:\.\d+)?)\]")
TERM = re.compile(r'\[Termination\s+"([^"]*)"\]')
SESSION_GAP = 20 * 60          # games less than 20 minutes apart are one session
TILT_GAP = 15 * 60
_cache: dict = {}


def _dt(s: str) -> Optional[datetime]:
    """'YYYY-MM-DD HH:MM', or a date alone (pasted games often have no time: noon, so it sorts within its day)."""
    for fmt, n in (("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            t = datetime.strptime((s or "")[:n], fmt).replace(tzinfo=timezone.utc)
            return t if n == 16 else t.replace(hour=12)
        except (ValueError, TypeError):
            continue
    return None


def _score(outcome: str) -> Optional[float]:
    return {"win": 1.0, "draw": 0.5, "loss": 0.0}.get(outcome)


def _pct(xs: list) -> Optional[int]:
    return round(100 * sum(xs) / len(xs)) if xs else None


# ---------------------------------------------------------------------------
# all games, from the PGN
# ---------------------------------------------------------------------------

def _all_games() -> list[dict]:
    skip = not store.maia_counted()
    with store.db() as con:
        key = con.execute("SELECT COUNT(*), MAX(imported_at) FROM games").fetchone()
        key = (key[0], key[1], skip)
        if _cache.get("key") == key:
            return _cache["games"]
        rows = con.execute(store.LIST_SQL + " WHERE g.player_color IS NOT NULL ORDER BY g.played_at").fetchall()
        pgns = {r[0]: r[1] for r in con.execute("SELECT id, pgn FROM games WHERE player_color IS NOT NULL")}
    out = []
    for r in rows:
        g = store._game_row(r)
        if skip and g.get("source") == store.BOT_SOURCE:
            continue
        t = _dt(g.get("played_at") or "")
        if t is None or g["outcome"] == "unknown":
            continue
        pgn = pgns.get(g["id"], "")
        clocks = [int(h) * 3600 + int(m) * 60 + float(s) for h, m, s in CLK.findall(pgn)]
        white = g["me"] == "White"
        mine = clocks[0::2] if white else clocks[1::2]
        opp = clocks[1::2] if white else clocks[0::2]
        base, inc = time_control_parts(g.get("time_control") or "")
        term = (TERM.search(pgn) or [None, ""])[1] if TERM.search(pgn) else ""
        on_time = bool(re.search(r"on time|time forfeit|timeout", term, re.I))
        out.append({
            "id": g["id"], "t": t, "day": t.date().isoformat(), "has_time": len(g.get("played_at") or "") >= 16, "tc": g.get("tc_category") or "unknown",
            "outcome": g["outcome"], "s": _score(g["outcome"]), "me": g["me"],
            "elo": g.get("my_elo"), "opp_elo": g.get("opp_elo"), "opening": g.get("opening") or "",
            "base": base, "mine": mine, "opp": opp, "lost_on_time": on_time and g["outcome"] == "loss",
            "won_on_time": on_time and g["outcome"] == "win", "analysed": g["analysed"],
        })
    _cache.update(key=key, games=out)
    return out


def _filter(games: list[dict], tc: str = "", since: Optional[datetime] = None, until: Optional[datetime] = None) -> list[dict]:
    return [g for g in games if (not tc or g["tc"] == tc) and (since is None or g["t"] >= since) and (until is None or g["t"] < until)]


def performance(games: list[dict]) -> Optional[int]:
    """Performance rating: average opponent rating + 400 x (wins - losses) / games."""
    rated = [g for g in games if g["opp_elo"]]
    if len(rated) < 5:
        return None
    w = sum(g["outcome"] == "win" for g in rated)
    l = sum(g["outcome"] == "loss" for g in rated)
    return round(sum(g["opp_elo"] for g in rated) / len(rated) + 400 * (w - l) / len(rated))


def tilt(games: list[dict]) -> dict:
    """Your score in the next game, started within 15 minutes, by what came before."""
    overall = _pct([g["s"] for g in games])
    games = [g for g in games if g.get("has_time", True)]     # a date without a time can't tell what came just before
    after_win, after_loss, after_2loss = [], [], []
    for i in range(1, len(games)):
        g, p = games[i], games[i - 1]
        if (g["t"] - p["t"]).total_seconds() > TILT_GAP:
            continue
        if p["s"] == 1:
            after_win.append(g["s"])
        elif p["s"] == 0:
            after_loss.append(g["s"])
            if i > 1 and games[i - 2]["s"] == 0 and (p["t"] - games[i - 2]["t"]).total_seconds() <= TILT_GAP:
                after_2loss.append(g["s"])
    return {"overall": overall, "games": len(games),
            "after_win": {"score": _pct(after_win), "n": len(after_win)},
            "after_loss": {"score": _pct(after_loss), "n": len(after_loss)},
            "after_2loss": {"score": _pct(after_2loss), "n": len(after_2loss)}}


def sessions(games: list[dict]) -> dict:
    games = [g for g in games if g.get("has_time", True)]
    pos = []
    k = 0
    for i, g in enumerate(games):
        k = k + 1 if i and (g["t"] - games[i - 1]["t"]).total_seconds() < SESSION_GAP else 1
        pos.append(min(k, 5))
    rows = []
    for n in range(1, 6):
        xs = [g["s"] for g, p in zip(games, pos) if p == n]
        rows.append({"game": n, "score": _pct(xs), "n": len(xs)})
    late = [p >= 3 for p in pos]
    return {"rows": rows, "share_3plus": _pct(late), "n": len(games)}


def clock(games: list[dict]) -> Optional[dict]:
    timed = [g for g in games if g["base"] and g["tc"] != "daily" and len(g["mine"]) >= 10]
    if len(timed) < 10:
        return None
    at30 = [(g["mine"][29] - g["opp"][29]) for g in timed if len(g["mine"]) > 29 and len(g["opp"]) > 29]
    trouble = [g for g in timed if min(g["mine"]) < 0.1 * g["base"]]
    calm = [g for g in timed if g not in trouble]
    n_all = len([g for g in games if g["tc"] != "daily"])
    return {
        "games": len(timed),
        "at_move30": round(sorted(at30)[len(at30) // 2]) if at30 else None, "at_move30_n": len(at30),
        "lost_on_time": _pct([g["lost_on_time"] for g in games if g["tc"] != "daily"]),
        "won_on_time": _pct([g["won_on_time"] for g in games if g["tc"] != "daily"]),
        "trouble_share": _pct([g in trouble for g in timed]),
        "score_trouble": _pct([g["s"] for g in trouble]), "score_calm": _pct([g["s"] for g in calm]),
        "n_trouble": len(trouble), "n_all": n_all,
    }


def rating_series(games: list[dict]) -> dict:
    """Your rating per day (last game of the day) per time control, and monthly performance."""
    by_tc: dict = {}
    for g in games:
        if g["elo"]:
            by_tc.setdefault(g["tc"], {})[g["day"]] = g["elo"]
    series = {tc: [{"day": d, "elo": e} for d, e in sorted(v.items())] for tc, v in by_tc.items() if len(v) >= 3}
    months: dict = {}
    for g in games:
        months.setdefault((g["tc"], g["day"][:7]), []).append(g)
    perf = [{"tc": tc, "month": m, "perf": performance(gs), "games": len(gs)} for (tc, m), gs in sorted(months.items())]
    return {"series": series, "perf": [p for p in perf if p["perf"]]}


# ---------------------------------------------------------------------------
# analysed games: skills and endgames
# ---------------------------------------------------------------------------

def _reviews(tc: str = "", since=None, until=None) -> list[dict]:
    t = store.thresholds_from(store.get_settings())
    out = []
    for e in store.all_reviews(t, record_only=True):
        g = e["game"]
        ts = _dt(g.get("played_at") or "")
        if ts is None or not e["review"].moves:
            continue
        if tc and (g.get("tc_category") or "") != tc:
            continue
        if since and ts < since or until and ts >= until:
            continue
        out.append(e)
    return out


def _endgame_type(fen: str) -> str:
    b = chess.Board(fen)
    q = len(b.pieces(chess.QUEEN, True)) + len(b.pieces(chess.QUEEN, False))
    r = len(b.pieces(chess.ROOK, True)) + len(b.pieces(chess.ROOK, False))
    m = sum(len(b.pieces(p, c)) for p in (chess.KNIGHT, chess.BISHOP) for c in (True, False))
    if q:
        return "Queen"
    if r:
        return "Rook"
    if m:
        return "Minor piece"
    return "Pawn"


def skills(entries: list[dict], games_all: list[dict]) -> dict:
    """Six scores from 0 to 100, each with the number of games behind it."""
    opening, tactics, conv, defend, endg = [], [], [], [], []
    eg_rows: dict = {}
    for e in entries:
        rv, g = e["review"], e["game"]
        s = _score(g.get("outcome"))
        mine = rv.moves
        me = rv.player_color
        # Opening: out of the opening (your 12th move) at least equal (eval >= -0.5)
        m12 = next((m for m in mine if m.move_number >= 12), None)
        if m12 is not None:
            if m12.mate_after is not None:
                opening.append(1 if m12.mate_after > 0 else 0)
            elif m12.eval_after_cp is not None:
                opening.append(1 if m12.eval_after_cp >= -50 else 0)
        # Tactics: share of your tactical moves that were not mistakes or blunders
        tac = [m for m in mine if m.move_type == "Tactical"]
        if len(tac) >= 3:
            tactics.append(sum(m.severity not in ("Mistake", "Blunder") and not (m.missed_opportunity and m.pp_loss >= 10) for m in tac) / len(tac))
        # Converting / defending: reached 80%+ (or 20%-) win chance at some point
        wins = [m.win_after for m in mine]
        if s is not None and wins:
            if max(wins) >= 80:
                conv.append(1 if s == 1 else 0)
            if min(wins) <= 20:
                defend.append(1 if s >= 0.5 else 0)
        # Endgame: accuracy of your endgame moves, and conversion by endgame type
        em = [m for m in mine if m.move_type == "Endgame"]
        if len(em) >= 4:
            endg.append(sum(m.accuracy for m in em) / len(em) / 100)
        first_end = next((m.ply for m in sorted(mine + rv.opp_moves, key=lambda m: m.ply) if m.game_phase == "Endgame"), None)
        entry = next((p for p in rv.raw if p.ply == first_end), None)
        if entry is not None and s is not None:
            cp = entry.cp_before if entry.mate_before is None else (1000 if entry.mate_before > 0 else -1000)
            if cp is not None:
                cp_me = cp if entry.color == me else -cp
                k = _endgame_type(entry.fen_before)
                row = eg_rows.setdefault(k, {"type": k, "games": 0, "ahead": 0, "converted": 0, "behind": 0, "saved": 0})
                row["games"] += 1
                if cp_me >= 200:
                    row["ahead"] += 1; row["converted"] += s == 1
                elif cp_me <= -200:
                    row["behind"] += 1; row["saved"] += s >= 0.5
    timed = [g for g in games_all if g["base"] and g["tc"] != "daily" and len(g["mine"]) >= 10]
    time_ok = [0 if (g["lost_on_time"] or min(g["mine"]) < 0.1 * g["base"]) else 1 for g in timed]
    sc = lambda xs, mult=100: {"score": round(mult * sum(xs) / len(xs)) if xs else None, "n": len(xs)}
    out = {
        "Opening": {**sc(opening), "why": "Out of the opening (your 12th move) at least equal"},
        "Tactics": {**sc(tactics), "why": "Tactical moves without a mistake, blunder or big miss"},
        "Converting": {**sc(conv), "why": "Games you won after reaching 80%+ win chance"},
        "Defending": {**sc(defend), "why": "Games you saved after dropping to 20% or less"},
        "Endgame": {**sc(endg), "why": "Accuracy of your endgame moves"},
        "Time": {**sc(time_ok), "why": "Games without time trouble (under 10% of your clock) or a flag"},
    }
    for r in eg_rows.values():
        r["converted_pct"] = round(100 * r["converted"] / r["ahead"]) if r["ahead"] else None
        r["saved_pct"] = round(100 * r["saved"] / r["behind"]) if r["behind"] else None
    order = ["Rook", "Minor piece", "Pawn", "Queen"]
    return {"skills": out, "endgames": sorted(eg_rows.values(), key=lambda r: order.index(r["type"]))}


# ---------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------

def build(tc: str = "", days: int = 90) -> dict:
    now = datetime.now(timezone.utc)
    cut, cut0 = now - timedelta(days=days), now - timedelta(days=2 * days)
    allg = _filter(_all_games(), tc)
    cur, prev = _filter(allg, since=cut), _filter(allg, since=cut0, until=cut)
    rv_cur, rv_prev = _reviews(tc, since=cut), _reviews(tc, since=cut0, until=cut)
    sk_cur, sk_prev = skills(rv_cur, cur), skills(rv_prev, prev)
    for k, v in sk_cur["skills"].items():
        p = sk_prev["skills"][k]
        v["prev"] = p["score"]
        v["change"] = (v["score"] - p["score"]) if v["score"] is not None and p["score"] is not None and p["n"] >= 5 and v["n"] >= 5 else None

    def summary(gs, rvs):
        rated = [g for g in gs if g["elo"]]
        accs = [sum(m.accuracy for m in e["review"].moves) / len(e["review"].moves) for e in rvs]
        mv = [m for e in rvs for m in e["review"].moves]
        by_tc = {}
        for g in rated:
            by_tc.setdefault(g["tc"], []).append(g["elo"])
        return {"games": len(gs), "score": _pct([g["s"] for g in gs]), "perf": performance(gs),
                "ratings": {k: {"start": v[0], "end": v[-1], "games": len(v)} for k, v in by_tc.items() if k != "daily"},
                "opp_avg": round(sum(g["opp_elo"] for g in gs if g["opp_elo"]) / max(1, sum(1 for g in gs if g["opp_elo"]))) if gs else None,
                "analysed": len(rvs), "accuracy": round(sum(accs) / len(accs), 1) if accs else None,
                "blunders_pg": round(sum(m.severity == "Blunder" for m in mv) / len(rvs), 2) if rvs else None,
                "lost_on_time": _pct([g["lost_on_time"] for g in gs if g["tc"] != "daily"])}
    unanalysed = sum(1 for g in allg if not g["analysed"])
    beh, beh_scope = (cur, "period") if tilt(cur)["after_2loss"]["n"] >= 30 else (allg, "all")
    return {
        "tc": tc, "days": days, "tcs": sorted({g["tc"] for g in _all_games()}),
        "periods": {"current": summary(cur, rv_cur), "previous": summary(prev, rv_prev)},
        "rating": rating_series(allg),
        # habits need many games: the period when it has enough, else all your games
        "tilt": tilt(beh), "tilt_scope": beh_scope,
        "sessions": sessions(beh),
        "clock": clock(cur if len(cur) >= 100 else allg), "clock_scope": "period" if len(cur) >= 100 else "all",
        "skills": sk_cur["skills"], "endgames": sk_cur["endgames"],
        "analysed": {"period": len(rv_cur), "all": sum(1 for g in allg if g["analysed"]), "unanalysed": unanalysed,
                     "needed": max(0, 30 - len(rv_cur))},
        "focus": focus_status(),
        "suggestions": suggestions(allg, cur, sk_cur, tc),
    }


# ---------------------------------------------------------------------------
# weekly focus
# ---------------------------------------------------------------------------

def _metrics(games: list[dict], rvs: Optional[list[dict]] = None) -> dict:
    """The numbers a focus can be measured by, over a set of games."""
    tl = tilt(games)
    se = sessions(games)
    m = {"after_2loss_games": tl["after_2loss"]["n"], "after_2loss_score": tl["after_2loss"]["score"],
         "share_3plus": se["share_3plus"], "score": _pct([g["s"] for g in games]), "games": len(games),
         "lost_on_time": _pct([g["lost_on_time"] for g in games if g["tc"] != "daily"])}
    if rvs is not None:
        sk = skills(rvs, games)["skills"]
        m["converting"] = sk["Converting"]["score"]; m["converting_n"] = sk["Converting"]["n"]
        mv = [x for e in rvs for x in e["review"].moves]
        m["blunders_pg"] = round(sum(x.severity == "Blunder" for x in mv) / len(rvs), 2) if rvs else None
    return m


FOCUS = {
    "tilt": {"title": "Stop after two losses in a row", "metric": "after_2loss_games", "better": "lower",
             "how": "games per week you start within 15 minutes of two straight losses"},
    "sessions": {"title": "Play at most two games per session", "metric": "share_3plus", "better": "lower",
                 "how": "share of your games that are the 3rd or later in a session"},
    "time": {"title": "Keep a minute on your clock", "metric": "lost_on_time", "better": "lower",
             "how": "share of games you lose on time"},
    "converting": {"title": "Convert your winning positions", "metric": "converting", "better": "higher",
                   "how": "games won after reaching 80%+ win chance (analysed games)"},
    "blunders": {"title": "Blunder check before every move", "metric": "blunders_pg", "better": "lower",
                 "how": "blunders per analysed game"},
    "opening": {"title": "Fix your weakest opening line", "metric": "score", "better": "higher",
                "how": "your score in games through that line"},
}


def suggestions(allg: list[dict], cur: list[dict], sk: dict, tc: str) -> list[dict]:
    base = cur if tilt(cur)["after_2loss"]["n"] >= 30 else allg
    tl, se, ck = tilt(base), sessions(base), clock(base)
    out = []
    if tl["after_2loss"]["n"] >= 15 and tl["overall"] is not None and tl["after_2loss"]["score"] is not None \
            and tl["after_2loss"]["score"] <= tl["overall"] - 5:
        out.append({"key": "tilt", "gap": tl["overall"] - tl["after_2loss"]["score"],
                    "why": f"You score {tl['after_2loss']['score']}% in the game after two straight losses ({tl['after_2loss']['n']} games), against {tl['overall']}% overall."})
    rows = {r["game"]: r for r in se["rows"]}
    late = [r for k, r in rows.items() if k >= 3 and r["score"] is not None and r["n"] >= 20]
    if late and tl["overall"] is not None:
        worst = min(late, key=lambda r: r["score"])
        if worst["score"] <= tl["overall"] - 4:
            out.append({"key": "sessions", "gap": tl["overall"] - worst["score"],
                        "why": f"Game {worst['game']}{'+' if worst['game'] == 5 else ''} of a session scores {worst['score']}% ({worst['n']} games), against {tl['overall']}% overall."})
    if ck and ck["lost_on_time"] is not None and ck["won_on_time"] is not None and ck["lost_on_time"] >= ck["won_on_time"] + 2:
        out.append({"key": "time", "gap": ck["lost_on_time"] - ck["won_on_time"],
                    "why": f"You lose {ck['lost_on_time']}% of games on time and win {ck['won_on_time']}% on time."})
    conv = sk["skills"]["Converting"]
    if conv["n"] >= 8 and conv["score"] is not None and conv["score"] < 75:
        out.append({"key": "converting", "gap": 75 - conv["score"],
                    "why": f"You won {conv['score']}% of the {conv['n']} analysed games where you reached a winning position."})
    try:
        import repertoire
        for color in ("White", "Black"):
            sc = repertoire.scan(color, tc)
            w = next((x for x in sc["worst"] if x["n"] >= 15), None)
            if w and sc["overall"] is not None and w["score"] <= sc["overall"] - 15 and w["n"] >= 15:
                out.append({"key": "opening", "gap": sc["overall"] - w["score"], "color": color, "line": w["moves"],
                            "line_name": w["name"],
                            "why": f"As {color} you score {w['score']}% in the {w['name'].split(' ', 1)[1]} ({w['n']} games), against {sc['overall']}% overall."})
                break
    except Exception:
        pass
    out.sort(key=lambda s: -s["gap"])
    for s in out:
        f = FOCUS[s["key"]]
        s.update(title=f["title"] if s["key"] != "opening" else f"Fix the {s['line_name'].split(' ', 1)[1]} as {s['color']}",
                 how=f["how"], better=f["better"])
    return out[:3]


def _measure(spec: dict, since: datetime, until: Optional[datetime] = None) -> dict:
    gs = _filter(_all_games(), spec.get("tc", ""), since=since, until=until)
    if spec["key"] == "opening":
        line = spec.get("line") or []
        try:
            import repertoire
            with store.db() as con:
                ids = _games_through_line(con, line, spec.get("color"))
        except Exception:
            ids = set()
        gs = [g for g in gs if g["id"] in ids]
        return {"value": _pct([g["s"] for g in gs]), "games": len(gs)}
    rvs = _reviews(spec.get("tc", ""), since=since, until=until) if spec["key"] in ("converting", "blunders") else None
    m = _metrics(gs, rvs)
    v = m.get(FOCUS[spec["key"]]["metric"])
    if spec["key"] == "tilt" and v is not None:      # a count: per week, so 30 days before and a week since compare
        span = max(1.0, ((until or datetime.now(timezone.utc)) - since).total_seconds() / 86400)
        v = round(v * 7 / span, 1)
    return {"value": v, "games": len(gs)}


def _games_through_line(con, moves: list[str], color: Optional[str]) -> set:
    import repertoire
    b = chess.Board()
    for u in moves:
        b.push(chess.Move.from_uci(u))
    z = repertoire.zkey(b)
    rows = con.execute("SELECT g.id FROM op_moves m JOIN games g ON g.okey = m.g WHERE m.z_after = ? AND g.player_color = ?",
                       (z, color)).fetchall()
    return {r[0] for r in rows}


def set_focus(key: str, tc: str = "", extra: Optional[dict] = None) -> dict:
    if key not in FOCUS:
        raise ValueError("unknown focus")
    now = datetime.now(timezone.utc)
    spec = {"key": key, "tc": tc, "started": now.strftime("%Y-%m-%d %H:%M"), **(extra or {})}
    base = _measure(spec, now - timedelta(days=30), now)
    spec["baseline"] = base
    hist = json.loads(store.get_meta("focus_history") or "[]")
    old = json.loads(store.get_meta("focus") or "null")
    if old:
        old["result"] = _measure(old, _dt(old["started"]))
        old["ended"] = now.strftime("%Y-%m-%d %H:%M")
        hist.append(old)
    store.set_meta("focus_history", json.dumps(hist[-20:]))
    store.set_meta("focus", json.dumps(spec))
    return focus_status()


def clear_focus() -> dict:
    store.set_meta("focus", "null")
    return focus_status()


def focus_status() -> dict:
    spec = json.loads(store.get_meta("focus") or "null")
    hist = json.loads(store.get_meta("focus_history") or "[]")
    if not spec:
        return {"active": None, "history": hist[-5:]}
    start = _dt(spec["started"])
    now = datetime.now(timezone.utc)
    cur = _measure(spec, start)
    f = FOCUS[spec["key"]]
    days = (now - start).days
    title = f["title"] if spec["key"] != "opening" else f"Fix the {spec.get('line_name', 'line').split(' ', 1)[-1]} as {spec.get('color')}"
    return {"active": {**spec, "title": title, "how": f["how"], "better": f["better"], "now": cur, "days": days,
                       "week_done": days >= 7}, "history": hist[-5:]}
