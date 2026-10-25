"""
Ask the coach (V7): "why not this move?" for any position.

Stockfish looks at your candidate and at the best move (depth 18, a few
seconds), the motif detector reads both lines, and that becomes a short list
of facts. If Ollama runs on this Mac and you picked a model in Settings, the
model turns the facts into a few plain sentences - it is told to use only
those facts, and moves it mentions that the engine didn't check are flagged.
Without Ollama you get the facts as they are.

Ollama is local (http://127.0.0.1:11434); nothing leaves the Mac.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Optional

import chess
import chess.engine

import store
from chess_analysis import win_percent

OLLAMA = "http://127.0.0.1:11434"
DEPTH = 18
SECONDS = 4.0


def ollama_status() -> dict:
    """Is Ollama running here, and which models does it have?"""
    try:
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=1.5) as r:
            data = json.loads(r.read().decode("utf-8"))
        models = sorted((m.get("name") for m in data.get("models", []) if m.get("name")), key=str.lower)
        return {"running": True, "models": models}
    except Exception:
        return {"running": False, "models": []}


def _engine():
    import engines
    path = engines._which("stockfish", store.get_settings().get("stockfish_path", ""))
    if not path:
        raise RuntimeError("Stockfish isn't installed (see Setup)")
    eng = chess.engine.SimpleEngine.popen_uci(path)
    try:
        eng.configure({"Threads": max(1, int(store.get_settings().get("threads", 2) or 2)), "Hash": 128})
    except Exception:
        pass
    return eng


def _score(info, color) -> tuple[Optional[int], Optional[int]]:
    s = info["score"].pov(color)
    return s.score(), s.mate()


def _fmt(cp, mate) -> str:
    if mate is not None:
        return f"mate in {abs(mate)} for {'you' if mate > 0 else 'them'}"
    v = round((cp or 0) / 100, 1)
    return f"{'+' if v > 0 else '−' if v < 0 else ''}{abs(v):.1f}"


def _san_line(board: chess.Board, pv: list, n: int = 8) -> list[str]:
    b = board.copy()
    out = []
    for mv in pv[:n]:
        lab = f"{b.fullmove_number}{'.' if b.turn else '...'}"
        out.append(lab + b.san(mv) if (b.turn or not out) else b.san(mv))
        b.push(mv)
    return out


THREAT_CP = 120          # a "threat" gains at least this much if it were that side's move


def _threat(eng, board: chess.Board, side: bool) -> Optional[dict]:
    """What `side` would play if it were its move now (a null move), when that gains a lot."""
    if board.is_check():
        return None
    b = board.copy(stack=False)
    b.turn = side
    b.ep_square = None
    if not any(True for _ in b.legal_moves) or b.is_check():
        return None
    try:
        now = eng.analyse(board, chess.engine.Limit(depth=12, time=1.0))
        pas = eng.analyse(b, chess.engine.Limit(depth=12, time=1.0))
    except Exception:
        return None
    n_cp, n_m = _score(now, side)
    p_cp, p_m = _score(pas, side)
    gain = (100000 if p_m and p_m > 0 else (p_cp or 0)) - (100000 if n_m and n_m > 0 else (n_cp or 0))
    if gain < THREAT_CP or not pas.get("pv"):
        return None
    from motifs import analyse_line
    mv = pas["pv"][0]
    al = analyse_line(b, _sans_from(b, pas["pv"]), ben_cp=p_cp, ben_mate=p_m if (p_m or 0) > 0 else None)
    return {"uci": mv.uci(), "san": b.san(mv), "phrase": al.get("phrase"), "mate": p_m if (p_m or 0) > 0 else None}


def _maia(board: chess.Board, cand: chess.Move) -> Optional[dict]:
    """How likely players at your rating are to play the candidate, and their favourite move (Maia, when installed)."""
    try:
        import engines
        from chess_analysis import MaiaEngine
        s = store.get_settings()
        lc0, w = engines.pick_maia(s)
        if not lc0:
            return None
        m = MaiaEngine(lc0, w, timeout=20)
        try:
            pol = m.policy(board)
        finally:
            m.quit()
    except Exception:
        return None
    if not pol:
        return None
    top = max(pol, key=pol.get)
    band = w.split("maia-")[-1].split(".")[0] if "maia-" in w else str(store.my_rating(settings=s))
    return {"band": band, "p_cand": round(100 * pol.get(cand.uci(), 0)), "top": board.san(chess.Move.from_uci(top)),
            "top_uci": top, "p_top": round(100 * pol[top])}


def facts(fen: str, uci: str, game: Optional[dict] = None) -> dict:
    """Why (not) this move: the engine's verdict plus what the position is like, the threats both ways, what the
    move changes compared with the best one, the plan behind the best line, and (with Maia) what players at your
    level play. Returned as sections for the screen and a flat list of facts for a language model."""
    import features as F
    from chess_analysis import openings, _epd
    from motifs import analyse_line
    board = chess.Board(fen)
    cand = chess.Move.from_uci(uci)
    if cand not in board.legal_moves:
        raise ValueError("that move isn't legal here")
    me = board.turn
    cand_san = board.san(cand)
    label = f"{board.fullmove_number}{'.' if me else '...'}"
    eng = _engine()
    try:
        top = eng.analyse(board, chess.engine.Limit(depth=DEPTH, time=SECONDS), multipv=3)
        top = top if isinstance(top, list) else [top]
        best = top[0]
        best_mv = best["pv"][0]
        alt = next((i for i in top if i["pv"][0] == cand), None)
        if alt is None:
            alt = eng.analyse(board, chess.engine.Limit(depth=DEPTH, time=SECONDS), root_moves=[cand])
        threat_now = _threat(eng, board, not me)                    # what they threaten before your move
        b_after = board.copy(); b_after.push(cand)
        my_threat = _threat(eng, b_after, me) if not b_after.is_game_over() else None   # what your move threatens
    finally:
        eng.quit()
    bcp, bm = _score(best, me)
    ccp, cm = _score(alt, me)
    wb, wc = win_percent(bcp, bm), win_percent(ccp, cm)
    gap = max(0.0, wb - wc) if cand != best_mv else 0.0
    verdict = ("the best move" if cand == best_mv else "about as good as the best" if gap < 2 else "a little worse than the best" if gap < 5
               else "an inaccuracy" if gap < 10 else "a mistake" if gap < 20 else "a blunder")
    best_san = board.san(best_mv)
    ref_pv = alt["pv"][1:]
    ref_line = analyse_line(b_after, _sans_from(b_after, ref_pv), ben_cp=(-ccp if ccp is not None else None)) if ref_pv else {"motif": None}
    best_line = analyse_line(board, _sans_from(board, best["pv"]), ben_cp=bcp, ben_mate=bm if (bm or 0) > 0 else None) if cand != best_mv else {"motif": None}
    sections = []

    # 1. the verdict
    v = [f"{label}{cand_san} is {verdict}: {_fmt(ccp, cm)}{'' if cm is not None else ' for you'} ({wc:.0f}% win chance)."]
    if cand != best_mv:
        v.append(f"The best move is {label}{best_san} at {_fmt(bcp, bm)} ({wb:.0f}%), {gap:.0f} points of win chance more.")
        if best_line.get("mate_in") == 1:
            v.append(f"{label}{best_san} is checkmate at once.")
        elif best_line.get("phrase"):
            v.append(f"{best_san} {best_line['phrase']}.")
    if ref_pv:
        reply = b_after.san(ref_pv[0])
        what = f", which {ref_line['phrase']}" if ref_line.get("phrase") else ""
        v.append(f"After {cand_san}, their best reply is {reply}{what}. Line: {' '.join(_san_line(b_after, ref_pv, 6))}.")
    others = [i for i in top[1:] if i["pv"][0] not in (cand, best_mv)]
    if others:
        ocp, om = _score(others[0], me)
        v.append(f"Another good option: {label}{board.san(others[0]['pv'][0])} at {_fmt(ocp, om)}.")
    sections.append({"key": "verdict", "title": "Verdict", "lines": v})

    # 2. the position before the move
    fb = F.features(board, me)
    name = None
    op = openings()
    hit = op.get(_epd(fen))
    if hit:
        name = hit[1]
    pos = [f"{fb['phase'].capitalize()}{f', {name}' if name else ''}; {'White' if me else 'Black'} (you) to move."] + F.describe(fb)[:6]
    sections.append({"key": "position", "title": "The position", "lines": pos})

    # 3. threats both ways
    th = []
    if threat_now:
        what = threat_now["phrase"] or ("mates" if threat_now["mate"] else "wins material")
        th.append(f"They threaten {threat_now['san']}, which {what}.")
        if ref_pv and ref_pv[0].uci() == threat_now["uci"]:
            th.append(f"{cand_san} doesn't stop it: {threat_now['san']} is still their best reply.")
        else:
            th.append(f"{cand_san} deals with that threat.")
    else:
        th.append("They have no big threat right now.")
    if my_threat:
        th.append(f"{cand_san} threatens {my_threat['san']}" + (f", which {my_threat['phrase']}" if my_threat["phrase"] else "") + ".")
    sections.append({"key": "threats", "title": "Threats", "lines": th})

    # 4. what the move changes, against the best move
    if cand != best_mv:
        ab = board.copy(); ab.push(best_mv)
        ch = F.compare(F.features(b_after, me), F.features(ab, me), cand_san, best_san)
        sections.append({"key": "changes", "title": f"{cand_san} vs {best_san}", "lines": ch or [f"The difference is in the moves that follow, not the position right after: see the plan."]})

    # 5. the plan behind the best line
    pl = F.plan(board, best["pv"], me)
    fe = board.copy()
    for mv in best["pv"][:10]:
        if mv not in fe.legal_moves:
            break
        fe.push(mv)
    end = F.describe(F.features(fe, me))[:2]
    sections.append({"key": "plan", "title": "The plan" if cand != best_mv else f"The plan after {cand_san}",
                     "lines": (pl or ["The engine's line is quiet: small improvements, no forcing moves."])
                     + [f"Best line: {' '.join(_san_line(board, best['pv'], 8))}."] + [f"Where it ends: {e[0].lower() + e[1:]}" for e in end[:1]]})

    # 6. at your level (Maia), and your game
    lvl = []
    mi = _maia(board, cand)
    if mi:
        lvl.append(f"Players around {mi['band']} play {mi['top']} here {mi['p_top']}% of the time; {cand_san} {mi['p_cand']}%.")
    if game and game.get("played_san") and game["played_san"] != cand_san:
        lvl.append(f"In your game you played {game['played_san']} here.")
    if lvl:
        sections.append({"key": "level", "title": "At your level", "lines": lvl})

    facts_flat = [f"Position: {('White' if me else 'Black')} to move (you). Candidate: {label}{cand_san}."]
    for sct in sections:
        facts_flat += [f"[{sct['title']}] {ln}" for ln in sct["lines"]]
    moves = set()
    for line in (best["pv"], alt["pv"]):
        b = board.copy()
        for mv in line[:10]:
            moves.add(b.san(mv).rstrip("+#")); b.push(mv)
    for o in others:
        moves.add(board.san(o["pv"][0]).rstrip("+#"))
    return {"facts": facts_flat, "sections": sections, "verdict": verdict, "gap": round(gap, 1), "candidate": cand_san, "best": best_san,
            "best_uci": best_mv.uci(), "reply_uci": ref_pv[0].uci() if ref_pv else None, "moves": sorted(moves),
            "threat_uci": threat_now["uci"] if threat_now else None, "fen": fen, "uci": uci}


def _sans_from(board: chess.Board, pv: list) -> list[str]:
    b = board.copy(); out = []
    for mv in pv[:12]:
        out.append(b.san(mv)); b.push(mv)
    return out


def _sans_after(board: chess.Board, pv: list) -> list[str]:
    return _sans_from(board, pv)[1:]


_SAN = re.compile(r"\b(?:[KQRBN][a-h]?[1-8]?x?[a-h][1-8]|[a-h]x[a-h][1-8]|[a-h][1-8]|O-O(?:-O)?)(?:=[QRBN])?[+#]?")


SYSTEM = ("You are a friendly chess coach talking to a club player about one position. Use ONLY the facts you are given: "
          "do not invent moves, evaluations, plans or threats that are not in them, and name moves exactly as written. "
          "Explain the ideas in plain words - why a move is good or bad, what it changes, what the plan is - rather than "
          "repeating numbers. Keep answers to 3-6 short sentences.")


def _ollama_chat(model: str, messages: list) -> tuple[Optional[str], Optional[str]]:
    body = json.dumps({"model": model, "messages": messages, "stream": False, "think": False,
                       "options": {"temperature": 0.3, "num_predict": 350}}).encode("utf-8")
    req = urllib.request.Request(OLLAMA + "/api/chat", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            text = json.loads(r.read().decode("utf-8")).get("message", {}).get("content", "")
    except urllib.error.HTTPError as e:
        return None, f"Ollama answered HTTP {e.code} (is the model '{model}' pulled?)"
    except Exception as e:
        return None, f"Ollama isn't reachable ({e.__class__.__name__}); showing the engine facts."
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip(), None


def _check(text: str, facts_list: list) -> Optional[str]:
    in_facts = {m.rstrip("+#") for m in _SAN.findall(" ".join(facts_list))}       # only moves the facts actually name
    stray = sorted({m.rstrip("+#") for m in _SAN.findall(text)} - in_facts - {"O-O", "O-O-O"})
    stray = [m for m in stray if len(m) > 2 or not re.fullmatch(r"[a-h][1-8]", m)]   # bare squares are fine
    if stray:
        return f"The model mentioned {', '.join(stray[:4])}, which the engine didn't check; trust the facts above."
    return None


def _model() -> Optional[str]:
    s = store.get_settings()
    m = (s.get("coach_model") or "").strip()
    return m if s.get("coach_ollama") and m else None


def explain(fen: str, uci: str, question: str = "", game: Optional[dict] = None) -> dict:
    """Facts always; a written answer when Ollama is set up."""
    f = facts(fen, uci, game)
    f["text"], f["model"], f["note"] = None, None, None
    model = _model()
    if not model:
        return f
    q = question.strip() or f"Why is {f['candidate']} {'good' if f['verdict'] == 'the best move' else 'good or bad'} here, and what is the idea?"
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": "Facts:\n- " + "\n- ".join(f["facts"]) + f"\n\nQuestion: {q}"}]
    text, err = _ollama_chat(model, msgs)
    if err:
        f["note"] = err
        return f
    f["text"], f["model"] = text, model
    f["note"] = _check(text, f["facts"])
    return f


def chat(facts_list: list, history: list, question: str) -> dict:
    """A follow-up question about the same position: the facts stay, the conversation so far is kept."""
    model = _model()
    if not model:
        return {"text": None, "note": "Follow-up questions in your own words need Ollama (Settings > Coach). The sections above have the facts."}
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": "Facts:\n- " + "\n- ".join(facts_list) + "\n\nI'll ask questions about this position."},
            {"role": "assistant", "content": "Go ahead."}]
    for h in history[-6:]:
        msgs += [{"role": "user", "content": h.get("q", "")}, {"role": "assistant", "content": h.get("a", "")}]
    msgs.append({"role": "user", "content": question.strip()})
    text, err = _ollama_chat(model, msgs)
    if err:
        return {"text": None, "note": err}
    return {"text": text, "model": model, "note": _check(text, facts_list)}
