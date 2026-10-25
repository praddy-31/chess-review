"""
Repeat-opponent prep (V8): people you have played more than once.

profile(name): your record against them (by colour), what they open with
against you and how you scored, the openings that worked for you, accuracy
on both sides in your analysed games, their rating over time, and a few
plain-words tips built from those numbers.
"""

from __future__ import annotations

from collections import Counter, defaultdict

import store

MIN_GAMES = 2


def _games() -> list[dict]:
    return [g for g in store.list_games(record_only=True) if g.get("me") and g.get("opponent")]


def _score(g: dict) -> float:
    return 1.0 if g["outcome"] == "win" else 0.5 if g["outcome"] == "draw" else 0.0


def _family(op: str) -> str:
    return (op or "").split(":")[0].split(",")[0].strip()


def list_opponents(limit: int = 30) -> list[dict]:
    by: dict = defaultdict(list)
    for g in _games():
        by[g["opponent"].lower()].append(g)
    out = []
    for key, gs in by.items():
        if len(gs) < MIN_GAMES:
            continue
        gs.sort(key=lambda g: g.get("played_at") or "")
        out.append({"name": gs[-1]["opponent"], "games": len(gs), "score": round(100 * sum(_score(g) for g in gs) / len(gs)),
                    "w": sum(g["outcome"] == "win" for g in gs), "d": sum(g["outcome"] == "draw" for g in gs),
                    "l": sum(g["outcome"] == "loss" for g in gs), "last": (gs[-1].get("played_at") or "")[:10],
                    "elo": gs[-1].get("opp_elo")})
    out.sort(key=lambda o: (o["games"], o["last"]), reverse=True)
    return out[:limit]


def profile(name: str) -> dict:
    gs = sorted((g for g in _games() if g["opponent"].lower() == name.lower()), key=lambda g: g.get("played_at") or "")
    if not gs:
        raise KeyError(name)
    res = lambda xs: {"games": len(xs), "w": sum(g["outcome"] == "win" for g in xs), "d": sum(g["outcome"] == "draw" for g in xs),
                      "l": sum(g["outcome"] == "loss" for g in xs), "score": round(100 * sum(_score(g) for g in xs) / len(xs)) if xs else None}
    as_white = [g for g in gs if g["me"] == "White"]
    as_black = [g for g in gs if g["me"] == "Black"]
    # what they open with: their first move from the PGN, and the opening family
    firsts = {}
    with store.db() as con:
        q = ",".join("?" * len(gs))
        for r in con.execute(f"SELECT id, pgn FROM games WHERE id IN ({q})", tuple(g["id"] for g in gs)):
            firsts[r["id"]] = _first_moves(r["pgn"])
    def openings(xs, their_side):
        by_move: dict = defaultdict(list)
        for g in xs:
            fm = firsts.get(g["id"], [])
            mv = fm[0] if their_side == "White" and fm else fm[1] if their_side == "Black" and len(fm) > 1 else None
            if mv:
                by_move[mv].append(g)
        rows = []
        for mv, v in by_move.items():
            fams: dict = defaultdict(list)
            for g in v:
                fams[_family(g.get("opening")) or "?"].append(g)
            rows.append({"move": mv, **res(v), "openings": sorted(({"opening": k, **res(x)} for k, x in fams.items()), key=lambda r: -r["games"])[:4]})
        return sorted(rows, key=lambda r: -r["games"])[:5]
    their_white = openings(as_black, "White")     # you were Black: they had White
    their_black = openings(as_white, "Black")
    fam: dict = defaultdict(list)
    for g in gs:
        if g.get("opening"):
            fam[(g["me"], _family(g["opening"]))].append(g)
    worked = sorted(({"color": k[0], "opening": k[1], **res(v)} for k, v in fam.items() if len(v) >= 2),
                    key=lambda r: (-(r["score"] or 0), -r["games"]))
    an = [g for g in gs if g.get("analysed")]
    acc = {"games": len(an), "you": round(sum(g["accuracy"] for g in an) / len(an), 1) if an else None,
           "them": round(sum(g["opp_accuracy"] for g in an if g.get("opp_accuracy") is not None) / max(1, sum(1 for g in an if g.get("opp_accuracy") is not None)), 1) if an else None,
           "your_blunders": round(sum(g.get("blunders") or 0 for g in an) / len(an), 1) if an else None}
    tips = []
    for side, rows in (("White", their_white), ("Black", their_black)):
        if rows and rows[0]["games"] >= 2:
            r = rows[0]
            n_all = sum(x["games"] for x in rows)
            pre = "1." if side == "White" else "1..."
            t = f"With {side} they play {pre}{r['move']} in {r['games']} of your {n_all} games; you scored {r['score']}%."
            op = r["openings"][0] if r["openings"] else None
            if op and op["opening"] != "?" and op["games"] >= 2:
                t += f" Most often it became the {op['opening']} ({op['games']} games, {op['score']}%)."
            tips.append(t)
    good = [w for w in worked if (w["score"] or 0) >= 60]
    bad = [w for w in worked if (w["score"] or 0) <= 40]
    if good:
        tips.append(f"Your best results: as {good[0]['color']} in the {good[0]['opening']} ({good[0]['w']} won of {good[0]['games']}).")
    if bad:
        tips.append(f"Your worst: as {bad[0]['color']} in the {bad[0]['opening']} ({bad[0]['score']}% in {bad[0]['games']} games).")
    if acc["you"] is not None and acc["them"] is not None and acc["games"] >= 2:
        tips.append(f"In {acc['games']} analysed games your accuracy was {acc['you']} against their {acc['them']}.")
    elos = [(g.get("played_at") or "")[:10] for g in gs]
    return {"name": gs[-1]["opponent"], "total": res(gs), "as_white": res(as_white), "as_black": res(as_black),
            "their_white": their_white, "their_black": their_black, "worked": worked[:6], "accuracy": acc, "tips": tips,
            "ratings": [{"date": (g.get("played_at") or "")[:10], "elo": g.get("opp_elo")} for g in gs if g.get("opp_elo")],
            "games": [{"id": g["id"], "date": (g.get("played_at") or "")[:10], "me": g["me"], "outcome": g["outcome"],
                       "opening": g.get("opening"), "tc": g.get("tc_category"), "accuracy": g.get("accuracy")} for g in reversed(gs)][:15],
            "first": elos[0] if elos else None}


def _first_moves(pgn: str) -> list[str]:
    import repertoire
    return repertoire._movetext(pgn)[:2]
