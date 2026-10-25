"""
Self-test for the engine process. Needs Stockfish (on PATH, in Homebrew's
folder, or STOCKFISH=path). Uses a throwaway data folder, never your real one.

    python3 selftest.py

1. the analysis core (mates, stalemate, formats, links, re-classification)
2. the store (ids, dedup, settings, threshold recompute)
3. the HTTP API end to end (token, import, analyse queue, review, export, insights)
"""
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
TMP = tempfile.mkdtemp(prefix="chess-review-test-")
os.environ["CHESS_REVIEW_DATA"] = TMP
os.environ["CHESS_REVIEW_PALETTE_DIR"] = os.path.join(TMP, "palette")   # never read the real ~/.config/palette

import chess.pgn  # noqa: E402

import engines  # noqa: E402
import store    # noqa: E402
from chess_analysis import (  # noqa: E402
    CHESSCOM_RE, LICHESS_ID_RE, LICHESS_RESERVED, Thresholds, analyze_game, classify_review,
    load_pgn_text, parse_games, win_percent,
)
from export_md import game_markdown  # noqa: E402
from payload import review_payload   # noqa: E402

SF = os.environ.get("STOCKFISH") or engines._which("stockfish")
failures = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def run(pgn, color, **kw):
    g = parse_games(load_pgn_text(pgn))[0]
    return analyze_game(g, SF, color, 1200, Thresholds(), depth=10, threads=1, **kw)


if not SF:
    print("Stockfish not found (brew install stockfish)"); sys.exit(2)

SCHOLAR = "1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# 1-0"

print("1. analysis core")
check(abs(win_percent(0, None) - 50) < 1e-9 and win_percent(None, 3) == 100, "win% mapping")
rv = run(SCHOLAR, "White")
check(rv.moves[-1].severity == "Best" and rv.moves[-1].phase == "Attack", "delivering mate is Best / Attack")
rv = run(SCHOLAR, "Black")
check(rv.moves[-1].severity == "Blunder", "allowing mate in 1 is a Blunder")
rv = run("1. f3 e5 2. g4 Qh4# 0-1", "White")
check(rv.moves[-1].eval_after_white == "#-1", "Fool's mate eval")
rv = run("1. e3 a5 2. Qh5 Ra6 3. Qxa5 h5 4. h4 Rah6 5. Qxc7 f6 6. Qxd7+ Kf7 7. Qxb7 Qd3 8. Qxb8 Qh7 9. Qxc8 Kg6 10. Qe6 1/2-1/2", "White")
check(rv.moves[-1].severity == "Blunder" and rv.moves[-1].missed_opportunity, "stalemating from +15: Blunder + missed")
check(len(parse_games("1. e4 e5 2. Nf3 Nc6")) == 1, "bare move list")
m = LICHESS_ID_RE.search("https://lichess.org/abcd1234wxyz/black")
check(m and m.group(1) == "abcd1234", "lichess link id")
check(CHESSCOM_RE.search("https://www.chess.com/game/live/144885079870").group(1) == "144885079870", "chess.com link id")
# a simulated lc0, run with this same Python (it needs python-chess)
FAKE_LC0 = os.path.join(TMP, "fake_lc0")
with open(FAKE_LC0, "w") as f:
    f.write(f'#!/bin/sh\nexec "{sys.executable}" "{os.path.join(HERE, "tests", "fake_lc0.py")}" "$@"\n')
os.chmod(FAKE_LC0, 0o755)
os.environ["FAKE_LC0_MODE"] = "die"
mrv = run("1. e4 e5 2. Nf3 Nc6", "White", maia_engine_path=FAKE_LC0, maia_weights_path=FAKE_LC0)
check(not mrv.maia_used and mrv.maia_error, "Maia: a dead lc0 still gives a review, with the error noted")
os.environ["FAKE_LC0_MODE"] = "ok"
mrv = run("1. e4 e5 2. Nf3 Nc6", "White", maia_engine_path=FAKE_LC0, maia_weights_path=FAKE_LC0)
check(mrv.maia_used and all(m.maia_prob_best is not None for m in mrv.moves), "Maia: per-move probabilities from lc0")
_w1200 = os.path.join(TMP, "maia-1200.pb.gz"); open(_w1200, "w").close()
mrv = run("1. e4 e5 2. Nf3 Nc6", "White", maia_engine_path=FAKE_LC0, maia_weights_path=_w1200)
check(mrv.maia_band == 1200 and store.review_from_json(store.review_to_json(mrv), Thresholds()).maia_band == 1200, "Maia: the review records which net it used (1200), and keeps it when saved")
strict = classify_review(rv, Thresholds(inaccuracy_pp=1.0))
check(len(strict.moves) == len(rv.moves), "re-classification without the engine")

print("1b. both sides, Book / Great / Brilliant")
import dataclasses  # noqa: E402
import chess  # noqa: E402
from chess_analysis import PlyData, classify_ply, time_control_category  # noqa: E402
rv = run("1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 6. Re1 b5 7. Bb3 d6", "White")
check(len(rv.moves) + len(rv.opp_moves) == len(rv.raw) and rv.opp_moves[0].color == "Black", "both sides' moves are classified")
check(all(m.severity == "Book" for m in rv.moves[:4]) and all(m.severity == "Book" for m in rv.opp_moves[:4]), "Ruy Lopez main line is Book for both sides")
check(all(p.second_cp is not None or p.second_mate is not None for p in rv.raw if p.n_legal and p.n_legal > 1), "second-best move evaluated (MultiPV 2)")
check(rv.analysis_version == 2, "analysis version recorded")
from sacrifice import offered  # noqa: E402
GG = "rnbq1rk1/ppp2ppp/3b1n2/3p4/3P4/3B1N2/PPP2PPP/RNBQ1RK1 w - - 0 7"
check(offered(chess.Board(GG), chess.Move.from_uci("d3h7")) == 2, "Bxh7+ offers a bishop for a pawn: 2 points")
check(offered(chess.Board(GG), chess.Move.from_uci("c2c3")) == 0, "a quiet move offers nothing")
# keirofearth 9...Nc6: developing into an exchange that comes out level is no sacrifice
KF = "r1bqr1k1/ppp2ppp/3b4/8/4n3/2N2N2/PPPP1PPP/R1BQ1RK1 w - - 0 1"
check(offered(chess.Board(KF), chess.Move.from_uci("c3e4")) == 0, "a fair trade (Nxe4 Rxe4) is not a sacrifice")
from sacrifice import sacrifice  # noqa: E402
check(sacrifice(GG, "d3h7") == (2, 2), "grading v4: Bxh7+ is 2 points down after the captures, and avoidable")
# 12.e5 vs Akashsaxena87: the knight on c5 'hangs' but dxc5 exf6 wins it back
check(sacrifice("r1bqk2r/2p2pb1/p1nppn1p/1pN3p1/4P3/1P1P1NP1/PBP2PBP/R2Q1RK1 w kq - 0 12", "e4e5")[0] < 2,
      "a counter-threat that wins the material back is no sacrifice")
# 33.Qxe5 vs Shreyash356: taking the checking queen, the knight on d2 was lost anyway
check(sacrifice("4r1k1/p1Q2p2/1pb3p1/2ppq3/8/3P1PKB/PPPNr3/R6R w - - 14 33", "c7e5")[1] < 2,
      "escaping check with a piece lost anyway is no sacrifice")
check(sacrifice("r1q2rk1/pp3pp1/2Nb3p/8/2P3n1/1P1P2P1/PB3KBP/R2QR3 w - - 1 19", "f2g1")[1] < 2,
      "a king move out of check that leaves a lost knight is no sacrifice")
check(time_control_category("1/86400") == "daily" and time_control_category("180+2") == "blitz", "daily games recognised")
base = PlyData(ply=13, move_number=7, color="White", played_san="c3", played_uci="c2c3", best_san="c3", best_uci="c2c3",
               fen_before=GG, fen_after="rnbq1rk1/ppp2ppp/3b1n2/3p4/3P4/2PB1N2/PP3PPP/RNBQ1RK1 b - - 0 7",
               cp_before=150, mate_before=None, cp_after=150, mate_after=None, best_line_san=[], refutation_san=[],
               material_before=40, in_book=False, delivered_mate=False, game_over_after=False,
               n_legal=30, second_cp=100, sac_points=0)
bxh7 = dataclasses.replace(base, played_san="Bxh7+", played_uci="d3h7", best_san="Bxh7+", best_uci="d3h7",
                           fen_after="rnbq1rk1/ppp2ppB/3b1n2/3p4/3P4/5N2/PPP2PPP/RNBQ1RK1 b - - 0 7")
T = Thresholds()
check((T.inaccuracy_pp, T.mistake_pp, T.blunder_pp) == (5.0, 10.0, 20.0), "error bands are chess.com's 5 / 10 / 20")
check(classify_ply(base, T, False).severity == "Best", "best move, quiet alternatives: Best")
gm = classify_ply(dataclasses.replace(base, second_cp=-250), T, False)
check(gm.severity == "Great" and "only good move" in gm.special_why, "second-best loses 20+ points: Great, with the reason")
check(classify_ply(dataclasses.replace(base, second_cp=-250, cp_before=900, cp_after=900), T, False).severity == "Best", "already won: not Great")
check(classify_ply(dataclasses.replace(bxh7, second_cp=-250, sac_points=0, fen_before=GG), T, False).severity != "Great", "a capture is never an only-move Great")
bm = classify_ply(bxh7, T, False)
check(bm.severity == "Brilliant" and "2 points" in bm.special_why, "sound sacrifice of the engine's move: Brilliant")
check(classify_ply(dataclasses.replace(bxh7, recapture=True), T, False).severity != "Brilliant", "a recapture is never Brilliant")
check(classify_ply(dataclasses.replace(bxh7, cp_after=-300, cp_before=-300), T, False).severity != "Brilliant", "a sacrifice that leaves you losing is not Brilliant")
check(classify_ply(dataclasses.replace(bxh7, cp_before=900, cp_after=900), T, False).severity != "Brilliant", "already winning: not Brilliant")
check(classify_ply(dataclasses.replace(base, sac_points=None, second_cp=None), T, False).severity == "Best", "old reviews (no MultiPV data) stay Best")
# Great, second case: turning the game after the opponent's mistake
from chess_analysis import GameReview, _turns_the_game  # noqa: E402
opp_pl = dataclasses.replace(base, ply=12, color="Black", played_uci="a7a6", best_uci="b8c6", played_san="a6", best_san="Nc6",
                             cp_before=200, cp_after=-150)  # Black was better (+2) and threw it away
opp = classify_ply(opp_pl, T, False)
check(opp.severity in ("Mistake", "Blunder"), f"setup: the opponent's move is an error ({opp.severity})")
tg_pl = dataclasses.replace(base, cp_before=150, cp_after=150, second_cp=-40)
tg = classify_ply(tg_pl, T, False); _turns_the_game(tg_pl, tg, opp)
check(tg.severity == "Great" and tg.special_why.startswith("turns the game"), f"punishing the mistake, losing -> equal: Great ({tg.special_why})")
easy_pl = dataclasses.replace(tg_pl, second_cp=140)
easy = classify_ply(easy_pl, T, False); _turns_the_game(easy_pl, easy, opp)
check(easy.severity == "Best", "when other moves cash in too, it is just Best")


print("1c. motifs (hand-made positions)")
import chess as _c  # noqa: E402
from motifs import analyse_line, _material_desc  # noqa: E402
from collections import Counter as _C  # noqa: E402
# knight fork of king and rook that wins the rook
fk = analyse_line(_c.Board("4k3/8/8/8/8/8/3r4/4K1N1 w - - 0 1"), ["Nf3", "Ke7", "Nxd2"], ben_cp=500)
check(fk["motif"] is None or fk["motif"] in ("hanging piece", "material", "fork"), f"plain capture line is not called a mate ({fk['motif']})")
fk = analyse_line(_c.Board("r3k3/8/8/8/8/8/8/4K1N1 w - - 0 1"), ["Nf3", "Kd7", "Ne5+", "Kc7", "Nd3"], ben_cp=0)
check(fk["motif"] is None, "no material won -> no motif claimed")
fk = analyse_line(_c.Board("4k3/8/8/2r5/8/3N4/8/4K3 w - - 0 1"), ["Nxc5"], ben_cp=500)
check(fk["motif"] == "hanging piece" and "undefended rook on c5" in fk["phrase"], f"undefended rook: {fk['phrase']}")
fk = analyse_line(_c.Board("r5k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1"), ["Rd8+", "Rxd8"], ben_cp=-500)
check(fk["motif"] is None or fk["motif"] != "mate", "a rook that is just traded is not mate")
bk = analyse_line(_c.Board("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1"), ["Rd8#"], ben_mate=1)
check(bk["motif"] == "back-rank mate" and bk["mate_in"] == 1, f"back-rank mate ({bk['motif']})")
fork = analyse_line(_c.Board("r3k3/8/8/8/8/8/8/4K1N1 w - - 0 1".replace("r3k3", "r3k3").replace("4K1N1", "4K3")), [], ben_cp=0)
check(fork["motif"] is None, "empty line -> nothing")
fk = analyse_line(_c.Board("2r1k3/8/8/1N6/8/8/8/4K3 w - - 0 1"), ["Nd6+", "Kd7", "Nxc8"], ben_cp=600)
check(fk["motif"] == "fork" and "king" in fk["phrase"] and "rook" in fk["phrase"], f"knight fork of king and rook: {fk['phrase']}")
check(_material_desc(_C({_c.KNIGHT: 1}), _C({_c.PAWN: 2})) == "a pawn", "N for two pawns is described as a pawn, not a knight")
check(_material_desc(_C({_c.ROOK: 1}), _C({_c.BISHOP: 1})) == "the exchange", "R for B is the exchange")
check(analyse_line(_c.Board("4k3/8/8/2r5/8/3N4/8/4K3 w - - 0 1"), ["Nxc5"], ben_cp=50)["motif"] != "hanging piece",
      "a material claim the eval doesn't back is dropped")

print("2. store")
g1 = parse_games('[Event "x"]\n[Link "https://www.chess.com/game/live/42?move=0"]\n[White "Me"]\n[Black "Opp"]\n[Result "1-0"]\n\n' + SCHOLAR)[0]
gid, new = store.add_game(g1, {"chesscom_user": "me", "lichess_user": ""})
check(gid == "chesscom:42" and new, "chess.com Link header gives a stable id")
_, again = store.add_game(g1, {"chesscom_user": "me", "lichess_user": ""})
check(not again and store.count_games() == 1, "importing the same game twice is a no-op")
g = store.get_game(gid)
check(g["player_color"] == "White" and g["opponent"] == "Opp" and g["outcome"] == "win", "my side / opponent / outcome from username (case-insensitive)")
g2 = parse_games("1. d4 d5 2. c4 e6")[0]
gid2, _ = store.add_game(g2, store.get_settings())
check(gid2.startswith("pgn:") and store.get_game(gid2)["player_color"] is None, "unknown side stays empty")
s = store.set_settings({"rating": 1300, "puzzles_per_day": 15, "bogus": 1})
check(s["rating"] == 1300 and s["puzzles_per_day"] == 15 and "bogus" not in s and s["puzzles_include_opponent"] is True, "settings: saved, defaults, unknown keys ignored")
rv = analyze_game(g1, SF, "White", 1200, Thresholds(), depth=8, threads=1)
store.save_review(gid, rv)
check(store.get_game(gid)["analysed"] and store.load_review(gid, Thresholds()) is not None, "review saved and reloaded")
th = dict(store.get_settings()["thresholds"]); th["inaccuracy_pp"] = 0.5; th["mistake_pp"] = 0.6; th["blunder_pp"] = 0.7
store.set_settings({"thresholds": th})
check(store.get_game(gid)["blunders"] >= 1, "changing thresholds recomputes the cached Library numbers")
store.set_settings({"thresholds": json.loads(json.dumps(store.DEFAULT_SETTINGS["thresholds"]))})

sample = open(os.path.join(HERE, "tests", "sample_games.pgn")).read()
v2games = parse_games(sample)
v2rv = analyze_game(v2games[2], SF, "White", 1200, Thresholds(), depth=6, threads=1)
from payload import clock_limits, clock_report  # noqa: E402
L = clock_limits(600)
check(L["budget"] == 15 and L["quick"] == 5 and L["long"] == 45 and L["low"] == 60, "10+0: 15 s a move, snap under 5 s, long think over 45 s, low under 60 s")
L = clock_limits(180, 2)
check(abs(L["budget"] - 6.5) < 1e-9 and abs(L["quick"] - 6.5 / 3) < 1e-9 and L["low"] == 26, "3+2: the increment counts in the budget")
check(clock_limits(600, 0, 30)["quick"] > clock_limits(600, 0, 40)["quick"], "shorter typical games give a bigger per-move budget")
cr = clock_report(v2rv)
check(cr and cr["tc"] == "10 minutes each, no increment" and cr["quick"] == 5 and cr["me"]["used"] > 0 and cr["opp"] and cr["notes"], "clock report for both sides of a 10+0 game")
check(clock_report(run(SCHOLAR, "White")) is None, "no clock report without clocks")
gv2, _ = store.add_game(v2games[2], store.get_settings())
store.save_review(gv2, v2rv)
check(gv2.startswith("chesscom:100000000001") and store.get_game(gv2)["analysed"], "a chess.com game keeps its chess.com id and analysis")
store.set_settings({"chesscom_user": "TestPlayer"})

print("2b. account sync (simulated chess.com and Lichess)")
import sync  # noqa: E402
SAMPLE = parse_games(open(os.path.join(HERE, "tests", "sample_games.pgn")).read())
def cc_pgn(i, white="TestPlayer", black="Opp"):
    return f'[Event "Live Chess"]\n[Site "Chess.com"]\n[White "{white}"]\n[Black "{black}"]\n[Result "1-0"]\n[TimeControl "180+2"]\n[Link "https://www.chess.com/game/live/{900+i}"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bc4 Nf6 1-0'
LI = [json.dumps({"id": f"li{i}xxxxx", "variant": "standard", "createdAt": 1000 + i,
                  "pgn": f'[Site "https://lichess.org/li{i}xxxxx"]\n[White "Opp"]\n[Black "testplayer"]\n[Result "0-1"]\n\n1. d4 d5 {i % 2 and "2. c4" or "2. Nf3"} 0-1'}) for i in range(3)]
LI.append(json.dumps({"id": "var", "variant": "chess960", "createdAt": 2000, "pgn": '[Site "https://lichess.org/varxxxxx"]\n\n1. e4 *'}))
calls = []
def fake_json(url):
    calls.append(url)
    if url.endswith("/archives"):
        return {"archives": ["https://api.chess.com/pub/player/testplayer/games/2026/08", "https://api.chess.com/pub/player/testplayer/games/2026/09"]}
    if url.endswith("2026/08"):
        return {"games": [{"rules": "chess", "pgn": cc_pgn(1)}, {"rules": "chess960", "pgn": cc_pgn(2)}]}
    return {"games": [{"rules": "chess", "pgn": cc_pgn(3)}, {"rules": "chess", "pgn": cc_pgn(4)}]}
def fake_lines(url):
    calls.append(url)
    since = int(urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("since", ["0"])[0])
    return [l for l in LI if json.loads(l)["createdAt"] >= since]
store.set_settings({"chesscom_user": "TestPlayer", "lichess_user": "TestPlayer"})
sy = sync.Syncer(); sy.get_json = fake_json; sy.get_lines = fake_lines
n0 = store.count_games()
sy.start()
for _ in range(100):
    if sy.snapshot()["state"] != "running": break
    time.sleep(0.05)
st = sy.snapshot()
check(st["state"] == "done" and st["added"] == 6 and store.count_games() == n0 + 6, f"first sync adds 3 chess.com + 3 Lichess games, skips variants ({st['added']}, {st['errors']})")
check(all(g["player_color"] for g in store.list_games() if g["id"].startswith(("chesscom:90", "lichess:li"))), "my side known for synced games")
check(not any(store.get_game(g["id"])["analysed"] for g in store.list_games() if g["id"].startswith("lichess:li")), "sync never analyses")
calls.clear(); sy.start()
for _ in range(100):
    if sy.snapshot()["state"] != "running": break
    time.sleep(0.05)
st = sy.snapshot()
check(st["added"] == 0 and not any(u.endswith("2026/08") for u in calls), "second sync re-reads only the latest month and newer Lichess games")
check(st["last"]["state"] == "done", "last sync remembered")
def boom(url):
    raise urllib.error.HTTPError(url, 404, "nf", {}, None)
sy2 = sync.Syncer(); sy2.get_json = boom; sy2.get_lines = boom
store.set_meta("sync_state", "{}")
sy2.start()
for _ in range(100):
    if sy2.snapshot()["state"] != "running": break
    time.sleep(0.05)
check(any("no player" in e for e in sy2.snapshot()["errors"]), "unknown username gives a clear message")
# selective sync: window + time controls + opponent rating
for gid in [g["id"] for g in store.list_games() if g["id"].startswith(("chesscom:90", "lichess:li"))]:
    store.delete_game(gid)
store.forget_deleted()
store.set_meta("sync_state", "{}")
store.set_settings({"sync_window": "since", "sync_since": "2026-09-01", "sync_tcs": ["rapid"]})
def run_sync():
    calls.clear(); sy.start()
    for _ in range(100):
        if sy.snapshot()["state"] != "running": break
        time.sleep(0.05)
    return sy.snapshot()
st = run_sync()
check(not any(u.endswith("2026/08") for u in calls), "months before the sync window are not fetched")
check(st["added"] == 0 and st["filtered"] == 2, f"blitz games skipped when only rapid is synced ({st['added']}, {st.get('filtered')})")
li_url = [u for u in calls if "lichess" in u][0]
check("perfType=rapid" in li_url and "since=1788220800000" in li_url, "Lichess asked only for rapid games since the window start")
store.set_settings({"sync_tcs": []})
st = run_sync()
check(st["added"] == 2 and any(u.endswith("2026/09") for u in calls), "changing the filters re-reads the months in range")
f = sync.sync_filter({"sync_window": "6m", "sync_opp_min": 1200, "sync_opp_max": "1500"}, today=sync.dt.date(2026, 10, 4))
check(f["since"] == "2026-04-04" and f["opp_max"] == 1500, "rolling window and rating range parsed")
check(sync.keep(f, "2026-05-01", "blitz", 1300) and not sync.keep(f, "2026-03-01", "blitz", 1300)
      and not sync.keep(f, "2026-05-01", "blitz", 1100) and not sync.keep(f, "2026-05-01", "blitz", 1600), "filter keeps only games inside window and rating range")
check(sync.sync_filter({})["active"] is False, "no filter by default: every game synced")
store.set_settings({"sync_window": "all", "sync_since": "", "sync_tcs": []})
for gid in [g["id"] for g in store.list_games() if g["id"].startswith(("chesscom:90", "lichess:li"))]:
    store.delete_game(gid)
store.set_settings({"lichess_user": ""})

print("2c. puzzles (V4)")
import puzzles  # noqa: E402
TRAP = ('[Event "t"]\n[White "TestPlayer"]\n[Black "Trapper"]\n[Result "0-1"]\n\n'
        "1. e4 e5 2. Nf3 Nc6 3. Bc4 Nd4 4. Nxe5 Qg5 5. Nxf7 Qxg2 6. Rf1 Qxe4+ 7. Be2 Nf3# 0-1")
gt = parse_games(TRAP)[0]
gtid, _ = store.add_game(gt, {"chesscom_user": "TestPlayer", "lichess_user": ""})
store.save_review(gtid, analyze_game(gt, SF, "White", 1200, Thresholds(), depth=12, threads=1))
added = puzzles.scan()
pq = puzzles.queue()
mine_p = [p for p in pq["queue"] if p["source"] == "mine"]
check(added >= 1 and mine_p, f"puzzles built from my errors in an analysed game ({added})")
check(all(p["color"] == "White" for p in mine_p) and all(len(p["solution"]) % 2 == 1 for p in pq["queue"]),
      "my puzzles are played as my side; every solution ends on the solver's move")
check(puzzles.scan() == 0, "scanning again adds nothing")
check(all(p["why"] and p["why"]["line"] and p["why"]["best"] for p in pq["queue"]), "every puzzle carries its line and a why line")
check(all(p["why"]["played"] and p["why"]["played"]["text"] for p in mine_p if p["kind"] == "tactic"), f"my tactic puzzles say what my game move allowed ({[(p['label'], p['played_san'], p['why']['played']) for p in mine_p if p['kind'] == 'tactic'][:2]})")
store.set_settings({"puzzles_per_day": 1})
check(len(puzzles.queue()["queue"]) == 1 and len(puzzles.queue(more=True)["queue"]) == pq["new_count"], "the daily queue respects puzzles per day (and 'keep going')")
p0 = pq["queue"][0]
r = puzzles.record(p0["id"], "solved", 0)
check(r["interval"] == 1 and r["due"] > puzzles.today(), "solved: comes back tomorrow at first")
check(puzzles.queue()["done_today"] == 1 and not puzzles.queue()["queue"], "done for today after 1 of 1")
r = puzzles.record(p0["id"], "solved", 0)
check(r["interval"] == 3, "solved again: 3 days")
r = puzzles.record(p0["id"], "failed", 0)
check(r["interval"] == 1, "failed: back to tomorrow")
store.set_settings({"puzzles_per_day": 10, "puzzles_include_opponent": False})
check(all(p["source"] == "mine" or p["from_retry"] for p in puzzles.queue(more=True)["queue"]), "opponent puzzles can be switched off")
store.set_settings({"puzzles_include_opponent": True})
sol = puzzles._solution("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1", ["Rd8#"], 1)
check(sol == (["d1d8"], ["Rd8#"]), "a mate in 1 is a one-move puzzle")
sol = puzzles._solution(chess.STARTING_FEN, ["e4", "e5", "Nf3", "Nc6"], None)
check(len(sol[0]) == 1, "a quiet follow-up is not part of the solution")
vid = puzzles.save_variation("my idea", chess.STARTING_FEN, ["e2e4", "e7e5"])
check(puzzles.variations()[0]["san"] == ["e4", "e5"], "variations saved with their moves")
puzzles.delete_variation(vid)
store.delete_game(gtid)
check(not [p for p in puzzles.queue(more=True)["queue"] if p["game_id"] == gtid], "deleting a game removes its puzzles")

print("2g. V7: recurring mistakes, notes and tags, weekly note, backups, coach facts")
import patterns, weekly, backup, coach  # noqa: E402,E401
pt = patterns.build()
check(pt["analysed"] >= 1 and isinstance(pt["patterns"], list), f"recurring mistakes computed ({pt['analysed']} games, {len(pt['patterns'])} patterns)")
check(patterns.build()["analysed"] == pt["analysed"], "recurring mistakes: second call from the per-game cache")
_g = store.list_games()[0]["id"]
store.set_tags(_g, ["Revisit", "time scramble", "revisit"])
store.set_note(_g, 0, "remember the knight")
store.set_note(_g, 12, "why not castle")
nt = store.get_notes(_g)
check(nt["tags"] == ["revisit", "time scramble"] and nt["notes"][12] == "why not castle", "tags (deduplicated, lower case) and notes stored")
check(_g in store.search_notes(["knight"]) and any(g["tags"] == ["revisit", "time scramble"] for g in store.list_games() if g["id"] == _g), "notes are searchable; tags come with the game list")
store.set_note(_g, 12, "")
check(12 not in store.get_notes(_g)["notes"], "an empty note removes it")
wk = weekly.note(0)
check(wk["markdown"].startswith("# Chess week") and "games" in wk, "weekly note in Markdown")
mon, sun = weekly.week_bounds(0)
check(mon.weekday() == 0 and (sun - mon).days == 6, "weekly note: Monday to Sunday")
bk = backup.make()
check(bk["bytes"] > 0 and backup.list_backups()[0]["name"] == bk["name"], "backup made and listed")
st_ = backup.stage_restore(bk["name"])
check(st_["games"] == store.count_games() and backup.pending(), "a backup checks out and is staged for the next start")
check(backup.cancel_restore() and not backup.pending(), "a staged restore can be cancelled")
try:
    backup.stage_restore("../chess.sqlite"); bad = False
except ValueError:
    bad = True
check(bad, "restore refuses anything that isn't a backup file")
cf = coach.facts("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1", "g1h1")
check(cf["best"] == "Rd8#" and cf["verdict"] != "the best move" and cf["gap"] > 0 and any("Rd8#" in f for f in cf["facts"]), f"coach: a candidate against the best move ({cf['verdict']})")
cf2 = coach.facts("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1", "d1d8")
check(cf2["verdict"] == "the best move", "coach: the best move is called the best move")
store.set_tags(_g, []); store.set_note(_g, 0, "")
import features as FT  # noqa: E402
_br = FT.features(chess.Board("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1"), chess.WHITE)
check(_br["their_king"]["back_rank"] and not _br["king"]["back_rank"], "features: back-rank weakness only where the other side has a rook or queen")
_lp = FT.features(chess.Board("4k3/8/8/3n4/8/8/8/3RK3 w - - 0 1"), chess.WHITE)
check(any(x["square"] == "d5" and not x["defended"] for x in _lp["their_loose"]), "features: an undefended attacked piece is loose")
_pp = FT.features(chess.Board("4k3/8/8/2P5/8/8/1p6/4K3 w - - 0 1"), chess.WHITE)
check(_pp["pawns"]["passed"] == ["c5"] and _pp["their_pawns"]["passed"] == ["b2"], "features: passed pawns for both sides")
_pl = FT.plan(chess.Board("r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/3P1N2/PPP2PPP/RNBQK2R w KQkq - 1 5"),
              [chess.Move.from_uci(u) for u in ["e1g1", "a7a6", "c2c3", "c5a7", "f1e1"]], chess.WHITE)
check(any("castle kingside" in x for x in _pl) and any("rook" in x for x in _pl), f"plan: castling and piece moves from an engine line ({_pl})")
cf3 = coach.facts("r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/3P1N2/PPP2PPP/RNBQK2R w KQkq - 1 5", "c1g5")
keys = [x["key"] for x in cf3["sections"]]
check(keys[:5] == ["verdict", "position", "threats", "changes", "plan"] and cf3["facts"] and any("[The position]" in f for f in cf3["facts"]),
      f"coach: verdict, position, threats, what changes and the plan ({keys})")
check(any("Italian" in l for l in cf3["sections"][1]["lines"]), "coach: the opening name in the position section")
cf4 = coach.facts("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1", "g1h1")
check(any("threatens Rd8#" in l for l in next(x for x in cf4["sections"] if x["key"] == "threats")["lines"]), "coach: what your move threatens")
check(coach.chat(cf4["facts"], [], "why?")["text"] is None, "coach: follow-ups need a model; without one it says so")

_pq = puzzles.queue(more=True)["queue"]
if _pq:
    _pid = _pq[0]["id"]
    _r = puzzles.record(_pid, "slow", 0, judged=True)
    check(_r["result"] == "solved" and _r["interval"] <= 3, "puzzles: over the clock counts as solved but comes back sooner")
    check(puzzles.queue()["judgement"]["right"] >= 1, "puzzles: 'one move or several?' guesses are counted")
    check(all("budget" in x for x in _pq), "puzzles: each carries its clock budget")

print("2d. openings tree, repertoire, drills (V5)")
import repertoire  # noqa: E402
OPG = []
for i, (line, res) in enumerate([("1. d4 d5 2. c4 e6 3. Nc3 Nf6", "1-0")] * 10 + [("1. d4 d5 2. c4 c6 3. Nc3 Nf6", "0-1")] * 8
                                 + [("1. d4 Nf6 2. c4 g6 3. Nc3 Bg7", "1-0")] * 3 + [("1. e4 e5 2. Nf3 Nc6", "1/2-1/2")] * 2):
    pg = (f'[Event "op{i}"]\n[Site "op{i}"]\n[White "TestPlayer"]\n[Black "Opp{i}"]\n[Result "{res}"]\n[Date "2026.09.{10 + i:02d}"]\n'
          f'[TimeControl "180+2"]\n\n{line} {{[%clk 0:02:59]}} {res}')
    OPG.append(store.add_game(parse_games(pg)[0], {"chesscom_user": "TestPlayer", "lichess_user": ""})[0])
check(len(set(OPG)) == 23, "23 opening test games stored")
check(repertoire._movetext('1. d4 {[%clk 0:02:59.9]} 1... d5 {[%clk 0:02:58]} 2. c4!? (2. Nf3 Nf6) dxc4 1-0') == ["d4", "d5", "c4", "dxc4"],
      "move text: clocks, glyphs and side lines are skipped")
repertoire.INDEXER.run()
with store.db() as _c:
    check(not repertoire.INDEXER.pending(_c), "opening index is up to date after a run (analysed games included)")
t = repertoire.tree([], "White")
d4 = next(m for m in t["moves"] if m["san"] == "d4")
check(d4["n"] == 21 and d4["w"] == 13 and d4["l"] == 8 and d4["score"] == 62, f"tree: 1.d4 in 21 games, 13 won, 8 lost ({d4})")
check(t["my_turn"] and t["moves"][0]["san"] == "d4", "tree: White to move, most played first")
t2 = repertoire.tree(["d2d4", "d7d5", "c2c4"], "White")
check({m["san"] for m in t2["moves"] if m["n"]} == {"e6", "c6"} and any(m.get("theory_only") for m in t2["moves"]) and t2["opening"] and "Queen" in t2["opening"], f"tree after 1.d4 d5 2.c4: their replies and the opening name ({t2['opening']})")
check(repertoire.depth_cap(1300) == 8 and repertoire.depth_cap(2100) == 12, "repertoire depth cap from rating")
sc = repertoire.scan("White")
check(sc["games"] >= 23 and sc["worst"] and sc["best"] and sc["best"][0]["score"] >= sc["worst"][0]["score"], f"line scan ranks lines by your score ({sc})")
b = repertoire.build_from_games("White", 1300)
check(b["added"] >= 2, f"repertoire built from your games ({b})")
cov = repertoire.coverage("White")
check(cov["lines"] >= 2 and cov["games"] >= 12, f"coverage counts games that met the repertoire ({cov['share']}%)")
repertoire.set_move("White", [], "e2e4")
cov2 = repertoire.coverage("White")
check(cov2["left"] and cov2["left"][0]["planned"] == "e4" and cov2["left"][0]["n"] >= 12, "where you left it: 1.d4 played instead of the starred 1.e4")
repertoire.set_move("White", [], "d2d4")
dq = repertoire.drill_queue("White")
check(dq["queue"] and dq["queue"][0]["uci"] == "d2d4" and len(dq["queue"][0]["line"]) >= 3, f"drills: most-played first, with a follow-up line ({dq['queue'][0]['line'] if dq['queue'] else None})")
r = repertoire.drill_result("White", dq["queue"][0]["epd"], "solved")
check(r["interval"] == 1 and repertoire.drill_queue("White")["done_today"] == 1, "drill result scheduled; counted for today")
store.set_settings({"drills_per_day": 1})
check(not repertoire.drill_queue("White")["queue"] and repertoire.drill_queue("White", more=True)["queue"], "drills have their own daily number")
store.set_settings({"drills_per_day": 10})
try:
    repertoire.set_move("White", ["d2d4"], "d7d5"); bad = False
except ValueError:
    bad = True
check(bad, "starring a move when it isn't your turn is refused")
n_before = store.count_games()
store.delete_games(OPG[:2])
check(store.count_games() == n_before - 2 and set(OPG[:2]) <= store.deleted_ids(), "mass delete removes games and remembers them")
check(repertoire.tree([], "White")["moves"][0]["n"] == 19, "deleted games leave the opening tree")
st = store.storage()
check(st["games"] == n_before - 2 and st["deleted"] >= 2 and st["bytes"] > 0, "storage numbers")
check(store.forget_deleted() >= 2 and not store.deleted_ids(), "forget the deleted list")
import theory  # noqa: E402
r = theory.search("caro kann advance")
check(r and r[0]["name"] == "Caro-Kann Defense: Advance Variation" and r[0]["san"] == ["e4", "c6", "d4", "d5", "e5"] and r[0]["side"] == "Black",
      "theory search finds an opening by name, with its moves and side")
check(theory.search("king’s indian") and theory.search("B12"), "theory search ignores curly quotes; finds by ECO")
lr = theory.learn("Black", r[0]["moves"], 1300)
check(lr["added"] >= 10 and lr["theory"] >= 3 and lr["engine"] >= 1, f"learning an opening adds theory and engine moves ({lr})")
mo = theory.my_openings("Black")
check(mo and mo[0]["opening"].endswith("Caro-Kann Defense: Advance Variation") and mo[0]["n"] == lr["added"], "the opening is listed with its moves")
dq = repertoire.drill_queue("Black", more=True, opening=lr["opening"])
check(dq["queue"] and dq["queue"][0]["san"] == "c6" and len(dq["queue"][0]["line"]) >= 3, f"drills for a new opening follow its line ({dq['queue'][0]['line'] if dq['queue'] else None})")
t3 = repertoire.tree(["e2e4", "c7c6", "d2d4", "d7d5", "e4e5"], "Black")
check(any(m["san"] == "Bf5" and m.get("theory_only") for m in t3["moves"]) and t3["rep"], "tree shows theory moves you haven't played, with your star")
rec = theory.recent("White", 3650)
check(rec and rec[0]["family"] and rec[0]["moves"] is not None, f"recent openings from your games ({[(x['family'], x['recent']) for x in rec][:3]})")
check(theory.forget_opening("Black", lr["opening"]) == lr["added"] and not theory.my_openings("Black"), "an opening can be removed again")
print("2f. opening study, line by line")
import study  # noqa: E402
import datetime as _dtm  # noqa: E402
store.set_settings({"new_lines_per_day": 3})
sl = study.sync_lines("White")
q = study.queue("White")
check(sl["lines"] >= 2 and q["queue"] and all(x["mode"] == "learn" for x in q["queue"]), f"lines from the repertoire, new ones to learn ({sl})")
check(q["queue"][0]["freq"] == max(x["freq"] for x in q["queue"]) and q["queue"][-1]["freq"] < q["queue"][0]["freq"], "the lines you meet most in your games come first")
first = next(x for x in q["queue"] if x["san"][:4] == ["d4", "d5", "c4", "e6"])
k = first["key"]
r1 = study.result("White", k, True)
r2 = study.result("White", k, True)
r3 = study.result("White", k, True)
check((r1["state"], r1["step"]) == ("learning", 1) and (r2["state"], r2["step"]) == ("learning", 2) and (r3["state"], r3["interval"]) == ("review", 1),
      "learn, then two same-day steps, then review in 1 day")
pr = study.result("White", k, False, practice=True)
check(pr["practice"] and study.queue("White", practice=True)["queue"][0]["mode"] == "practice", "practice is logged without moving the schedule")
m1 = study.result("White", k, False)
check((m1["state"], m1["step"]) == ("learning", 1), "a missed review goes back to the same-day steps")
with store.db() as _c:
    _c.execute("UPDATE rep_lines SET state = 'review', ladder = 1, due = 0, learned_on = ? WHERE color = 'White' AND key = ?",
               ((_dtm.date.today() - _dtm.timedelta(days=8)).isoformat(), k))
lr2 = study.result("White", k, True)
check(lr2["learned"] and lr2["interval"] == 7, "learned = a clean review 7+ days after learning; next in 7 days")
store.set_settings({"new_lines_per_day": 1})
q1 = study.queue("White")
check(not [x for x in q1["queue"] if x["mode"] == "learn"] and [x for x in study.queue("White", more=1)["queue"] if x["mode"] == "learn"],
      "new lines have a daily number; 'learn more' adds some")
store.set_settings({"new_lines_per_day": 3})
mv = first["moves"]
repertoire.set_move("White", mv + ["g8f6"], "c1g5")
with store.db() as _c:
    grown = _c.execute("SELECT * FROM rep_lines WHERE color = 'White' AND key = ?", (",".join(mv + ["g8f6", "c1g5"]),)).fetchone()
    old_gone = _c.execute("SELECT COUNT(*) FROM rep_lines WHERE color = 'White' AND key = ?", (k,)).fetchone()[0] == 0
check(grown is not None and old_gone and grown["state"] == "review" and grown["ladder"] == 2, "a line that grows keeps its progress")
with store.db() as _c:
    _c.execute("UPDATE rep_lines SET due = ?, learned_on = ? WHERE color = 'White' AND key = ?", (study.in_days(7), study.today(), grown["key"]))
study.apply_games()                       # catch up on the games already there
dev_pgn = (f'[Event "dev"]\n[Site "dev1"]\n[White "TestPlayer"]\n[Black "Deviant"]\n[Result "0-1"]\n[Date "{_dtm.date.today().strftime("%Y.%m.%d")}"]\n'
           '[TimeControl "180+2"]\n\n1. d4 d5 2. c4 e6 3. Nf3 Nf6 0-1')
dev_id = store.add_game(parse_games(dev_pgn)[0], {"chesscom_user": "TestPlayer", "lichess_user": ""})[0]
repertoire.INDEXER.run()
moved = study.apply_games()
with store.db() as _c:
    g2 = _c.execute("SELECT ladder, due FROM rep_lines WHERE color = 'White' AND key = ?", (grown["key"],)).fetchone()
check(moved >= 1 and g2["ladder"] == 1 and g2["due"] <= study.in_days(3), "a game that left the line moves it one step back (7 days -> 3)")
dv = study.deviations(3650)
check(any(d["who"] == "you" and d["played"] == "Nf3" and d["planned"] == "Nc3" for d in dv), "deviations: you left your line in a recent game")
ov = study.overview()
check(ov["openings"] and sum(c["lines"] for c in ov["openings"]) >= 2 and any(c["learning"] for c in ov["openings"]), "overview: one card per opening with progress")
check(study.level_moves(3, 1300) == 8 and study.level_moves(1, 1300) == 4 and study.level_moves(5, 1300) > 12, "line length scale around the rating")
lr5 = theory.learn("Black", theory.search("caro kann advance")[0]["moves"], 1300, level=1)
check(lr5["cap"] == 4 and lr5["level"] == 1 and lr5["lines"]["lines"] >= 1, f"learning at a short length ({lr5['cap']} moves)")
lr6 = theory.learn("Black", theory.search("caro kann advance")[0]["moves"], 1300, level=1)
check(lr6["added"] == 0, "learning the same opening again adds nothing new")
store.delete_games(OPG + [dev_id], remember=False)
with store.db() as _con:
    _con.execute("DELETE FROM repertoire"); _con.execute("DELETE FROM drill_log")
    _con.execute("DELETE FROM rep_lines"); _con.execute("DELETE FROM study_log"); _con.execute("DELETE FROM study_openings")

print("2e. insights: skill profile, tilt, focus (V6)")
import skillprofile as SP  # noqa: E402
from datetime import datetime as _D, timedelta as _TD, timezone as _TZ
_t0 = _D(2026, 9, 1, 12, 0, tzinfo=_TZ.utc)
_g = lambda i, s, mins: {"t": _t0 + _TD(minutes=mins), "s": s, "outcome": {1: "win", 0: "loss", 0.5: "draw"}[s], "opp_elo": 1200,
                          "lost_on_time": False, "tc": "blitz"}
seq = [_g(0, 0, 0), _g(1, 0, 10), _g(2, 0, 20), _g(3, 1, 300), _g(4, 0, 310), _g(5, 1, 320)]
tl = SP.tilt(seq)
check(tl["after_2loss"]["n"] == 1 and tl["after_2loss"]["score"] == 0 and tl["after_loss"]["n"] == 3, f"tilt counts the game after two straight losses ({tl})")
se = SP.sessions(seq)
check(se["rows"][0]["n"] == 2 and se["rows"][2]["n"] == 2, "sessions split on 20-minute gaps")
check(SP.performance([_g(i, 1 if i < 3 else 0, i * 60) for i in range(6)]) == 1200, "performance rating: 3 wins, 3 losses vs 1200 = 1200")
pf = SP.build("", 3650)
check(all(k in pf for k in ("periods", "rating", "tilt", "sessions", "skills", "endgames", "suggestions", "focus")), "profile has every section")
check(set(pf["skills"]) == {"Opening", "Tactics", "Converting", "Defending", "Endgame", "Time"} and all("n" in v for v in pf["skills"].values()),
      "six skills, each with the number of games behind it")
fs = SP.set_focus("tilt")
check(fs["active"] and fs["active"]["key"] == "tilt" and "baseline" in fs["active"], "a weekly focus stores its baseline")
fs = SP.set_focus("sessions")
check(fs["active"]["key"] == "sessions" and fs["history"] and fs["history"][-1]["key"] == "tilt", "a new focus moves the old one to history")
check(SP.clear_focus()["active"] is None, "focus cleared")
try:
    SP.set_focus("nonsense"); bad = False
except ValueError:
    bad = True
check(bad, "unknown focus refused")

print("2j. V10: phases (Lichess's divider)")
import phases as PHA  # noqa: E402
START = chess.STARTING_FEN
NO_Q_N = "r1b1kb1r/pppppppp/8/8/8/8/PPPPPPPP/R1B1KB1R w KQkq - 0 1"     # 10 queens/rooks/minors left
R_B_N = "4k3/pp3r2/2n5/8/8/5B2/PP3R2/4K3 w - - 0 1"                      # 4 left
check(PHA.divide([START, START]) == (None, None), "divider: the starting position is all opening")
check(PHA.divide([START, NO_Q_N, R_B_N]) == (1, 2), "divider: middlegame at 10 pieces, endgame at 6 or fewer")
check(PHA.divide([START, R_B_N]) == (None, 1), "divider: straight into an endgame drops the middlegame")
check(PHA.divide([START, "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/R2QK2R w KQkq - 0 1"])[0] == 1, "divider: a thinned back rank starts the middlegame")
check([PHA.phase_at(i, 1, 2) for i in range(3)] == ["Opening", "Middlegame", "Endgame"], "phase of each ply")
# grading 5: the Review's phases and the Opening/Endgame move types come from the divider too
import payload as PAY  # noqa: E402
rvE = run('[SetUp "1"]\n[FEN "%s"]\n\n1. Rf1 Rf8 2. Kd2 Kd8 *' % R_B_N, "White")
check(all(m.game_phase == "Endgame" for m in rvE.moves + rvE.opp_moves), "an endgame position: every move is in the endgame")
check(all(m.move_type == "Endgame" for m in rvE.moves), "endgame moves have the Endgame type")
check(PAY._side_summary(rvE, False)["by_phase"]["Endgame"]["moves"] == 2, "the Review's phase accuracy uses the divider")
check(review_payload(rvE)["plies"][0]["game_phase"] == "Endgame", "the Review payload names each move's phase")
rvO = run("1. e4 e5 2. Nf3 Nc6", "White")
check(all(m.game_phase == "Opening" and m.move_type == "Opening" for m in rvO.moves), "opening moves: Opening phase and type")
print("2k. V11: other systems (system.py)")
import system as SYS, engines as ENG  # noqa: E402,E401
saved = (SYS.MAC, SYS.WINDOWS, SYS.LINUX, SYS.NAME)
for flags, name in (((True, False, False), "mac"), ((False, True, False), "windows"), ((False, False, True), "linux")):
    SYS.MAC, SYS.WINDOWS, SYS.LINUX = flags; SYS.NAME = name
    su = SYS.setup("/home/x/data")
    check(su["os"] == name and su["shell"] and su["stockfish"] and su["maia"] and su["book"] and (su["lc0"] or su["lc0_note"]),
          f"Setup has a command for every part on {name}")
    check(SYS.data_dir().endswith(("Chess Review", "chess-review")), f"a data folder on {name}")
SYS.MAC, SYS.WINDOWS, SYS.LINUX, SYS.NAME = saved
SYS.WINDOWS = True
hint = SYS.install_hint("stockfish")
SYS.WINDOWS = saved[1]
check("winget install" in hint, "the not-found message gives this system's command")
os.makedirs(os.path.join(store.data_dir(), "engines", "lc0-v0.31"), exist_ok=True)
fake = os.path.join(store.data_dir(), "engines", "lc0-v0.31", "lc0")
shutil.copy(FAKE_LC0, fake); os.chmod(fake, 0o755)
_path = os.environ["PATH"]; os.environ["PATH"] = os.path.dirname(sys.executable)   # no lc0 on the PATH
_dirs = SYS.engine_dirs; SYS.engine_dirs = lambda: []
check(ENG._which("lc0") == fake, "an engine unzipped into the data folder's engines/ is found")
import api as API  # noqa: E402
try:
    API.need_stockfish(); refused = ""
except API.ApiError as e:
    refused = str(e)
check(SYS.install_hint("stockfish") in refused, "a clean computer: Analyse is refused with the install command")
os.environ["PATH"] = _path; SYS.engine_dirs = _dirs
os.environ["CHESS_REVIEW_ENGINE_DIRS"] = os.pathsep.join(["/x/a", "", "/x/b"])
check(SYS.engine_dirs() == ["/x/a", "/x/b"], "CHESS_REVIEW_ENGINE_DIRS overrides where engines are looked for")
os.environ["CHESS_REVIEW_ENGINE_DIRS"] = ""
check(SYS.engine_dirs() == [], "an empty CHESS_REVIEW_ENGINE_DIRS means a clean computer")
del os.environ["CHESS_REVIEW_ENGINE_DIRS"]
shutil.rmtree(os.path.join(store.data_dir(), "engines"))
check(isinstance(SYS.low_priority("sf"), list), "engines start at low priority where nice exists")
_tconf = json.load(open(os.path.join(os.path.dirname(HERE), "tauri", "src-tauri", "tauri.conf.json")))
check(API.VERSION == _tconf["version"], f"the engine's version matches the app's ({API.VERSION} / {_tconf['version']})")
check("1400" in SYS.setup("/d", [1400])["maia"] and "1100" not in SYS.setup("/d", [1400])["maia"], "Setup fetches only the Maia nets that are missing")
check(set(ENG.status(store.get_settings())["maia_missing"]) <= set(SYS.MAIA_BANDS), "status lists the missing Maia nets")
import palette as PAL  # noqa: E402
_retro = {"theme": "retro-82", "mode": "dark", "background": "#05182e", "dark_background": "#031222", "lighter_background": "#0a2540",
          "selection": "#134e5a", "muted": "#2a6b78", "foreground": "#f6dcac", "dark_foreground": "#3f8f8a", "light_foreground": "#a7c9c6",
          "bright_foreground": "#f6dcac", "accent": "#faa968", "red": "#f85525", "orange": "#faa968", "yellow": "#e97b3c", "green": "#028391",
          "cyan": "#8cbfb8", "blue": "#3f8f8a", "magenta": "#3f8f8a"}
check(PAL.status()["installed"] is False and PAL.status()["vars"] is None, "Palette: not installed, nothing applied")
check(PAL.parse(json.dumps(dict(_retro, red="red"))) is None and PAL.parse("not json") is None and PAL.parse("[]") is None,
      "Palette: a file with any colour that isn't plain #rrggbb is ignored")
check(not set(PAL.parse(json.dumps(dict(_retro, theme='<img src=x onerror="y">')))["theme"]) & set('<>"/='), "Palette: the theme name is cleaned of markup")
_v = PAL.css_vars(PAL.parse(json.dumps(_retro)))
check(_v["--accent"] == "#3f8f8a" and _v["--page"] == "#05182e" and len(_v) == 15, "Palette: an orange accent is swapped (it would read as a Mistake label)")
check(PAL.contrast(_v["--muted"], "#05182e") >= 3 and PAL.contrast(_v["--good"], "#05182e") >= 3, "Palette: muted text and green are nudged until readable")
_lt = PAL.css_vars(PAL.parse(json.dumps(dict(_retro, mode="light", background="#fafafa", lighter_background="#e0e0e0", foreground="#222222", accent="#3366cc"))))
check(_lt["--accent"] == "#3366cc" and PAL.lum(_lt["--surface"]) > PAL.lum("#e0e0e0"), "Palette: a cool accent stays; light themes get cards lighter than darker")
os.makedirs(os.path.join(TMP, "palette", "current"), exist_ok=True)
with open(PAL.colours_file(), "w") as _f:
    json.dump(_retro, _f)
_ps = PAL.status()
check(_ps["installed"] and _ps["active"] and _ps["valid"] and _ps["theme"] == "retro-82" and _ps["accent_swapped"] and _ps["modified"], "Palette: status for the setup check")
with open(PAL.colours_file(), "w") as _f:
    _f.write(" " * (PAL.MAX_BYTES + 1))
check(not PAL.status()["file"], "Palette: an oversized file is ignored")
shutil.rmtree(os.path.join(TMP, "palette"))
check(store.get_settings()["follow_palette"] is False, "Follow Palette is off by default")
# V11: your rating from your own games, per time control
_rg = []
for _i, (_tc, _elo, _d) in enumerate([("60+0", 1010, "2026.10.01"), ("60+0", 1050, "2026.10.03"), ("1800+0", 1600, "2026.10.02")]):
    _g = parse_games(f'[Event "r{_i}"]\n[Site "rt{_i}"]\n[Date "{_d}"]\n[White "TestPlayer"]\n[Black "Opp"]\n[WhiteElo "{_elo}"]\n[BlackElo "1000"]\n[TimeControl "{_tc}"]\n[Result "1-0"]\n\n1. e4 e5 1-0')[0]
    _rg.append(store.add_game(_g, {"chesscom_user": "TestPlayer", "lichess_user": ""})[0])
_rs = store.my_ratings()
check(_rs["bullet"]["elo"] == 1050 and _rs["bullet"]["at"] == "2026-10-03" and _rs["classical"]["elo"] == 1600, f"rating: your latest game of each time control ({_rs.get('bullet')})")
_s = dict(store.get_settings(), rating_auto=True, rating_tc="classical", rating=1234)
check(store.my_rating("bullet", _s) == 1050 and store.my_rating(None, _s) == 1600 and store.my_rating("daily", _s) == 1600, "rating: per time control, else your main one")
check(store.my_rating("bullet", dict(_s, rating_auto=False)) == 1234, "rating: typed by hand when automatic is off")
store.delete_games(_rg, remember=False)
_md = os.path.join(TMP, "maia-bands"); os.makedirs(_md, exist_ok=True)
for _b in SYS.MAIA_BANDS:
    open(os.path.join(_md, f"maia-{_b}.pb.gz"), "w").close()
_ms = dict(store.get_settings(), lc0_path=FAKE_LC0, maia_dir=_md, use_maia=True, rating_auto=False, rating=1400)
check(ENG.pick_maia(_ms, 1171)[1].endswith("maia-1200.pb.gz") and ENG.pick_maia(_ms)[1].endswith("maia-1400.pb.gz"),
      "Maia: a blitz game at 1171 is compared with Maia 1200, not your typed 1400")
check(store.get_settings()["tips_seen"] == [], "a fresh install has seen no first-visit notes")
store.set_settings({"tips_seen": ["library"]}); check(store.get_settings()["tips_seen"] == ["library"], "a dismissed note is remembered")
store.set_settings({"tips_seen": []})
print("2h. V8: convert drills, study plan, opponents, practical move")
import convert, plan as PLN, opponents as OPP, practical as PRA  # noqa: E402,E401
import chess.engine  # noqa: E402
convert.scan()
check(convert.scan() == 0, "convert scan: a second pass adds nothing (games scanned once)")
with store.db() as con:
    convert.ensure(con)
    con.execute("INSERT OR REPLACE INTO convert_drills (id, game_id, ply, fen, color, start_cp, opp_elo, outcome, opponent, played_at, created) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("t:1", "t", 41, "4k3/8/8/8/8/8/8/3QK3 w - - 0 1", "White", 900, 1500, "draw", "Opp", "2026-01-01", time.time()))
cq = convert.queue(more=True)
check(any(d["id"] == "t:1" for d in cq["queue"]), "convert queue lists the drill")
st0 = convert.start("t:1")
check(st0["win"] >= 75 and st0["defender"], f"convert start: winning position ({st0['win']}%; drills start at +3, about 75%), defender {st0['defender']}")   # 95 was too tight for a quick eval on a slow CI runner
_eng = chess.engine.SimpleEngine.popen_uci(shutil.which("stockfish"))
out, n = None, 0
while n < 40:
    b = chess.Board(out["fen"] if out else st0["fen"])
    mv = _eng.play(b, chess.engine.Limit(depth=12)).move
    out = convert.move("t:1", mv.uci()); n += 1
    if out["status"]:
        break
_eng.quit()
check(out["status"] == "won" and out["summary"]["won"] and out["summary"]["due"], f"convert: queen vs king converted in {n} moves ({out['status']})")
check(convert.queue()["done_today"] >= 1, "convert: done today counted")
st1 = convert.start("t:1")
check(convert.resign("t:1")["status"] == "gave up", "convert: giving up is recorded")
with store.db() as con:
    rr = con.execute("SELECT reps, lapses, due FROM convert_drills WHERE id='t:1'").fetchone()
check(rr["reps"] == 0 and rr["lapses"] == 1, "convert: a give-up resets the drill and counts a lapse")
with store.db() as con:
    con.execute("DELETE FROM convert_drills WHERE id='t:1'"); con.execute("DELETE FROM convert_log WHERE drill_id='t:1'")
store.set_settings({"plan_minutes": None})
check(PLN.build() == {"enabled": False, "asked": False}, "plan: not asked yet")
store.set_settings({"plan_minutes": 0})
check(PLN.build() == {"enabled": False, "asked": True}, "plan: 0 switches it off")
store.set_settings({"plan_minutes": 120})
pb = PLN.build()
check(pb["enabled"] and len(pb["parts"]) == 4 and abs(sum(x["minutes"] for x in pb["parts"]) - 120) <= 2, f"plan: 2 hours split four ways ({[x['minutes'] for x in pb['parts']]})")
_g0 = store.list_games()[0]["id"]
before = next(x for x in pb["parts"] if x["key"] == "review")["done"]
PLN.log_review(_g0); PLN.log_review(_g0)
check(next(x for x in PLN.build()["parts"] if x["key"] == "review")["done"] == before + 1, "plan: a reviewed game counts once a day")
store.set_settings({"plan_minutes": None})
ol = OPP.list_opponents()
check(isinstance(ol, list) and all(o["games"] >= 2 for o in ol), f"opponents: repeat opponents only ({len(ol)})")
if ol:
    pr = OPP.profile(ol[0]["name"])
    check(pr["total"]["games"] == ol[0]["games"] and pr["games"], "opponents: profile matches the list")
try:
    OPP.profile("nobody-at-all"); miss = False
except KeyError:
    miss = True
check(miss, "opponents: unknown name refused")
if PRA.available():
    pp = PRA.practical("r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3")
    check(pp and pp["san"] and pp["gap"] <= 5, f"practical move: {pp and pp['san']} ({pp and pp['p']}%)")
else:
    print("   (practical move: skipped, Maia not installed)")

print("2i. puzzles: a forced mate is one answer (win chance saturates at mate)")
from types import SimpleNamespace as _NS  # noqa: E402
_mfen = "2q2rk1/p4rp1/3R4/2PB1p1p/2P3nP/PPQ3P1/1B6/4R1K1 w - - 0 33"
_b = chess.Board(_mfen); _b.push_san("Rg6")
_pl = _NS(best_line_san=["Qxg7#"], best_uci="c3g7", second_cp=602, second_mate=None, played_uci="d6g6", played_san="Rg6",
          cp_before=None, mate_before=1, fen_before=_mfen, color="White", ply=65, move_number=33, fen_after=_b.fen(),
          refutation_san=["Qxc5+"], cp_after=830, mate_after=None)
_c = puzzles._candidate(_pl, _NS(severity="Mistake"), "mine", "t")
check(_c and _c["kind"] == "tactic" and _c["solution_san"] == ["Qxg7#"], f"mate in 1 vs +6 is a one-answer puzzle ({_c and _c['kind']})")
_pl2 = _NS(**{**vars(_pl), "second_cp": None, "second_mate": 1})
check(puzzles._candidate(_pl2, _NS(severity="Mistake"), "mine", "t")["kind"] == "better", "two moves that mate at once: several answers")
_pl3 = _NS(**{**vars(_pl), "second_cp": None, "second_mate": 3})
check(puzzles._candidate(_pl3, _NS(severity="Mistake"), "mine", "t")["kind"] == "tactic", "a slower mate doesn't make it several answers")

print("3. HTTP API")
proc = subprocess.Popen([sys.executable, os.path.join(HERE, "server.py"), "--token", "T", "--parent-pipe"],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=dict(os.environ))
line = proc.stdout.readline().split()
port = int(line[1])
base = f"http://127.0.0.1:{port}"


def api(method, path, body=None, token="T"):
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Token": token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


try:
    check(line[0] == "LISTENING" and line[2] == "T", "prints LISTENING <port> <token>")
    check(api("GET", "/api/status", token="wrong")[0] == 403, "wrong token refused")
    with urllib.request.urlopen(base + "/") as r:
        check(r.status == 200 and b"<html" in r.read().lower(), "UI served without token")
    code, st = api("GET", "/api/status")
    check(code == 200 and st["engines"]["stockfish"], "status finds Stockfish")
    code, r = api("POST", "/api/import", {"text": sample})
    check(code == 200 and len(r["added"]) == 2 and len(r["existing"]) == 1, f"paste of 3 games: 2 new, 1 already there ({r})")
    code, r = api("POST", "/api/import", {"text": "not a game at all"})
    check(code == 200 and r["errors"] and not r["added"], "garbage paste gives an error, adds nothing")
    games = api("GET", "/api/games")[1]["games"]
    check(len(games) == 5 and all(g["player_color"] for g in games if "TestPlayer" in (g["white"], g["black"])), "Library lists games; my side known from username")
    target = next(g for g in games if not g["analysed"] and g["player_color"])
    api("POST", "/api/settings", {"depth": 8, "threads": 1})
    code, j = api("POST", f"/api/games/{urllib.parse.quote(target['id'])}/analyse", {})
    check(code == 200 and j["state"] in ("queued", "running"), "analysis queued")
    t0 = time.time()
    while time.time() - t0 < 180:
        jobs = {x["id"]: x for x in api("GET", "/api/jobs")[1]["jobs"]}
        if jobs[target["id"]]["state"] not in ("queued", "running"):
            break
        time.sleep(0.5)
    check(jobs[target["id"]]["state"] == "done", f"analysis finished ({jobs[target['id']]['state']}, {jobs[target['id']].get('error')}, {time.time()-t0:.0f}s)")
    code, g = api("GET", f"/api/games/{urllib.parse.quote(target['id'])}")
    rp = g.get("review") or {}
    check(code == 200 and rp.get("plies") and rp["summary"]["accuracy"] > 0, "review payload with plies and accuracy")
    mine = [p for p in rp.get("plies", []) if p["mine"]]
    check(mine and all("best_line" in p for p in mine), "every one of my moves has its lines")
    code, ex = api("GET", f"/api/games/{urllib.parse.quote(target['id'])}/export")
    check(code == 200 and "```chess" in ex["markdown"], "Markdown export")
    # V10: annotated PGN
    tq = urllib.parse.quote(target["id"])
    api("POST", f"/api/games/{tq}/notes", {"ply": 0, "text": "Game note here"})
    api("POST", f"/api/games/{tq}/notes", {"ply": 3, "text": "Move note here"})
    api("POST", f"/api/games/{tq}/tags", {"tags": ["pgntest"]})
    code, px = api("GET", f"/api/games/{tq}/pgn")
    pg = chess.pgn.read_game(io.StringIO(px.get("pgn", ""))) if code == 200 else None
    orig = chess.pgn.read_game(io.StringIO(store.game_pgn(target["id"])))
    check(pg is not None and not pg.errors and [m.uci() for m in pg.mainline_moves()] == [m.uci() for m in orig.mainline_moves()],
          "PGN export reads back with the same moves")
    labelled = sum(1 for p in rp["plies"] if p.get("severity") in ("Brilliant", "Great", "Inaccuracy", "Mistake", "Blunder"))
    nags = sum(len(n.nags) for n in pg.mainline()) if pg else -1
    check(nags == labelled, f"PGN export: one NAG per labelled move ({nags} vs {labelled})")
    evals = [n.eval() for n in pg.mainline()] if pg else []
    check(evals and sum(e is not None for e in evals) >= len(evals) - 1, "PGN export: [%eval] on every move (but a final mate)")
    flagged_alt = [p for p in rp["plies"] if p.get("flagged") and p["played_uci"] != p.get("best_uci")]
    vars_ = sum(len(n.variations) - 1 for n in [pg] + list(pg.mainline())[:-1]) if pg else 0
    check(vars_ == len(flagged_alt), f"PGN export: the better line as a variation at each flagged move ({vars_} vs {len(flagged_alt)})")
    third = list(pg.mainline())[2] if pg else None
    check(pg and "Game note here" in pg.comment and third and "Move note here" in third.comment and pg.headers.get("Tags") == "pgntest",
          "PGN export: notes and tags travel along")
    code, px0 = api("GET", f"/api/games/{tq}/pgn?lines=0&comments=0")
    check(code == 200 and "(" not in px0["pgn"].split("\n\n", 1)[1] and "Game note here" in px0["pgn"], "PGN export: lines and comments can be switched off; notes stay")
    plain = next(g for g in games if not g["analysed"] and g["id"] != target["id"])
    code, pm = api("POST", "/api/export/pgn", {"ids": [target["id"], plain["id"], "nope"]})
    check(code == 200 and pm["count"] == 2 and pm["analysed"] == 1 and len(parse_games(pm["pgn"])) == 2, f"PGN export of ticked games: 2 games, 1 analysed ({pm.get('count')}, {pm.get('analysed')})")
    check(api("POST", "/api/export/pgn", {"ids": []})[0] == 400, "PGN export with nothing ticked is refused")
    unknown = next(g for g in games if not g["player_color"])
    code, r = api("POST", f"/api/games/{urllib.parse.quote(unknown['id'])}/analyse", {})
    time.sleep(1.5)
    jobs = {x["id"]: x for x in api("GET", "/api/jobs")[1]["jobs"]}
    check(jobs[unknown["id"]]["state"] == "error" and "side" in jobs[unknown["id"]]["error"], "unknown side -> clear error asking which side")
    games = api("GET", "/api/games")["games"] if False else api("GET", "/api/games")[1]["games"]
    rp2 = api("GET", f"/api/games/{urllib.parse.quote(target['id'])}")[1]["review"]
    opp = [p for p in rp2["plies"] if not p["mine"]]
    check(opp and all("severity" in p for p in opp) and rp2["opp_summary"]["accuracy"] > 0, "opponent's moves carry labels and an accuracy")
    two = [g["id"] for g in games if g["player_color"] and not g["analysed"]][:1]
    code, r = api("POST", "/api/analyse-many", {"ids": two + ["nope"]})
    check(code == 200 and r["queued"] == len(two) and r["skipped"] == 1, "analyse-many queues only the selected games")
    api("POST", f"/api/games/{urllib.parse.quote(two[0])}/cancel") if two else None
    code, ph = api("GET", "/api/phases?tc=all&days=3650")
    my_err = sum(1 for p in rp2["plies"] if p["mine"] and p.get("severity") in ("Mistake", "Blunder"))
    check(code == 200 and len(ph["series"]) == 12 and len(ph["heat"]["land"]) == 64 and ph["games"] >= 1, "phases over HTTP: 12 months and a 64-square heatmap")
    check(ph["heat"]["errors"] >= my_err and set(ph["current"]) == {"Opening", "Middlegame", "Endgame"}, f"phases: every mistake and blunder on the heatmap ({ph['heat']['errors']} >= {my_err})")
    code, ins = api("GET", "/api/insights")
    check(code == 200 and ins["n_games"] >= 2 and len(ins["by_type"]) == 4, "insights")
    check(len(ins["by_tc"]) >= 1 and all("score" in r for r in ins["by_tc"]), "insights: one row per time control")
    tc0 = ins["by_tc"][0]["tc"]
    code, ins1 = api("GET", f"/api/insights?tc={tc0}")
    check(code == 200 and ins1["n_games"] == ins["by_tc"][0]["games"], f"insights narrowed to {tc0}")
    code, _ = api("DELETE", f"/api/games/{urllib.parse.quote(unknown['id'])}")
    check(code == 200 and len(api("GET", "/api/games")[1]["games"]) == 4, "delete")
    check(api("POST", "/api/open", {"url": "file:///etc/passwd"})[0] == 400, "open refuses non-https")
    code, pos = api("POST", "/api/position", {"fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"})
    check(code == 200 and len(pos["moves"]) == 20, "legal moves for a position (20 at the start)")
    code, gr = api("POST", "/api/grade", {"fen": "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1", "uci": "d1d8", "game_id": "x", "ply": 1})
    check(code == 200 and gr["solved"] and gr["label"] == "Best", f"grading the mating move: solved ({gr.get('label')})")
    code, gr = api("POST", "/api/grade", {"fen": "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1", "uci": "d1a1"})
    check(code == 200 and not gr["solved"] and gr["best_san"] == "Rd8#", f"grading a miss: not solved, best is Rd8# ({gr.get('label')})")
    check(api("POST", "/api/grade", {"fen": "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1", "uci": "e2e4"})[0] == 400, "illegal move refused")
    code, g = api("GET", f"/api/games/{urllib.parse.quote(target['id'])}")
    rp = g["review"]
    check(rp.get("story") and rp.get("key_moments") is not None, "review has a game story and key moments")
    check(all(q.get("explain") and q["explain"]["sentence"] for q in rp["plies"] if q.get("flagged")), "every flagged move has a verdict line")
    code, pz = api("GET", "/api/puzzles")
    check(code == 200 and "queue" in pz and pz["per_day"] == 10, f"puzzle queue over HTTP ({pz.get('total')} puzzles)")
    if pz.get("queue"):
        pid = urllib.parse.quote(pz["queue"][0]["id"], safe="")
        code, r = api("POST", f"/api/puzzles/{pid}/result", {"result": "failed", "hints": 2})
        check(code == 200 and r["result"] == "failed", "puzzle result recorded")
    check(api("POST", "/api/puzzles/nope/result", {"result": "solved"})[0] == 404, "unknown puzzle: 404")
    code, lv = api("POST", "/api/live/start", {"fen": "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1", "multipv": 3})
    check(code == 200 and lv["running"], "live analysis starts")
    for _ in range(40):
        time.sleep(0.25)
        lv = api("GET", "/api/live?fen=" + urllib.parse.quote("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1"))[1]
        if lv.get("lines") and lv["depth"] >= 6:
            break
    check(lv.get("lines") and lv["lines"][0]["mate"] == 1 and lv["lines"][0]["san"][0] == "1.Rd8#", f"live lines: mate in 1 first ({(lv.get('lines') or [{}])[0].get('san')})")
    check(len(lv["lines"]) >= 2, "MultiPV: more than one line")
    code, lv2 = api("POST", "/api/live/start", {"fen": chess.STARTING_FEN})
    time.sleep(1.0)
    lv2 = api("GET", "/api/live?fen=" + urllib.parse.quote(chess.STARTING_FEN))[1]
    check(lv2["fen"] == chess.STARTING_FEN and len(lv2["lines"]) == 3 and lv2["lines"][0]["san"][0].startswith("1."), "a new position replaces the old one")
    check(api("GET", "/api/live?fen=" + urllib.parse.quote("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1"))[1].get("stale"), "polling an old position says it's stale")
    api("POST", "/api/live/stop")
    time.sleep(0.3)
    check(not api("GET", "/api/live")[1]["running"], "live analysis stops")
    check(api("POST", "/api/live/start", {"fen": "bad"})[0] == 400, "bad FEN refused")
    code, mt = api("POST", "/api/live/start", {"fen": "3R2k1/5ppp/8/8/8/8/5PPP/6K1 b - - 1 1"})
    check(code == 200 and mt.get("game_over") == "1-0", "checkmated position: no lines, result given")
    code, th = api("POST", "/api/threat", {"fen": "6k1/5ppp/8/8/8/8/5PPP/3R2K1 b - - 0 1"})
    check(code == 200 and th["uci"] == "d1d8" and th["real"] and th["mate"] == 1, f"threat: Black to move, White threatens Rd8# ({th.get('san')})")
    code, th = api("POST", "/api/threat", {"fen": chess.STARTING_FEN})
    check(code == 200 and not th.get("real"), "no real threat in the starting position")
    code, gr = api("POST", "/api/grade", {"fen": "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1", "uci": "g2g3", "record": False})
    check(code == 200 and gr.get("reply_uci"), "a graded move comes with the engine's answer as a move")
    code, lv = api("POST", "/api/live/start", {"fen": chess.STARTING_FEN, "strength": "low"})
    check(code == 200 and lv.get("target_depth") == 14, "low engine strength: depth 14")
    api("POST", "/api/live/stop")
    code, op = api("POST", "/api/line", {"fen": chess.STARTING_FEN, "moves": ["e2e4", "c7c5"]})
    check(op["steps"][-1]["opening"] and "Sicilian" in op["steps"][-1]["opening"], f"positions carry their opening name ({op['steps'][-1]['opening']})")
    code, pos = api("POST", "/api/position", {"fen": "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1"})
    check(all(m.get("fen") for m in pos["moves"]) and not pos["game_over"], "legal moves carry the position after them")
    code, pr = api("GET", "/api/profile?days=3650")
    check(code == 200 and pr["skills"] and "tilt" in pr, "profile over HTTP")
    code, ar = api("POST", "/api/analyse-recent", {"n": 1})
    check(code == 200 and ar["queued"] <= 1, f"analyse my recent games queues at most n ({ar})")
    for j in api("GET", "/api/jobs")[1]["jobs"]:
        if j["state"] in ("queued", "running"):
            api("POST", f"/api/games/{urllib.parse.quote(j['id'])}/cancel")
    code, ts = api("GET", "/api/theory/search?q=" + urllib.parse.quote("caro kann"))
    check(code == 200 and ts["results"], "theory search over HTTP")
    code, ln = api("POST", "/api/line", {"fen": chess.STARTING_FEN, "moves": ["e2e4", "e7e5", "zzz", "g1f3"]})
    check(code == 200 and [x["san"] for x in ln["steps"]] == ["e4", "e5"], "a line of moves played out (stops at a bad one)")
    code, v = api("POST", "/api/variations", {"name": "test", "fen": chess.STARTING_FEN, "moves": ["e2e4", "e7e5", "g1f3"]})
    check(code == 200 and api("GET", "/api/variations")[1]["variations"][0]["san"] == ["e4", "e5", "Nf3"], "variation saved and listed")
    check(api("POST", "/api/variations", {"name": "x", "fen": chess.STARTING_FEN, "moves": ["e2e5"]})[0] == 400, "illegal variation refused")
    check(api("DELETE", f"/api/variations/{v['id']}")[0] == 200 and not api("GET", "/api/variations")[1]["variations"], "variation deleted")
    code, gm = api("POST", "/api/grade", {"fen": "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1", "uci": "a1a7", "record": False, "fastest": True})
    check(code == 200 and not gm["solved"] and not gm["mate_after"], "puzzle grading: a move that drops the mate is a miss")
    code, gm = api("POST", "/api/grade", {"fen": "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1", "uci": "a1a8", "record": False, "fastest": True})
    check(code == 200 and gm["solved"], "puzzle grading: the mate is solved")
    code, th = api("POST", "/api/threat", {"fen": "2q2rk1/p4rp1/3R4/2PB1p1p/2P3nP/PPQ3P1/1B6/4R1K1 w - - 0 33"})
    check(code == 200 and th.get("gain_cp") is None, f"threat: no pawn value against a mate score (was ~990 pawns; {th.get('gain_cp')})")
    code, pl = api("GET", "/api/plan")
    check(code == 200 and "enabled" in pl, "study plan over HTTP")
    code, op = api("GET", "/api/opponents")
    check(code == 200 and isinstance(op["opponents"], list), "opponents over HTTP")
    check(api("GET", "/api/opponents/" + urllib.parse.quote("nobody at all"))[0] == 404, "unknown opponent is a 404")
    code, cv = api("GET", "/api/convert")
    check(code == 200 and "queue" in cv and "maia" in cv, "convert queue over HTTP")
    code, pr = api("GET", "/api/practical?fen=" + urllib.parse.quote(chess.STARTING_FEN))
    check(code == 200 and "available" in pr, "practical move over HTTP")
    # V10: play against Maia (the fake lc0 stands in for Maia)
    import play as PLY  # noqa: E402
    os.makedirs(os.path.join(TMP, "maia"), exist_ok=True)
    open(os.path.join(TMP, "maia", "maia-1500.pb.gz"), "w").close()
    api("POST", "/api/settings", {"lc0_path": FAKE_LC0, "maia_dir": os.path.join(TMP, "maia")})
    code, po = api("GET", "/api/play")
    check(code == 200 and po["available"] and po["bands"] == [1500] and po["band"] == 1500, f"Play: finds lc0 and the Maia 1500 net ({po})")
    check(PLY.parse_clock("10+5") == (600, 5) and PLY.parse_clock("none") is None and PLY.parse_clock("x+y") is None, "Play: clock specs")
    n_before = len(api("GET", "/api/games")[1]["games"])
    code, g1 = api("POST", "/api/play/start", {"band": 1500, "color": "Black", "clock": "none"})
    check(code == 200 and g1["color"] == "Black" and g1["maia"] and len(g1["moves"]) == 1, "Play as Black: Maia moves first")
    check(api("POST", f"/api/play/{g1['id']}/move", {"uci": "a1a8"})[0] == 400, "Play: an illegal move is refused")
    import random as _r
    b, last = chess.Board(g1["fen"]), None
    for _ in range(400):
        code, last = api("POST", f"/api/play/{g1['id']}/move", {"uci": _r.choice(list(b.legal_moves)).uci()})
        if code != 200 or last["over"]:
            break
        b = chess.Board(last["fen"])
    over = (last or {}).get("over") or {}
    check(code == 200 and over.get("game_id") and over["result"] in ("1-0", "0-1", "1/2-1/2"), f"Play: a game runs to its end ({over.get('termination')})")
    gg = store.get_game(over.get("game_id", "")) or {}
    check(gg.get("source") == "maia" and gg.get("player_color") == "Black" and gg.get("black") != "Maia 1500" and gg.get("white") == "Maia 1500",
          "Play: the game is in the Library as vs Maia, your side known")
    check(not gg.get("analysed") and len(api("GET", "/api/games")[1]["games"]) == n_before + 1, "Play: saved, not analysed")
    check(api("POST", f"/api/play/{g1['id']}/move", {"uci": "e2e4"})[0] == 404, "Play: a finished game takes no more moves")
    check(all(x["id"] != gg.get("id") for x in store.list_games(record_only=True)) and any(x["id"] == gg.get("id") for x in store.list_games()),
          "Maia games stay out of Insights' games, not out of the Library")
    store.set_settings({"insights_include_maia": True})
    check(any(x["id"] == gg.get("id") for x in store.list_games(record_only=True)), "...unless Settings counts them")
    store.set_settings({"insights_include_maia": False})
    code, g2 = api("POST", "/api/play/start", {"band": 1500, "color": "White", "clock": "1+0"})
    code, r2 = api("POST", f"/api/play/{g2['id']}/move", {"uci": "e2e4", "spent": 61})
    check(code == 200 and r2["over"] and r2["over"]["termination"] == "time" and r2["over"]["outcome"] == "loss", "Play: running out of time loses")
    pg2 = chess.pgn.read_game(io.StringIO(store.game_pgn(r2["over"]["game_id"])))
    check(pg2.headers["TimeControl"] == "60+0" and "on time" not in pg2.headers["Termination"] and "time" in pg2.headers["Termination"], "Play: the PGN says how it ended")
    code, g3 = api("POST", "/api/play/start", {"band": 1500, "color": "White", "clock": "3+2"})
    code, r3 = api("POST", f"/api/play/{g3['id']}/move", {"uci": "e2e4", "spent": 5})
    check(code == 200 and r3["clocks"]["White"] == 177.0 and r3["maia"], f"Play: your clock books the time you took plus the increment ({r3.get('clocks')})")
    # V11: pause, a saved game, resume after a "restart"
    code, pz = api("POST", f"/api/play/{g3['id']}/pause", {"spent": 12})
    check(code == 200 and pz["paused"] and pz["pending"] == 12 and pz["sans"][0] == "e4", "Play: Pause keeps the time you'd used on this move")
    sv = api("GET", "/api/play")[1]["saved"]
    check(sv and sv["id"] == g3["id"] and sv["moves"] == 2, "Play: the paused game is saved and offered on Play")
    gr = PLY.Game.restore(PLY._saved())
    check(len(gr.board.move_stack) == 2 and gr.pending == 12 and gr.paused and gr.left[chess.WHITE] == 177.0, "Play: a saved game rebuilds after a restart (moves, clocks, the paused move)")
    gr.close()
    code, ru = api("POST", f"/api/play/{g3['id']}/resume")
    check(code == 200 and not ru["paused"] and ru["pending"] == 12, "Play: Resume carries on")
    code, r4 = api("POST", f"/api/play/{g3['id']}/move", {"uci": [m.uci() for m in chess.Board(ru["fen"]).legal_moves][0], "spent": 15})
    check(code == 200 and r4["clocks"]["White"] == 164.0, f"Play: the move after a pause books the time before and after it ({r4.get('clocks')})")
    rz = api("POST", f"/api/play/{g3['id']}/resign")[1]
    check(api("GET", "/api/play")[1]["saved"] is None, "Play: a finished game is no longer offered")
    pclk = chess.pgn.read_game(io.StringIO(store.game_pgn(rz["over"]["game_id"])))
    check(pclk.headers["Termination"].endswith("resignation") and list(pclk.mainline())[0].clock() == 177.0, "Play: resigning saves the game with its clocks")
    proc.stdin.close()
    proc.wait(5)
    check(proc.returncode is not None, "exits when the parent's pipe closes")
finally:
    if proc.poll() is None:
        proc.kill()
    shutil.rmtree(TMP, ignore_errors=True)

print()
if failures:
    print(f"{len(failures)} FAILED:"); [print("  -", f) for f in failures]; sys.exit(1)
print("all checks passed")
