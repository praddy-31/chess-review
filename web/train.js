// Chess Review V4 - Train: live engine lines, "what if" on the Review board,
// the analysis Board screen and Puzzles from your own games.
// Uses the helpers from app.js (api, $, $$, esc, S, R, VIEWS, toast, ...).
"use strict";

// ------------------------------------------------------------------ positions (legal moves, cached)
const POS = new Map();
async function getPos(fen) {
  if (POS.has(fen)) return POS.get(fen);
  const p = await api("POST", "/api/position", { fen });
  if (POS.size > 400) POS.clear();
  POS.set(fen, p);
  return p;
}
async function playLineFrom(fen, ucis) { return (await api("POST", "/api/line", { fen, moves: ucis })).steps; }
const turnOf = fen => fen.split(" ")[1] === "w" ? "White" : "Black";
const moveNo = fen => +fen.split(" ")[5] || 1;
// label for the move played FROM fen ("12." for White, "12..." for Black)
const labelFrom = fen => `${moveNo(fen)}${turnOf(fen) === "White" ? "." : "..."}`;

// ------------------------------------------------------------------ live engine lines
const LIVE = { fen: null, timer: null, data: null, cb: null, startTimer: null };
function liveWatch(fen, cb) {
  LIVE.cb = cb;
  if (LIVE.fen === fen) { if (LIVE.data) cb(LIVE.data); return; }
  LIVE.fen = fen; LIVE.data = null;
  clearTimeout(LIVE.timer); clearTimeout(LIVE.startTimer);
  cb(null);
  // a short wait so stepping quickly through moves doesn't restart the engine every keypress
  LIVE.startTimer = setTimeout(async () => {
    try {
      const d = await api("POST", "/api/live/start", { fen, multipv: 3 });
      if (LIVE.fen !== fen) return;
      LIVE.data = d; LIVE.cb && LIVE.cb(d);
      if (d.running) LIVE.timer = setTimeout(livePoll, 300);
    } catch (e) { if (LIVE.fen === fen) { LIVE.data = { error: e.message, lines: [] }; LIVE.cb && LIVE.cb(LIVE.data); } }
  }, 160);
}
async function livePoll() {
  const fen = LIVE.fen;
  if (!fen) return;
  try {
    const d = await api("GET", "/api/live?fen=" + encodeURIComponent(fen));
    if (LIVE.fen !== fen) return;
    if (!d.stale) { LIVE.data = d; LIVE.cb && LIVE.cb(d); }
    if (d.running || d.stale) LIVE.timer = setTimeout(livePoll, 450);
  } catch (e) { LIVE.timer = setTimeout(livePoll, 1500); }
}
function liveStop() {
  clearTimeout(LIVE.timer); clearTimeout(LIVE.startTimer);
  if (LIVE.fen) api("POST", "/api/live/stop").catch(() => {});
  LIVE.fen = null; LIVE.data = null; LIVE.cb = null;
}
// White's point of view, like the eval bar
const evalWhite = l => l.mate != null ? (l.mate > 0 ? 99 : -99) : (l.cp || 0) / 100;
const evalStr = l => l.mate != null ? (l.mate > 0 ? `#${l.mate}` : `#-${-l.mate}`) : `${l.cp > 0 ? "+" : l.cp < 0 ? "−" : ""}${Math.abs((l.cp || 0) / 100).toFixed(2)}`;

function liveHtml(d, opts = {}) {
  const cur = S.settings?.live_strength || "medium";
  const seg = `<span class="seg" role="group" aria-label="Engine strength">${[["low", "Low"], ["medium", "Medium"], ["high", "High"]].map(([k, l]) => `<button class="seg-b ${cur === k ? "on" : ""}" data-str="${k}" title="${STRENGTH_HELP[k]}">${l}</button>`).join("")}</span>`;
  const head = t => `<div class="ll-head"><span class="ll-title">Engine</span>${seg}${t}</div>`;
  if (!d) return head(`<span class="muted small">starting…</span>`) + `<div class="ll-body"><div class="ll skel"></div><div class="ll skel"></div><div class="ll skel"></div></div>`;
  if (d.error) return head("") + `<div class="ll-body"><span class="status-no small">${esc(d.error)}</span></div>`;
  if (d.game_over) return head("") + `<div class="ll-body"><span class="ink2">${d.reason === "checkmate" ? `Checkmate (${d.game_over})` : "Draw"}</span></div>`;
  const lines = d.lines || [];
  const status = `<span class="muted small">depth ${d.depth || 0}${d.target_depth ? ` of ${d.target_depth}` : ""}${d.running ? ` <span class="pulse" aria-label="thinking"></span>` : ""}</span>`;
  return head(status) + `<div class="ll-body">${lines.map((l, li) => `<div class="ll">
      <span class="ll-ev ${evalWhite(l) >= 0 ? "w" : "b"}">${evalStr(l)}</span>
      <span class="ll-moves">${l.san.slice(0, opts.max || 10).map((s, mi) => `<a class="ll-mv" data-li="${li}" data-mi="${mi}">${esc(s)}</a>`).join(" ")}</span></div>`).join("")
    || `<div class="ll skel"></div>`}</div>`;
}
const STRENGTH_HELP = { low: "Depth 14, 1 core, at most 15 s: cool and quiet", medium: "Depth 20, 2 cores, at most 45 s",
  high: "Depth 30, all the cores in Settings, at most 90 s: strongest, warms the Mac" };
// clicks on a move in an engine line: play the line up to it; the strength buttons restart the engine
function bindLive(el, onPlay) {
  el.onclick = e => {
    const sb = e.target.closest("[data-str]");
    if (sb) {
      S.settings.live_strength = sb.dataset.str;
      api("POST", "/api/settings", { live_strength: sb.dataset.str }).catch(() => {});
      const fen = LIVE.fen, cb = LIVE.cb;
      if (fen && cb) { LIVE.fen = null; liveWatch(fen, cb); }
      return;
    }
    const a = e.target.closest(".ll-mv");
    if (!a || !LIVE.data) return;
    const l = LIVE.data.lines[+a.dataset.li];
    if (l) onPlay(l.uci.slice(0, +a.dataset.mi + 1));
  };
}

// ================================================================== what if (Review board)
// Moving a piece on the Review board starts a side line from the position on
// the board; the live engine shows what it is worth. Esc goes back to the game.
function reviewPlayable() {
  if (!R.board || R.retry || R.line) return;
  const fen = R.board.state && R.board.state.fen;
  if (!fen) return;
  getPos(fen).then(p => {
    if (!R.board || R.board.state?.fen !== fen || R.retry || R.line) return;
    R.board.setMoves(p.moves, (uci, m) => whatifPlay(uci, m));
  }).catch(() => {});
}
function whatifPlay(uci, m) {
  const rv = S.review.review;
  if (!R.whatif) {
    const p = R.idx ? rv.plies[R.idx - 1] : null;
    const fen = R.board.state.fen;
    const before = p && shows_before(p) && fen === p.fen_before;
    R.whatif = { base: fen, gameMoves: before ? R.idx - 1 : R.idx, steps: [], pos: 0, eval0: R.shownEval };
  }
  const w = R.whatif;
  const from = w.pos ? w.steps[w.pos - 1].fen : w.base;
  w.steps = w.steps.slice(0, w.pos);
  w.steps.push({ uci, san: m.san, fen: m.fen, label: labelFrom(from) + m.san });
  w.pos = w.steps.length;
  R.whatifAnimate = true;
  draw();
}
function whatifFen() { const w = R.whatif; return w.pos ? w.steps[w.pos - 1].fen : w.base; }
function whatifGo(d) {
  const w = R.whatif;
  if (d === -1) { if (w.pos > 0) w.pos--; else { R.whatif = null; } }
  else if (d === 1 && w.pos < w.steps.length) { w.pos++; R.whatifAnimate = true; }
  draw();
}
function whatifCard() {
  const w = R.whatif;
  const chipsH = w.steps.map((s, i) => `<a class="mchip ${i + 1 === w.pos ? "cur" : ""}" data-wi="${i + 1}">${esc(i === 0 || turnOf(w.steps[i - 1].fen) === "White" ? s.label : s.san)}</a>`).join("");
  return `<div class="coach whatif">
    <div class="coach-head"><span class="mv-big">Your idea</span><span class="muted small">from ${esc(w.gameMoves ? S.review.review.plies[w.gameMoves - 1].label + S.review.review.plies[w.gameMoves - 1].san : "the start")}</span><span style="flex:1"></span>
      <span class="muted small">${turnOf(whatifFen())} to play</span></div>
    <div class="coach-rows"><span class="muted">Moves</span><span>${chipsH || `<span class="muted small">Move a piece on the board.</span>`}</span></div>
    <div class="live" id="wi-live">${liveHtml(LIVE.fen === whatifFen() ? LIVE.data : null)}</div>
    <div class="coach-actions">
      <button class="sm" id="wi-back">Back to the game (Esc)</button>
      <button class="sm" id="wi-board">Open on the Board</button>
      <span class="muted small">← → step through your line · click an engine move to play it</span>
    </div></div>`;
}
function bindWhatif() {
  const w = R.whatif;
  $$("[data-wi]").forEach(a => a.onclick = () => { w.pos = +a.dataset.wi; draw(); });
  if ($("#wi-back")) $("#wi-back").onclick = () => { R.whatif = null; draw(); };
  if ($("#wi-board")) $("#wi-board").onclick = () => openBoardFromReview();
  const box = $("#wi-live");
  if (box) bindLive(box, async ucis => {
    const fen = whatifFen();
    const steps = await playLineFrom(fen, ucis);
    w.steps = w.steps.slice(0, w.pos);
    let f = fen;
    for (const s of steps) { w.steps.push({ uci: s.uci, san: s.san, fen: s.fen, label: labelFrom(f) + s.san }); f = s.fen; }
    w.pos = w.steps.length; R.whatifAnimate = true; draw();
  });
  liveWatch(whatifFen(), d => {
    const el = $("#wi-live");
    if (el && R.whatif) el.innerHTML = liveHtml(d);
    if (d && d.lines && d.lines.length && R.whatif) {
      R.shownEval = evalWhite(d.lines[0]);
      paintEvalBar(R.shownEval, R.flipped);
      if (R.board && R.board.state && R.board.state.fen === whatifFen())
        R.board.state.arrows = [[d.lines[0].uci[0], cssv("--sev-best")]], R.board._overlay();
    }
  });
}
function paintEvalBar(e, flipped) {
  const bar = $("#evalbar");
  if (!bar) return;
  const white = winPct(e) / 100;
  bar.classList.toggle("flip", flipped);
  $("i", bar).style.height = ((flipped ? 1 - white : white) * 100) + "%";
  $("b", bar).textContent = Math.abs(e) >= 10 ? "M" : (e >= 0 ? "+" : "") + e.toFixed(1);
}
// Open the current Review position (and any what-if line) on the Board screen.
function openBoardFromReview() {
  const rv = S.review.review;
  const w = R.whatif;
  let upto;
  if (w) upto = w.gameMoves;
  else { const p = R.idx ? rv.plies[R.idx - 1] : null; upto = p && shows_before(p) ? R.idx - 1 : R.idx; }
  S.boardSeed = {
    fen: rv.start_fen, game: rv.plies.map(p => p.played_uci), at: upto,
    extra: w ? w.steps.slice(0, w.pos).map(s => s.uci) : [],
    flipped: R.flipped, title: `${rv.white} vs ${rv.black}`, game_id: S.review.id,
  };
  location.hash = "#/board";
}

// ================================================================== Board screen
const BV = { root: null, cur: null, flipped: false, board: null, title: "", game_id: null, engine: true, animate: false };
const mkNode = (fen, parent = null, step = null) => ({ fen, parent, kids: [], uci: step?.uci || null, san: step?.san || null,
  label: parent ? labelFrom(parent.fen) : "", opening: step?.opening || null });
// the deepest named opening on the way to a node (transpositions keep the last name)
function openingOf(n) { for (let x = n; x; x = x.parent) if (x.opening) return x.opening; return null; }
function addChild(node, step) {
  let k = node.kids.find(c => c.uci === step.uci);
  if (!k) { k = mkNode(step.fen, node, step); node.kids.push(k); }
  return k;
}
function pathTo(node) { const out = []; for (let n = node; n && n.parent; n = n.parent) out.unshift(n); return out; }

async function boardFromSeed(seed) {
  BV.root = mkNode(seed.fen);
  BV.title = seed.title || ""; BV.game_id = seed.game_id || null; BV.flipped = !!seed.flipped;
  let n = BV.root;
  const steps = seed.game?.length ? await playLineFrom(seed.fen, seed.game) : [];
  let atNode = BV.root;
  steps.forEach((s, i) => { n = addChild(n, s); n.game = true; if (i + 1 === seed.at) atNode = n; });
  if (!seed.at) atNode = BV.root;
  BV.cur = atNode;
  if (seed.extra?.length) {
    const ex = await playLineFrom(atNode.fen, seed.extra);
    let m = atNode;
    for (const s of ex) m = addChild(m, s);
    BV.cur = m;
  }
}

VIEWS.board = async function () {
  if (S.boardSeed) { const sd = S.boardSeed; S.boardSeed = null; await boardFromSeed(sd); }
  else if (!BV.root) { BV.root = mkNode("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"); BV.cur = BV.root; BV.title = ""; }
  const m = $("#main");
  m.innerHTML = `<div class="page page-wide">
    <div class="page-head rv-head"><div><div class="crumb">Board${BV.title ? ` / ${esc(BV.title)}` : ""}</div><h1>Analysis board</h1>
      <div class="small ink2" style="margin-top:2px">Play any moves; the engine follows along.${BV.game_id ? ` <a href="#/review/${encodeURIComponent(BV.game_id)}">Back to the review</a>` : ""}</div></div>
      <span class="spacer"></span><button class="ghost" id="bv-new">New board</button></div>
    <div class="rv">
      <div class="rv-left">
        <div class="boardwrap"><div class="evalbar" id="evalbar"><i></i><b></b></div><svg class="board" id="board" role="img" aria-label="Analysis board"></svg></div>
        <div class="navbar">
          <button class="nb" data-bgo="start" aria-label="Start" title="Start (Home)">⏮</button><button class="nb" data-bgo="-1" aria-label="Back" title="Back (←)">◀</button>
          <button class="nb" data-bgo="1" aria-label="Forward" title="Forward (→)">▶</button><button class="nb" data-bgo="end" aria-label="End" title="End of line (End)">⏭</button>
          <button class="nb" id="bv-flip" title="Flip (F)">Flip</button><button class="nb" id="bv-del" title="Delete this move and what follows (Delete)">Delete move</button>
          <span class="hint">drag or click to move · ← → · F flip</span>
        </div>
        <div class="card fenrow"><label class="muted small" for="bv-fen">FEN</label><input id="bv-fen" class="mono small" spellcheck="false"><button class="sm" id="bv-load">Load</button><button class="sm ghost" id="bv-copy">Copy</button></div>
      </div>
      <div class="rv-right">
        <div class="card live" id="bv-live"></div>
        <div class="bv-prac small" id="bv-prac" hidden></div>
        <div class="card"><div class="ll-head"><span class="ll-title">Moves</span><span class="muted small" id="bv-turn"></span></div><div class="opening-name" id="bv-opening"></div><div class="tree" id="bv-tree"></div>
          <div class="row" style="margin-top:10px;gap:8px"><input id="bv-name" placeholder="Name this line…" style="flex:1"><button class="sm" id="bv-save">Save line</button></div></div>
        <div class="card coach-ask" id="bv-coach"></div>
        <div class="card"><div class="ll-head"><span class="ll-title">Saved lines</span></div><div id="bv-saved" class="saved"></div></div>
      </div>
    </div></div>`;
  BV.board = new ChessBoard($("#board"));
  BV.board.pieces = S.settings.pieces || "cburnett";
  $$("[data-bgo]").forEach(b => b.onclick = () => bvGo(b.dataset.bgo === "start" || b.dataset.bgo === "end" ? b.dataset.bgo : +b.dataset.bgo));
  $("#bv-flip").onclick = () => { BV.flipped = !BV.flipped; bvDraw(); };
  $("#bv-del").onclick = bvDelete;
  $("#bv-new").onclick = () => { BV.root = mkNode("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"); BV.cur = BV.root; BV.title = ""; BV.game_id = null; VIEWS.board(); };
  $("#bv-load").onclick = async () => {
    const fen = $("#bv-fen").value.trim();
    try { const p = await api("POST", "/api/position", { fen }); BV.root = mkNode(p.fen); BV.cur = BV.root; BV.title = ""; BV.game_id = null; bvDraw(); }
    catch (e) { toast("That FEN isn't a legal position", true); }
  };
  $("#bv-fen").onkeydown = e => { if (e.key === "Enter") $("#bv-load").click(); };
  $("#bv-copy").onclick = () => copyText(BV.cur.fen);
  $("#bv-save").onclick = async () => {
    const path = pathTo(BV.cur);
    if (!path.length) return toast("Play some moves first");
    const name = $("#bv-name").value.trim() || `${BV.title || "Line"} · ${path[0].label}${path[0].san}`;
    try { await api("POST", "/api/variations", { name, fen: BV.root.fen, moves: path.map(n => n.uci), game_id: BV.game_id }); $("#bv-name").value = ""; toast("Line saved"); bvSaved(); }
    catch (e) { toast(e.message, true); }
  };
  bindLive($("#bv-live"), async ucis => {
    const steps = await playLineFrom(BV.cur.fen, ucis);
    let n = BV.cur;
    for (const s of steps) n = addChild(n, s);
    BV.cur = n; BV.animate = true; bvDraw();
  });
  document.onkeydown = e => {
    if (e.target.closest("input,textarea,select")) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key;
    if (k === "ArrowRight") bvGo(1); else if (k === "ArrowLeft") bvGo(-1);
    else if (k === "Home") bvGo("start"); else if (k === "End") bvGo("end");
    else if (k === "f") { BV.flipped = !BV.flipped; bvDraw(); }
    else if (k === "Delete" || k === "Backspace") bvDelete();
    else return;
    e.preventDefault();
  };
  bvDraw();
  bvSaved();
};
function bvGo(d) {
  if (d === "start") BV.cur = BV.root;
  else if (d === "end") { while (BV.cur.kids.length) BV.cur = BV.cur.kids[0]; }
  else if (d === -1) { if (BV.cur.parent) BV.cur = BV.cur.parent; }
  else if (d === 1 && BV.cur.kids.length) { BV.cur = BV.cur.kids[0]; BV.animate = true; }
  bvDraw();
}
function bvDelete() {
  const n = BV.cur;
  if (!n.parent) return;
  n.parent.kids = n.parent.kids.filter(k => k !== n);
  BV.cur = n.parent; bvDraw();
}
function bvDraw() {
  const n = BV.cur;
  BV.board.draw({ fen: n.fen, lastUci: n.uci, flipped: BV.flipped, animate: BV.animate });
  BV.animate = false;
  $("#bv-fen").value = n.fen;
  $("#bv-turn").textContent = `${turnOf(n.fen)} to play`;
  const op = openingOf(n);
  $("#bv-opening").textContent = op || (BV.root.fen.startsWith("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR") && n === BV.root ? "Starting position" : "");
  $("#bv-opening").title = op ? "Opening name from the Lichess list (by position)" : "";
  getPos(n.fen).then(p => {
    if (BV.cur !== n) return;
    BV.board.setMoves(p.moves, (uci, m) => { BV.cur = addChild(BV.cur, { uci, san: m.san, fen: m.fen, opening: m.opening }); BV.animate = true; bvDraw(); });
  }).catch(() => {});
  bvCoachCard(n);
  $("#bv-tree").innerHTML = BV.root.kids.length ? treeHtml(BV.root.kids[0], true) : `<span class="muted small">No moves yet. Drag a piece, or click it and then a square.</span>`;
  $$("#bv-tree [data-node]").forEach(a => a.onclick = () => { BV.cur = NODE_BY_ID.get(+a.dataset.node); bvDraw(); });
  bvPractical(n);
  const live = $("#bv-live");
  liveWatch(n.fen, d => {
    if (BV.cur !== n || !$("#bv-live")) return;
    live.innerHTML = liveHtml(d);
    if (d && d.lines && d.lines.length) {
      paintEvalBar(evalWhite(d.lines[0]), BV.flipped);
      BV.board.state.arrows = [[d.lines[0].uci[0], cssv("--sev-best")]]; BV.board._overlay();
    }
  });
}
// practical move under the engine lines (V8): waits until you stop on a position
let bvPracTimer = null;
function bvPractical(n) {
  const box = $("#bv-prac");
  if (!box) return;
  clearTimeout(bvPracTimer);
  box.hidden = true;
  if (typeof PRAC_OFF !== "undefined" && PRAC_OFF) return;
  const show = r => {
    if (BV.cur !== n || !$("#bv-prac")) return;
    if (!r || r === "pending" || r.same) { box.hidden = true; return; }
    box.hidden = false;
    box.innerHTML = `<span class="muted" title="The most likely move for players at your level that is within 5 points of win chance of the best">Practical</span> <a class="mchip" id="bv-prac-mv">${esc(r.san)}</a> ${r.p}% at your level${r.gap ? `, ${r.gap} points off ${esc(r.best_san)}` : ", as good as the best"} · ${esc(r.best_san)} is found by ${r.p_best}%`;
    $("#bv-prac-mv").onclick = () => { BV.board.state.arrows = [[r.uci, "#4a8fd4"]]; BV.board._overlay(); };
  };
  if (PRAC.has(n.fen)) return show(PRAC.get(n.fen));
  bvPracTimer = setTimeout(() => {
    if (BV.cur !== n) return;
    PRAC.set(n.fen, "pending");
    api("GET", "/api/practical?fen=" + encodeURIComponent(n.fen)).then(d => {
      if (!d.available) PRAC_OFF = true;
      PRAC.set(n.fen, d.practical || null); show(d.practical);
    }).catch(() => PRAC.delete(n.fen));
  }, 900);
}

// the move tree as text: main line, side lines in brackets
const NODE_BY_ID = new Map();
let nodeSeq = 0;
function nodeId(n) { if (!n._id) { n._id = ++nodeSeq; } NODE_BY_ID.set(n._id, n); return n._id; }
function treeHtml(start, top) {
  let h = "", n = start, needNum = true;
  while (n) {
    const white = turnOf(n.parent.fen) === "White";
    const num = white ? n.label : (needNum ? n.label : "");
    h += `<a class="tm ${n === BV.cur ? "cur" : ""}" data-node="${nodeId(n)}">${num ? `<span class="muted">${esc(num)}</span>` : ""}${esc(n.san)}</a> `;
    needNum = false;
    const sibs = n.parent.kids;
    if (sibs[0] === n && sibs.length > 1) {
      for (const v of sibs.slice(1)) h += `<span class="tv">(${treeHtml(v, false)})</span> `;
      needNum = true;
    }
    n = n.kids[0];
  }
  return top ? `<div class="tline">${h}</div>` : h.trim();
}
async function bvSaved() {
  const box = $("#bv-saved");
  if (!box) return;
  let vs = [];
  try { vs = (await api("GET", "/api/variations")).variations; } catch (e) {}
  box.innerHTML = vs.length ? vs.map(v => `<div class="sv"><a data-load="${v.id}"><b>${esc(v.name)}</b> <span class="muted small">${esc(v.san.slice(0, 6).join(" "))}${v.san.length > 6 ? " …" : ""}</span></a><button class="ghost sm" data-delv="${v.id}" aria-label="Delete">✕</button></div>`).join("")
    : `<span class="muted small">Lines you save show up here.</span>`;
  $$("[data-load]", box).forEach(a => a.onclick = async () => {
    const v = vs.find(x => x.id === +a.dataset.load);
    await boardFromSeed({ fen: v.fen, game: v.moves, at: v.moves.length, title: v.name, game_id: v.game_id });
    VIEWS.board();
  });
  $$("[data-delv]", box).forEach(b => b.onclick = async () => { await api("DELETE", `/api/variations/${b.dataset.delv}`); bvSaved(); });
}

// ================================================================== Puzzles
const PZ = { q: null, item: null, filter: { motif: "", kind: "" }, more: false, board: null };
const MOTIF_NAME = { "fork": "Fork", "pin": "Pin", "hanging piece": "Undefended piece", "material": "Win material", "mate": "Mate",
  "back-rank mate": "Back-rank mate", "discovered check": "Discovered check", "promotion": "Promotion", "advantage": "Better move" };
const ARROW = { best: () => cssv("--sev-best"), reply: () => "#7c8aa5", mine: () => cssv("--sev-mistake"), threat: () => cssv("--sev-blunder") };

const pzModes = cur => `<div class="tabs pz-modes" role="tablist"><a role="tab" href="#/puzzles" class="${cur === "puzzles" ? "on" : ""}">Puzzles</a><a role="tab" href="#/puzzles/convert" class="${cur === "convert" ? "on" : ""}">Convert the win</a></div>`;
VIEWS.puzzles = async function (arg) {
  if (arg === "convert") return cvView();
  const m = $("#main");
  m.innerHTML = `<div class="page page-wide pz-page">${pzModes("puzzles")}
    <div class="rv">
      <div class="rv-left">
        <div class="boardwrap"><svg class="board" id="board" role="img" aria-label="Puzzle board"></svg></div>
      </div>
      <div class="rv-right" id="pz-side"></div>
    </div></div>`;
  PZ.board = new ChessBoard($("#board"));
  PZ.board.pieces = S.settings.pieces || "cburnett";
  document.onkeydown = e => {
    if (e.target.closest("input,textarea,select")) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const p = PZ.item, k = e.key;
    if (k === "Enter" && p?.done) pzNext();
    else if ((k === "1" || k === "2") && p && p.asking) pzGuess(k === "1" ? "one" : "several");
    else if (k === "h" && p && !p.done && !p.locked && !p.asking) pzHint();
    else if (k === "r" && p?.locked) pzRetry();
    else if (k === "f") { PZ.board.flipped = !PZ.board.flipped; p?.done ? pzWhyDraw() : pzDraw(); }
    else if (p?.done && (k === "ArrowRight" || k === "ArrowLeft")) pzWhyStep(k === "ArrowRight" ? 1 : -1);
    else if (p?.done && k === "Home") pzWhyGo(0);
    else return;
    e.preventDefault();
  };
  await pzLoad();
};
async function pzLoad() {
  const f = PZ.filter;
  if (S.pzSet) { PZ.set = S.pzSet; S.pzSet = null; }
  const qs = new URLSearchParams({ motif: f.motif, kind: f.kind, more: PZ.more ? "1" : "0", ids: PZ.set ? PZ.set.ids.join(",") : "" });
  try { PZ.q = await api("GET", "/api/puzzles?" + qs); }
  catch (e) { $("#pz-side").innerHTML = `<div class="card status-no">${esc(e.message)}</div>`; return; }
  updatePuzzleBadge(PZ.q);
  pzStart(PZ.q.queue[0] || null);
}
function updatePuzzleBadge(q) {
  const b = $("#pz-badge");
  if (!b || !q) return;
  const left = Math.max(0, q.per_day - q.done_today);
  const avail = q.due_count + q.new_count;
  b.textContent = Math.min(left, avail);
  b.hidden = !Math.min(left, avail);
}
function pzStart(item) {
  clearInterval(PZ.tick);
  PZ.item = item ? { ...item, idx: 0, cur: item.fen, wrong: false, misses: 0, hints: 0, done: false, msg: null, last: item.last_uci,
    busy: false, locked: false, alt: null, why: item.why || null, view: null,
    asking: !!(PZ.q && PZ.q.ask_judgement), guess: null, truth: item.kind === "tactic" ? "one" : "several",
    clock: !!(PZ.q && PZ.q.clock && item.budget), t0: null, slow: false } : null;
  if (!item) { PZ.board.setMoves(null); PZ.board.draw({ fen: "8/8/8/8/8/8/8/8 w - - 0 1" }); pzSide(); return; }
  const flipped = item.color === "Black";
  // show the move that led here, then hand over
  if (item.prev_fen && item.last_uci) {
    PZ.board.draw({ fen: item.prev_fen, flipped });
    PZ.item.busy = true;
    pzSide();
    setTimeout(() => { if (!PZ.item || PZ.item.id !== item.id) return; PZ.item.busy = false; PZ.board.draw({ fen: item.fen, lastUci: item.last_uci, flipped, animate: true }); pzArm(); pzSide(); }, 450);
  } else { PZ.board.draw({ fen: item.fen, flipped }); pzArm(); pzSide(); }
}
function pzDraw(extra = {}) {
  const p = PZ.item;
  if (!p) return;
  PZ.board.draw({ fen: p.cur, lastUci: p.last, marks: p.marks || [], arrows: p.arrows || [], ...extra });
  pzArm();
}
function pzArm() {
  const p = PZ.item;
  if (!p || p.done || p.busy || p.locked || p.asking) { PZ.board.setMoves(null); return; }
  if (p.clock && !p.t0) pzClockStart(p);
  const fen = p.cur;
  getPos(fen).then(pos => { if (PZ.item === p && p.cur === fen && !p.done && !p.busy && !p.locked) PZ.board.setMoves(pos.moves, pzMove); });
}
async function pzMove(uci, m) {
  const p = PZ.item;
  if (!p || p.done || p.busy || p.locked) return;
  const want = p.solution[p.idx];
  p.marks = []; p.arrows = [];
  if (uci === want) {
    p.cur = m.fen; p.last = uci; p.idx++;
    p.msg = null;
    pzDraw({ animate: true });
    if (p.idx >= p.solution.length) return pzFinish();
    // their reply
    p.busy = true; pzSide();
    setTimeout(async () => {
      const [st] = await playLineFrom(p.cur, [p.solution[p.idx]]);
      if (PZ.item !== p) return;
      p.cur = st.fen; p.last = st.uci; p.idx++; p.busy = false;
      p.msg = { kind: "ok", text: `Good. They reply ${esc(st.san)}; keep going.` };
      if (p.idx >= p.solution.length) return pzFinish();
      pzDraw({ animate: true }); pzSide();
    }, 420);
    return;
  }
  // not the line's move: ask the engine whether it works just as well
  p.busy = true; p.msg = { kind: "wait", text: `Checking ${esc(m.san)}…` };
  const before = p.cur;
  p.cur = m.fen; p.last = uci; pzDraw({ animate: true }); pzSide();
  let res = null;
  try { res = await api("POST", "/api/grade", { fen: before, uci, record: false, fastest: true }); } catch (e) { toast(e.message, true); }
  if (PZ.item !== p) return;
  p.busy = false;
  if (res && res.solved) {
    p.alt = m.san;
    p.msg = { kind: "ok", text: `<b>${esc(m.san)}</b> works too${res.label === "Best" ? "" : ` (${Math.round(res.pp)} point${Math.round(res.pp) === 1 ? "" : "s"} off ${esc(p.solution_san[p.idx])})`}.` };
    return pzFinish();
  }
  // a slower mate isn't wrong, just not the puzzle's answer: take it back, no miss counted
  if (res && res.slower) {
    p.cur = before; p.last = null;
    p.msg = { kind: "hint", text: `<b>${esc(m.san)}</b> mates too, but slower (mate in ${res.mate_after + 1} instead of ${res.mate_before}). Find the fastest.` };
    pzDraw({ animate: false }); pzSide();
    return;
  }
  // a miss: leave the move on the board with their answer drawn, until you press Retry
  p.wrong = true; p.misses++;
  p.locked = true; p.retryFen = before;
  p.arrows = res && res.reply_uci ? [[res.reply_uci, ARROW.threat(), { label: "!" }]] : [];
  const reply = res?.reply_line?.length ? res.reply_line : [];
  p.msg = { kind: "no", text: res && res.mate_before && !res.mate_after ? `<b>${esc(m.san)}</b> isn't it: you had mate in ${res.mate_before}, and this lets it go.`
      + (reply.length ? ` The red arrow is their answer, <b>${esc(reply[0])}</b>.` : "")
    : res ? `<b>${esc(m.san)}</b> isn't it: ${res.label === "Good" ? "playable, but" : `a${res.label === "Inaccuracy" ? "n" : ""} ${res.label.toLowerCase()},`} it costs ${Math.round(res.pp)} point${Math.round(res.pp) === 1 ? "" : "s"} of win chance.`
    + (reply.length ? ` The red arrow is their answer, <b>${esc(reply[0])}</b>${reply.length > 1 ? ` (then ${esc(reply.slice(1, 4).join(" "))})` : ""}.` : "") : "That's not it." };
  pzDraw(); pzSide();
}
function pzRetry() {
  const p = PZ.item;
  if (!p || !p.locked) return;
  p.locked = false; p.cur = p.retryFen; p.last = null; p.arrows = []; p.msg = { kind: "hint", text: "Try again." };
  pzDraw({ animate: false }); pzSide();
}
function pzHint() {
  const p = PZ.item;
  if (!p || p.done || p.busy || p.locked) return;
  const want = p.solution[p.idx];
  p.hints = Math.max(p.hints, Math.min(3, p.hints + 1));
  const accent = cssv("--accent");
  if (p.hints === 1) { p.marks = [{ sq: want.slice(0, 2), color: accent }]; p.msg = { kind: "hint", text: "This piece moves." }; }
  else if (p.hints === 2) { p.marks = [{ sq: want.slice(0, 2), color: accent }, { sq: want.slice(2, 4), color: accent }]; p.msg = { kind: "hint", text: "From here to there." }; }
  else return pzShow();
  pzDraw(); pzSide();
}
async function pzShow() {
  const p = PZ.item;
  p.hints = 3; p.wrong = true; p.busy = true; p.marks = [];
  pzSide();
  const rest = p.solution.slice(p.idx);
  const steps = await playLineFrom(p.cur, rest);
  for (const st of steps) {
    if (PZ.item !== p) return;
    p.cur = st.fen; p.last = st.uci; p.idx++;
    p.arrows = [];
    pzDraw({ animate: true });
    await new Promise(r => setTimeout(r, 650));
  }
  p.busy = false;
  p.shown = true;
  pzFinish();
}
// V7 polish: a clock per puzzle (your per-move time for the game's time control, times your moves) - over time = slow, not a miss
function pzClockStart(p) {
  p.t0 = Date.now();
  clearInterval(PZ.tick);
  PZ.tick = setInterval(() => {
    if (PZ.item !== p || p.done) { clearInterval(PZ.tick); return; }
    const used = (Date.now() - p.t0) / 1000, left = p.budget - used;
    if (left <= 0 && !p.slow) { p.slow = true; pzSide(); }
    const el = $("#pz-clock");
    if (el) { el.querySelector("i").style.width = `${Math.max(0, Math.min(100, 100 * left / p.budget))}%`; el.querySelector("span").textContent = left > 0 ? `${Math.ceil(left)} s` : "over time"; el.classList.toggle("over", left <= 0); }
  }, 200);
}
function pzGuess(g) {
  const p = PZ.item;
  if (!p || !p.asking) return;
  p.guess = g; p.asking = false;
  pzSide(); pzArm();
}
async function pzFinish() {
  const p = PZ.item;
  p.done = true; PZ.board.setMoves(null); clearInterval(PZ.tick);
  const result = p.wrong || p.hints >= 3 ? "failed" : p.slow ? "slow" : "solved";
  p.result = result === "slow" ? "solved" : result;
  if (p.shown) p.msg = null;
  else if (!p.alt) p.msg = null;
  const judged = p.guess ? p.guess === p.truth : undefined;
  try { p.sched = await api("POST", `/api/puzzles/${encodeURIComponent(p.id)}/result`, { result, hints: p.hints, judged }); } catch (e) { toast(e.message, true); }
  if (judged !== undefined && PZ.q && PZ.q.judgement) { PZ.q.judgement.asked++; PZ.q.judgement.right += judged ? 1 : 0; }
  if (PZ.q) { PZ.q.done_today++; PZ.q.queue = PZ.q.queue.filter(x => x.id !== p.id); updatePuzzleBadge({ ...PZ.q, due_count: PZ.q.queue.length, new_count: 0 }); }
  pzSide();
  // the explanation: back to the puzzle position with the arrows, the line to step through, and their threat
  const line = (p.why?.line || []).slice(0, 10);
  const [steps, threat] = await Promise.all([
    line.length ? playLineFrom(p.fen, line.map(s => s.uci)).catch(() => []) : Promise.resolve([]),
    api("POST", "/api/threat", { fen: p.fen }).catch(() => null),
  ]);
  if (PZ.item !== p) return;
  p.view = { pos: 0, steps, threat: threat && threat.real && threat.uci && threat.uci !== p.solution[0] && !/mate/.test(p.motif || "") ? threat : null,   // you mate first: their threat doesn't matter
    show: { line: true, mine: true, threat: true } };
  setTimeout(() => { if (PZ.item === p) { pzWhyDraw(); pzSide(); } }, 700);
}

// --- after the puzzle: the start position with arrows, and the engine line to step through
function pzWhyArrows() {
  const p = PZ.item, v = p.view, out = [];
  if (!v) return out;
  if (v.pos === 0) {
    if (v.show.line) {
      const ln = v.steps.slice(0, 3);
      ln.forEach((s, i) => out.push([s.uci, i % 2 === 0 ? ARROW.best() : ARROW.reply(), { label: String(i + 1) }]));
    }
    const pl = p.why?.played;
    if (v.show.mine && pl?.uci && pl.uci !== p.solution[0]) out.push([pl.uci, ARROW.mine(), { label: "✗" }]);
    if (v.show.threat && v.threat) out.push([v.threat.uci, ARROW.threat(), { dash: true }]);
  } else {
    const s = v.steps[v.pos - 1];
    out.push([s.uci, (v.pos - 1) % 2 === 0 ? ARROW.best() : ARROW.reply()]);
    const nx = v.steps[v.pos];
    if (nx) out.push([nx.uci, v.pos % 2 === 0 ? ARROW.best() : ARROW.reply(), { dash: true }]);
  }
  return out;
}
function pzWhyDraw() {
  const p = PZ.item, v = p?.view;
  if (!v) return;
  const fen = v.pos === 0 ? p.fen : v.steps[v.pos - 1].fen;
  const last = v.pos === 0 ? p.last_uci : v.steps[v.pos - 1].uci;
  PZ.board.setMoves(null);
  PZ.board.draw({ fen, lastUci: last, arrows: pzWhyArrows(), animate: v.anim });
  v.anim = false;
}
function pzWhyGo(i) { const v = PZ.item?.view; if (!v) return; v.anim = i === v.pos + 1; v.pos = Math.max(0, Math.min(v.steps.length, i)); pzWhyDraw(); pzSide(); }
function pzWhyStep(d) { const v = PZ.item?.view; if (v) pzWhyGo(v.pos + d); }

function pzNext() { pzStart(PZ.q?.queue[0] || null); if (!PZ.q?.queue.length) pzLoad(); }
const dayWord = d => { const n = Math.round((new Date(d) - new Date(new Date().toISOString().slice(0, 10))) / 864e5); return n <= 1 ? "tomorrow" : `in ${n} days`; };

function pzWhyHtml(p) {
  const v = p.view, w = p.why || {};
  if (!v) return `<div class="pz-why muted small">Working out why…</div>`;
  const chipsH = v.steps.map((s, i) => {
    const fb = i === 0 ? p.fen : v.steps[i - 1].fen;
    const lab = i === 0 || turnOf(fb) === "White" ? labelFrom(fb) : "";
    return `<a class="mchip ${i + 1 === v.pos ? "cur" : ""} ${i < p.solution.length ? "strong" : ""}" data-pw="${i + 1}">${esc(lab + s.san)}</a>`;
  }).join("");
  const sw = (k, label, color, on) => `<button class="sm ghost pw-sw ${on ? "on" : ""}" data-sw="${k}"><i style="background:${color}"></i>${label}</button>`;
  const pl = w.played;
  return `<div class="pz-why">
    <div class="pw-row"><span class="pw-k" style="color:${ARROW.best()}">Why</span><span>${esc(w.best || `${p.solution_san[0]} is the move.`)}</span></div>
    ${pl && pl.text ? `<div class="pw-row"><span class="pw-k" style="color:${ARROW.mine()}">${p.source === "mine" ? "In the game" : "Their move"}</span><span>${esc(pl.text)}</span></div>` : ""}
    ${v.threat ? `<div class="pw-row"><span class="pw-k" style="color:${ARROW.threat()}">Threat</span><span>If it were their move: <b>${esc(v.threat.san)}</b>${v.threat.mate ? `, mate in ${v.threat.mate}` : v.threat.text ? `, which ${esc(v.threat.text.replace(/^\S+\s/, ""))}` : v.threat.gain_cp != null ? `, worth about ${(v.threat.gain_cp / 100).toFixed(1)} pawns to them` : ""}.</span></div>` : ""}
    <div class="pw-row"><span class="pw-k">Line</span><span>${chipsH || `<span class="muted small">no engine line stored</span>`}</span></div>
    <div class="pw-ctl">
      <button class="sm ghost" id="pw-start" ${v.pos === 0 ? "disabled" : ""}>Start position</button>
      ${v.pos === 0 ? `${sw("line", "Line (1, 2, 3)", ARROW.best(), v.show.line)}${pl?.uci && pl.uci !== p.solution[0] ? sw("mine", "Your move", ARROW.mine(), v.show.mine) : ""}${v.threat ? sw("threat", "Their threat", ARROW.threat(), v.show.threat) : ""}` : `<span class="muted small">move ${v.pos} of ${v.steps.length} · ← →</span>`}
    </div></div>`;
}

function pzSide() {
  const side = $("#pz-side");
  if (!side) return;
  const q = PZ.q || { per_day: 10, done_today: 0, queue: [], motifs: {}, kinds: {} };
  const p = PZ.item;
  const total = Math.max(q.per_day, q.done_today + (PZ.more ? q.queue.length : 0));
  const dots = Array.from({ length: Math.min(total, 30) }, (_, i) => `<i class="${i < q.done_today ? "done" : i === q.done_today && p && !p.done ? "now" : ""}"></i>`).join("");
  const filters = PZ.set ? `<div class="pz-filters"><span class="tag rep">Practising: ${esc(PZ.set.title)}</span><a class="small" id="pz-allset">all puzzles</a></div>` : `<div class="pz-filters">
      <select id="pz-motif" aria-label="Theme"><option value="">All themes</option>${Object.entries(q.motifs || {}).map(([k, n]) => `<option value="${esc(k)}" ${PZ.filter.motif === k ? "selected" : ""}>${esc(MOTIF_NAME[k] || k)} (${n})</option>`).join("")}</select>
      <select id="pz-kind" aria-label="Kind"><option value="">Tactics and better moves</option><option value="tactic" ${PZ.filter.kind === "tactic" ? "selected" : ""}>Tactics only</option><option value="better" ${PZ.filter.kind === "better" ? "selected" : ""}>Better moves only</option></select>
    </div>`;
  if (!p) {
    const none = !q.total;
    side.innerHTML = `<div class="pz-card card">
      <div class="pz-top"><span class="pz-title">Puzzles</span><span class="muted small">${q.done_today} of ${q.per_day} today${q.streak ? ` · ${q.streak}-day streak` : ""}</span></div>
      <div class="pz-dots">${dots}</div>
      ${none ? `<h2>No puzzles yet</h2><p class="muted">They are built from your analysed games: your mistakes${q.include_opponent ? ", and the moment after your opponent's mistakes" : ""}. Analyse a few games in the Library and come back.</p><a class="btn" href="#/library">Open the Library</a>`
        : `<h2>${q.done_today >= q.per_day ? "Done for today" : "Nothing due right now"}</h2>
           <p class="muted">${q.due_count + q.new_count ? "You've reached today's number." : "Every puzzle is scheduled for a later day."} Missed ones come back tomorrow; solved ones later and later.</p>
           ${q.due_count + q.new_count || q.new_count ? `<button class="primary" id="pz-more">Keep going</button>` : ""}`}
      <div class="muted small" style="margin-top:12px">${q.total} puzzles from your games. Per-day number in <a href="#/settings">Settings</a>.</div>
    </div>${q.total ? filters : ""}`;
    if ($("#pz-more")) $("#pz-more").onclick = () => { PZ.more = true; pzLoad(); };
    bindPzFilters();
    return;
  }
  const g = p.game || {};
  const you = p.color;
  const sevG = { Blunder: "??", Mistake: "?", Inaccuracy: "?!" }[p.severity] || "";
  const ctx = p.source === "mine"
    ? `You played <b>${esc(p.label + p.played_san)}</b>${sevG ? ` <span class="sev-inline" style="color:${sevColor(p.severity)}">${sevG}</span>` : ""} here${p.kind === "better" && (p.done || !(PZ.q && PZ.q.ask_judgement)) ? (/mate/.test(p.motif || "") ? " - more than one move mates, find one" : " - several moves are fine, find one") : PZ.q && PZ.q.ask_judgement && !p.done ? " - find a better move" : ""}.`
    : `${esc(g.opponent || "Your opponent")} just played <b>${esc(p.played_san)}</b>${sevG ? ` <span class="sev-inline" style="color:${sevColor(p.severity)}">${sevG}</span>` : ""}. Punish it.`;
  const msg = p.msg ? `<div class="pz-msg ${p.msg.kind}">${p.msg.text}</div>` : "";
  // found it (perhaps after misses) = green; only giving up shows "Not this time"
  let head;
  if (!p.done) head = `<span class="pz-turn"><span class="side ${you}"></span>${you} to play</span>`;
  else if (p.shown) head = `<span class="pz-res no">Not this time</span>`;
  else if (p.misses) head = `<span class="pz-res ok">Solved</span><span class="tag">on try ${p.misses + 1}</span>`;
  else head = `<span class="pz-res ok">Solved</span>${p.hints ? `<span class="tag">with a hint</span>` : ""}`;
  if (p.slow) head += `<span class="tag">over time</span>`;
  const jd = PZ.q && PZ.q.judgement;
  const judge = p.asking ? `<div class="pz-judge"><div><b>Before you move:</b> is there one critical move here, or are several moves fine?</div>
        <div class="row" style="gap:8px"><button class="sm" id="pz-one">One move (1)</button><button class="sm" id="pz-several">Several are fine (2)</button></div></div>`
    : p.guess && p.done ? `<div class="pz-msg ${p.guess === p.truth ? "ok" : "no"}">${p.guess === p.truth ? "Good judgement" : "Not quite"}: ${p.truth === "one" ? "only one move works here" : "several moves are fine here"}.${jd && jd.asked ? ` <span class="muted small">${jd.right} of ${jd.asked} right so far</span>` : ""}</div>`
    : p.guess ? `<div class="muted small">You said: ${p.guess === "one" ? "one critical move" : "several are fine"}.</div>` : "";
  const clock = p.clock && !p.done && !p.asking ? `<div class="pz-clock" id="pz-clock"><i></i><span>${Math.ceil(p.budget)} s</span></div>` : "";
  const back = !p.sched ? "" : p.result === "solved"
    ? `Back ${dayWord(p.sched.due)}${p.slow ? " (over time, so soon)" : p.hints ? " (you used a hint, so soon)" : ""}.`
    : p.shown ? "Back tomorrow." : "Back tomorrow, since it took more than one try.";
  side.innerHTML = `<div class="pz-card card">
      <div class="pz-top"><span class="pz-title">Puzzle ${Math.min(q.done_today + (p.done ? 0 : 1), total)} of ${total}</span><span class="muted small">${q.streak ? `${q.streak}-day streak` : ""}</span></div>
      <div class="pz-dots">${dots}</div>
      <div class="pz-head">${head}<span style="flex:1"></span>${p.motif && p.done ? `<span class="tag">${esc(MOTIF_NAME[p.motif] || p.motif)}</span>` : ""}${p.from_retry ? `<span class="tag">your retry</span>` : ""}</div>
      <p class="pz-ctx">${ctx}</p>
      ${judge}${clock}
      ${msg}
      ${p.done ? `${pzWhyHtml(p)}<div class="pz-after">
          <div class="muted small">${back}</div>
          <div class="row" style="gap:8px;margin-top:12px"><button class="primary" id="pz-next">Next puzzle (Enter)</button>
          <button id="pz-game">Open in the game</button><button class="ghost" id="pz-board">Analyse on the Board</button></div></div>`
      : p.locked ? `<div class="pz-hints"><button class="primary sm" id="pz-retry">Retry (R)</button><button class="sm ghost" id="pz-give">Show the answer</button><span class="muted small">take your time - the board waits</span></div>`
      : `<div class="pz-hints">
          <button class="sm" id="pz-hint" ${p.busy ? "disabled" : ""}>${["Hint: which piece", "Hint: which square", "Show the answer"][Math.min(2, p.hints)]}</button>
          <span class="ladder">${[0, 1, 2].map(i => `<i class="${i < p.hints ? "on" : ""}"></i>`).join("")}</span>
          <span class="muted small">H for a hint</span></div>`}
      <div class="pz-src muted small">From your game vs ${esc(g.opponent || "?")}${g.date ? ` · ${esc(g.date)}` : ""} · move ${esc(p.label.replace(/\.+$/, ""))}</div>
    </div>${filters}`;
  if ($("#pz-hint")) $("#pz-hint").onclick = pzHint;
  if ($("#pz-retry")) $("#pz-retry").onclick = pzRetry;
  if ($("#pz-give")) $("#pz-give").onclick = () => { pzRetry(); p.hints = 2; pzShow(); };
  if ($("#pz-next")) $("#pz-next").onclick = pzNext;
  if ($("#pz-one")) $("#pz-one").onclick = () => pzGuess("one");
  if ($("#pz-several")) $("#pz-several").onclick = () => pzGuess("several");
  if ($("#pz-game")) $("#pz-game").onclick = () => { S.reviewJump = { id: p.game_id, ply: p.ply }; location.hash = `#/review/${encodeURIComponent(p.game_id)}`; };
  if ($("#pz-board")) $("#pz-board").onclick = async () => {
    const ext = p.view?.steps?.length ? p.view.steps.map(s => s.uci) : p.solution;
    S.boardSeed = { fen: p.fen, game: [], at: 0, extra: ext, flipped: p.color === "Black", title: `Puzzle vs ${g.opponent || "?"}`, game_id: p.game_id };
    location.hash = "#/board";
  };
  $$("[data-pw]", side).forEach(a => a.onclick = () => pzWhyGo(+a.dataset.pw));
  if ($("#pw-start")) $("#pw-start").onclick = () => pzWhyGo(0);
  $$("[data-sw]", side).forEach(b => b.onclick = () => { const v = p.view; v.show[b.dataset.sw] = !v.show[b.dataset.sw]; pzWhyDraw(); pzSide(); });
  bindPzFilters();
}
function bindPzFilters() {
  if ($("#pz-allset")) $("#pz-allset").onclick = () => { PZ.set = null; PZ.more = false; pzLoad(); };
  if ($("#pz-motif")) $("#pz-motif").onchange = e => { PZ.filter.motif = e.target.value; PZ.more = false; pzLoad(); };
  if ($("#pz-kind")) $("#pz-kind").onchange = e => { PZ.filter.kind = e.target.value; PZ.more = false; pzLoad(); };
}

// the nav badge: puzzles left today
async function refreshPuzzleBadge() { try { updatePuzzleBadge(await api("GET", "/api/puzzles")); } catch (e) {} }


// ------------------------------------------------------------------ V7: ask the coach (engine facts about the position, optionally in words by a local Ollama model)
const COACH = { key: null, busy: false, res: null, err: null, chat: [], chatBusy: false };
const QUICK = [["threats", "What's their threat?"], ["plan", "What's the plan?"], ["changes", "Why is the best move better?"], ["position", "What matters in this position?"], ["level", "What do players at my level play?"]];
function bvCoachCard(n) {
  const box = $("#bv-coach");
  if (!box) return;
  const parent = n.parent;
  const key = (parent ? parent.fen : n.fen) + "|" + (n.uci || "");
  if (COACH.key !== key && !COACH.busy) { COACH.key = key; COACH.res = null; COACH.err = null; COACH.chat = []; }
  const mv = parent ? `${labelFrom(parent.fen)}${n.san}` : null;
  const r = COACH.res, words = !!(S.settings.coach_ollama && S.settings.coach_model);
  const sec = sc => `<div class="co-sec" data-sec="${sc.key}"><div class="co-sec-t">${esc(sc.title)}</div><ul>${sc.lines.map(l => `<li>${esc(l)}</li>`).join("")}</ul></div>`;
  box.innerHTML = `<div class="ll-head"><span class="ll-title">Ask the coach</span><span class="muted small">${words ? `engine facts, in words by ${esc(S.settings.coach_model)}` : "engine facts about the position"}</span></div>
    <div class="row coach-q">${mv ? `<button class="sm primary" id="co-last" ${COACH.busy ? "disabled" : ""}>Why ${esc(mv)}?</button><span class="muted small">or</span>` : ""}
      <input id="co-move" placeholder="a move, e.g. Nf3" style="width:130px" ${COACH.busy ? "disabled" : ""}><input id="co-q" placeholder="your question (optional)" style="flex:1;min-width:120px" ${COACH.busy ? "disabled" : ""}><button class="sm" id="co-go" ${COACH.busy ? "disabled" : ""}>Ask</button></div>
    ${COACH.busy ? `<div class="muted small"><span class="spin"></span> Stockfish is looking at the move, the best move and the threats${words ? ", then the model writes it up" : ""}… (about 10 seconds)</div>` : ""}
    ${COACH.err ? `<div class="status-no small">${esc(COACH.err)}</div>` : ""}
    ${r ? `${r.text ? `<div class="coach-text">${esc(r.text).replace(/\n+/g, "<br>")}</div>` : ""}
      ${r.note ? `<div class="small muted">${esc(r.note)}</div>` : ""}
      <div class="co-quick">${QUICK.filter(([k]) => r.sections.some(x => x.key === k)).map(([k, l]) => `<button class="chip" data-quick="${k}">${l}</button>`).join("")}</div>
      ${COACH.chat.map(c => `<div class="co-chat"><div class="co-q-t">${esc(c.q)}</div>${c.a ? `<div class="coach-text">${esc(c.a).replace(/\n+/g, "<br>")}</div>` : c.pending ? `<div class="muted small"><span class="spin"></span> thinking…</div>` : ""}${c.note ? `<div class="small muted">${esc(c.note)}</div>` : ""}</div>`).join("")}
      ${words ? `<div class="row coach-q"><input id="co-follow" placeholder="Ask a follow-up about this position…" style="flex:1" ${COACH.chatBusy ? "disabled" : ""}><button class="sm" id="co-send" ${COACH.chatBusy ? "disabled" : ""}>Ask</button></div>` : ""}
      <div class="co-secs ${r.text ? "quiet" : ""}">${r.sections.map(sec).join("")}</div>
      <div class="row" style="gap:6px">${r.best_uci && r.best_uci !== r.asked_uci ? `<button class="sm" id="co-best">Play the best move, ${esc(r.best)}</button>` : ""}${r.reply_uci ? `<button class="sm ghost" id="co-reply">Show their reply</button>` : ""}${r.threat_uci ? `<button class="sm ghost" id="co-threat">Show their threat</button>` : ""}</div>` : ""}`;
  const gameMove = base => { const k = BV.game_id && base.kids.find(x => x.game); return k ? { played_san: k.san } : null; };
  const ask = async (base, uci, from) => {
    COACH.busy = true; COACH.err = null; COACH.res = null; COACH.chat = []; bvCoachCard(BV.cur);
    try { COACH.res = { ...(await api("POST", "/api/coach/ask", { fen: base.fen, uci, question: $("#co-q") ? $("#co-q").value : "", game: gameMove(base) })), asked_uci: uci, from }; }
    catch (e) { COACH.err = e.message; }
    COACH.busy = false;
    COACH.key = (BV.cur.parent ? BV.cur.parent.fen : BV.cur.fen) + "|" + (BV.cur.uci || "");
    bvCoachCard(BV.cur);
  };
  if ($("#co-last")) $("#co-last").onclick = () => ask(parent, n.uci, "last");
  const typed = async () => {
    const t = ($("#co-move").value || "").trim().replace(/[!?]+$/, "");
    if (!t) return;
    const p = await getPos(n.fen);
    const m = p.moves.find(x => x.san === t || x.san.replace(/[+#]/g, "") === t.replace(/[+#]/g, "") || x.uci === t.toLowerCase());
    if (!m) { COACH.err = `${t} isn't a legal move here (${turnOf(n.fen)} to play)`; return bvCoachCard(n); }
    ask(n, m.uci, "typed");
  };
  $("#co-go").onclick = () => ($("#co-move").value.trim() ? typed() : mv ? ask(parent, n.uci, "last") : null);
  $("#co-move").onkeydown = e => { if (e.key === "Enter") typed(); };
  if (!r) return;
  const follow = async q => {
    if (!q.trim()) return;
    const item = { q, pending: true };
    COACH.chat.push(item); COACH.chatBusy = true; bvCoachCard(BV.cur);
    try {
      const x = await api("POST", "/api/coach/chat", { facts: r.facts, history: COACH.chat.filter(c => c.a).map(c => ({ q: c.q, a: c.a })), question: q });
      item.a = x.text; item.note = x.note;
    } catch (e) { item.note = e.message; }
    item.pending = false; COACH.chatBusy = false; bvCoachCard(BV.cur);
    const f = $("#co-follow"); if (f) f.focus();
  };
  $$("[data-quick]", box).forEach(b => b.onclick = () => {
    const k = b.dataset.quick;
    if (words) return follow(b.textContent);
    const el = box.querySelector(`[data-sec="${k}"]`);           // without a model: point at the section that answers it
    $$(".co-sec", box).forEach(x => x.classList.toggle("hl", x === el));
    if (el) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
  });
  if ($("#co-send")) $("#co-send").onclick = () => follow($("#co-follow").value);
  if ($("#co-follow")) $("#co-follow").onkeydown = e => { if (e.key === "Enter") follow(e.target.value); };
  const base = () => (r.from === "last" ? BV.cur.parent : BV.cur);
  if ($("#co-best")) $("#co-best").onclick = async () => { const b0 = base(); const [st] = await playLineFrom(b0.fen, [r.best_uci]); BV.cur = addChild(b0, st); BV.animate = true; bvDraw(); };
  if ($("#co-reply")) $("#co-reply").onclick = async () => { const b0 = base(); const steps = await playLineFrom(b0.fen, [r.asked_uci, r.reply_uci]); let x = b0; for (const st of steps) x = addChild(x, st); BV.cur = x; BV.animate = true; bvDraw(); };
  if ($("#co-threat")) $("#co-threat").onclick = () => {
    const b0 = base(); const t = r.threat_uci;
    BV.board.draw({ fen: b0.fen, lastUci: null, flipped: BV.flipped, arrows: [[t, cssv("--sev-blunder"), { label: "!" }]] });
  };
}


// ------------------------------------------------------------------ V8: convert the win (winning positions you didn't win, against Maia)
const CV = { q: null, d: null, s: null, board: null, busy: false, moves: [], res: null, win: null };
async function cvView() {
  const m = $("#main");
  m.innerHTML = `<div class="page page-wide pz-page">${pzModes("convert")}
    <div class="rv"><div class="rv-left"><div class="boardwrap"><svg class="board" id="board" role="img" aria-label="Convert board"></svg></div><div class="op-path" id="cv-path"></div></div>
      <div class="rv-right" id="cv-side"></div></div></div>`;
  CV.board = new ChessBoard($("#board")); CV.board.pieces = S.settings.pieces || "cburnett";
  document.onkeydown = e => { if (e.target.closest("input,textarea,select")) return; if (e.key === "Enter" && CV.res) { cvNext(); e.preventDefault(); } };
  await cvLoad();
}
async function cvLoad(more) {
  try { CV.q = await api("GET", "/api/convert" + (more ? "?more=1" : "")); } catch (e) { $("#cv-side").innerHTML = `<div class="card status-no">${esc(e.message)}</div>`; return; }
  CV.d = CV.q.queue[0] || null; CV.s = null; CV.res = null; CV.moves = [];
  cvIntro();
}
function cvNext() { if (CV.q) { CV.q.queue = CV.q.queue.filter(x => !CV.d || x.id !== CV.d.id); CV.q.done_today++; } CV.d = CV.q && CV.q.queue[0] || null; CV.s = null; CV.res = null; CV.moves = []; cvIntro(); }
const cvPct = w => `<div class="cv-win"><i style="width:${w}%"></i><span>${w}% win chance</span></div>`;
function cvIntro() {
  const side = $("#cv-side"), q = CV.q, d = CV.d;
  if (!side) return;
  if (!d) {
    CV.board.setMoves(null); CV.board.draw({ fen: "8/8/8/8/8/8/8/8 w - - 0 1" }); $("#cv-path").innerHTML = "";
    side.innerHTML = `<div class="pz-card card"><div class="pz-top"><span class="pz-title">Convert the win</span><span class="muted small">${q.done_today} of ${q.per_day} today</span></div>
      <h2>${q.total ? (q.done_today >= q.per_day ? "Done for today" : "Nothing due right now") : "No lost wins yet"}</h2>
      <p class="muted">${q.total ? "Drills you converted come back later and later; the ones that slipped come back tomorrow." : "When an analysed game had you at +3 or better and you didn't win, the position turns up here to play out again."}</p>
      ${q.due_count + q.new_count ? `<button class="primary" id="cv-more">Keep going</button>` : ""}</div>`;
    if ($("#cv-more")) $("#cv-more").onclick = () => cvLoad(true);
    return;
  }
  const flipped = d.color === "Black";
  CV.board.setMoves(null); CV.board.draw({ fen: d.fen, flipped }); $("#cv-path").innerHTML = "";
  const ev = d.start_cp >= 10000 ? "a forced mate" : `+${(d.start_cp / 100).toFixed(1)}`;
  side.innerHTML = `<div class="pz-card card"><div class="pz-top"><span class="pz-title">Convert the win</span><span class="muted small">${q.done_today} of ${q.per_day} today</span></div>
    <div class="pz-head"><span class="pz-turn"><span class="side ${d.color}"></span>${d.color} to play</span>${d.last_result ? `<span class="tag">last time: ${esc(d.last_result)}</span>` : ""}</div>
    <p class="pz-ctx">You were ${ev} against <b>${esc(d.opponent || "?")}</b>${d.opp_elo ? ` (${d.opp_elo})` : ""} on ${esc((d.played_at || "").slice(0, 10))}, and ${d.outcome === "draw" ? "drew" : "lost"}. Win it this time.</p>
    <p class="muted small">${q.maia ? `The defender is Maia at their rating: it plays like a human, and not the same way twice.` : `Maia isn't installed, so the defender is Stockfish held to their rating (Setup shows how to add Maia).`} Stockfish judges: win when it says 95%+ (or mate), and it slips under 60%.</p>
    <div class="row" style="gap:8px"><button class="primary" id="cv-go">Play it out</button><button class="ghost" id="cv-skip">Skip</button><a class="small" href="#/review/${encodeURIComponent(d.game_id)}">your game</a></div></div>`;
  $("#cv-go").onclick = cvStart;
  $("#cv-skip").onclick = () => { CV.q.queue.push(CV.q.queue.shift()); CV.d = CV.q.queue[0]; cvIntro(); };
}
async function cvStart() {
  const d = CV.d;
  $("#cv-go").disabled = true; $("#cv-go").textContent = "Starting the engines…";
  try { CV.s = await api("POST", `/api/convert/${encodeURIComponent(d.id)}/start`); } catch (e) { toast(e.message, true); cvIntro(); return; }
  CV.fen = CV.s.fen; CV.win = CV.s.win; CV.moves = []; CV.last = null;
  cvDraw(); cvSide();
}
function cvDraw(anim) {
  const flipped = CV.d.color === "Black";
  CV.board.draw({ fen: CV.fen, lastUci: CV.last, flipped, animate: anim });
  CV.board.setMoves(null);
  $("#cv-path").innerHTML = CV.moves.map(x => `<span class="mchip ${x.by === "you" && x.drop >= 8 ? "slip" : ""}" title="${x.win}% after it">${esc(x.san)}</span>`).join("");
  if (CV.res || CV.busy) return;
  const f = CV.fen;
  getPos(f).then(p => { if (CV.fen === f && !CV.busy && !CV.res) CV.board.setMoves(p.moves, cvMove); }).catch(() => {});
}
async function cvMove(uci, m) {
  if (CV.busy) return;
  CV.busy = true; CV.fen = m.fen; CV.last = uci; cvDraw(true); cvSide();
  let r;
  try { r = await api("POST", `/api/convert/${encodeURIComponent(CV.d.id)}/move`, { uci }); }
  catch (e) { toast(e.message, true); CV.busy = false; return cvIntro(); }
  CV.moves.push(r.you);
  if (r.reply) { CV.moves.push(r.reply); }
  CV.win = r.win;
  if (r.reply) { await new Promise(res => setTimeout(res, 250)); CV.fen = r.fen; CV.last = r.reply.uci; }
  CV.busy = false;
  if (r.status) CV.res = r.summary;
  cvDraw(true); cvSide();
}
function cvSide() {
  const side = $("#cv-side"), d = CV.d, r = CV.res;
  if (!side) return;
  const mine = CV.moves.filter(x => x.by === "you").length;
  const word = { won: "Converted", slipped: "The win slipped", drawn: "It ended in a draw", lost: "Lost", unfinished: "Not finished", "gave up": "You stopped" };
  side.innerHTML = `<div class="pz-card card"><div class="pz-top"><span class="pz-title">Convert the win</span><span class="muted small">vs ${esc(CV.s.defender || "")}</span></div>
    ${cvPct(CV.win ?? 0)}
    ${!r ? `<div class="pz-msg">${CV.busy ? "They're thinking…" : `Your move. ${mine ? `${mine} played.` : ""}`}</div>
      <div class="row" style="gap:8px"><button class="sm ghost" id="cv-stop">Give up</button></div>`
      : `<div class="pz-head"><span class="pz-res ${r.won ? "ok" : "no"}">${word[r.status] || r.status}</span><span class="muted small">${mine} of your moves</span></div>
        ${r.worst ? `<div class="pz-msg no">Your costliest move: <b>${esc(r.worst.san)}</b> (−${r.worst.drop} points of win chance, down to ${r.worst.win}%).</div>` : r.won ? `<div class="pz-msg ok">Clean: no move of yours gave away more than a few points.</div>` : ""}
        <div class="muted small">${r.won ? `Back in ${Math.max(1, Math.round((new Date(r.due) - new Date()) / 864e5))} days.` : "Back tomorrow."} <a href="#/review/${encodeURIComponent(d.game_id)}">Compare with your game</a></div>
        <div class="row" style="gap:8px"><button class="primary" id="cv-next">Next (Enter)</button></div>`}
  </div>`;
  if ($("#cv-stop")) $("#cv-stop").onclick = async () => { CV.res = await api("POST", `/api/convert/${encodeURIComponent(d.id)}/resign`).catch(() => ({ status: "gave up" })); cvDraw(); cvSide(); };
  if ($("#cv-next")) $("#cv-next").onclick = cvNext;
}
