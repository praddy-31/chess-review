// Chess Review - Openings. Study (default): your repertoire learnt line by line - new lines, same-day steps,
// reviews - with one card per opening. Your games: the opening tree, line scan and repertoire stars from V5.
// Uses helpers from app.js and train.js (api, $, $$, esc, S, VIEWS, toast, getPos, playLineFrom, labelFrom, turnOf).
"use strict";

const OP = { tab: "study", color: "White", tc: "", period: "", path: [], data: null, scan: null, cov: null, board: null, flipped: false,
  mode: "tree", animate: false, st: null, dev: null, lv: null, sess: null };

const pct = v => v == null ? "—" : `${v}%`;
const evalTxt = v => v == null ? "" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2)}`;
function wdlBar(m, w = 150) {
  const n = m.n || 1;
  return `<span class="wdl" style="width:${w}px" role="img" aria-label="${m.w} won, ${m.d} drawn, ${m.l} lost">
    <i class="w" style="width:${100 * m.w / n}%"></i><i class="d" style="width:${100 * m.d / n}%"></i><i class="l" style="width:${100 * m.l / n}%"></i></span>`;
}
const opName = n => n ? n.replace(/^[A-E]\d\d\s/, "") : "";
const STAR = on => `<svg width="16" height="16" viewBox="0 0 24 24" fill="${on ? "currentColor" : "none"}" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/></svg>`;
const START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
const sanLine = (sans, from = 0) => sans.map((s, i) => ((i + from) % 2 === 0 ? `${(i + from) / 2 + 1}.` : i === 0 ? `${Math.floor((i + from) / 2) + 1}...` : "") + s).join(" ");
const whenTxt = t => { const m = Math.round((t * 1000 - Date.now()) / 60000); return m <= 0 ? "now" : m < 60 ? `in ${m} min` : `at ${new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`; };

VIEWS.openings = async function () {
  OP.sess = null; OP.lv = null;
  document.onkeydown = opKeys;
  if (OP.tab === "games") return opGames();
  return stStudy();
};

function opHead(crumb, title, sub) {
  return `<div class="page-head rv-head"><div><div class="crumb">${crumb}</div><h1>${title}</h1>
      <div class="small ink2" id="op-sub" style="margin-top:2px">${sub}</div></div>
      <span class="spacer"></span><button id="op-learn">+ Learn an opening</button></div>
    <div class="tabs op-tabs" role="tablist"><a role="tab" data-optab="study" class="${OP.tab === "study" ? "on" : ""}">Study</a><a role="tab" data-optab="games" class="${OP.tab === "games" ? "on" : ""}">Your games</a></div>`;
}
function opBindHead() {
  $$("[data-optab]").forEach(a => a.onclick = () => { OP.tab = a.dataset.optab; VIEWS.openings(); });
  if ($("#op-learn")) $("#op-learn").onclick = () => openLearn();
}

function opKeys(e) {
  if (e.target.closest("input,textarea,select")) return;
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  if (OP.sess) return sessKey(e);
  if (OP.lv) return lvKey(e);
  if (OP.tab !== "games") return;
  if (e.key === "ArrowLeft") opGo(OP.path.slice(0, -1));
  else if (e.key === "Home") opGo([]);
  else if (e.key === "f") { OP.flipped = !OP.flipped; opDraw(); }
  else return;
  e.preventDefault();
}

// ------------------------------------------------------------------ Study: the overview
async function stStudy() {
  OP.tab = "study";
  const m = $("#main");
  m.innerHTML = `<div class="page page-wide op-page">${opHead("Openings / study", "Openings", "Your repertoire, learnt line by line.")}
    <div id="st-today"></div><div class="st-grid" id="st-cards"></div><div class="card" id="st-dev"><span class="muted small">Checking your recent games…</span></div></div>`;
  opBindHead();
  try { OP.st = await api("GET", "/api/study"); } catch (e) { toast(e.message, true); return; }
  if (S.view !== "openings" || OP.tab !== "study" || !$("#st-cards")) return;
  stRender();
  api("GET", "/api/study/deviations").then(d => { OP.dev = d.deviations; stDev(); }).catch(() => {});
}

function stRender() {
  const st = OP.st;
  const total = st.openings.reduce((a, c) => a + c.lines, 0);
  const due = st.reviews_due, nw = st.new_today;
  $("#op-sub").textContent = total ? `${total} line${total === 1 ? "" : "s"} in ${st.openings.length} opening${st.openings.length === 1 ? "" : "s"}${st.recall_7d != null ? ` · ${st.recall_7d}% recalled cleanly this week` : ""}.`
    : "Learn an opening, or star moves under Your games, and your lines appear here.";
  $("#st-today").innerHTML = total ? `<div class="card st-today">
      <div class="st-today-main"><div class="ll-title">Today</div>
        <div class="st-nums"><span><b>${due}</b> to review</span><span><b>${nw}</b> new line${nw === 1 ? "" : "s"} <span class="muted small">(${st.per_day} a day)</span></span>
          ${st.waiting ? `<span class="muted">${st.waiting} back ${whenTxt(st.next_step_at)} for its 10-minute step</span>` : ""}</div></div>
      <span class="spacer"></span>
      ${due + nw ? `<button class="primary" id="st-go">Start studying</button>` : `<span class="muted small">Done for today.</span><button id="st-more">Learn ${st.per_day || 3} more</button><button id="st-prac">Practice</button>`}
    </div>` : `<div class="card empty"><h2>No lines yet</h2><p class="muted">Pick an opening to learn - from what you play now, or any opening by name. Its main line and named replies become lines you study a few at a time.</p><button class="primary" id="st-learn">Learn an opening</button></div>`;
  if ($("#st-go")) $("#st-go").onclick = () => sessStart({});
  if ($("#st-more")) $("#st-more").onclick = () => sessStart({ more: st.per_day || 3 });
  if ($("#st-prac")) $("#st-prac").onclick = () => sessStart({ practice: true });
  if ($("#st-learn")) $("#st-learn").onclick = () => openLearn();
  const lv = st.levels || [];
  $("#st-cards").innerHTML = st.openings.map((c, i) => {
    const n = c.lines || 1;
    const lvl = c.level ? lv.find(x => x.level === c.level) : null;
    return `<div class="card st-op" data-i="${i}">
      <div class="st-op-head"><span class="side ${c.color}" title="As ${c.color}"></span><b class="st-op-name" title="${esc(c.opening)}">${esc(opName(c.opening))}</b>${c.due ? `<span class="tag st-due">${c.due} due</span>` : ""}</div>
      <div class="st-bar" role="img" aria-label="${c.learned} learned, ${c.learning} learning, ${c.new} new"><i class="lrn" style="width:${100 * c.learned / n}%"></i><i class="ing" style="width:${100 * c.learning / n}%"></i></div>
      <div class="small muted">${c.lines} line${c.lines === 1 ? "" : "s"} · <b class="ink">${c.learned}</b> learned · ${c.learning} learning · ${c.new} new${c.games ? ` · ${c.games.toLocaleString()} of your games` : ""}</div>
      ${c.chosen ? `<div class="st-len"><span class="muted small">Length</span><span class="seg" role="group" aria-label="Line length">${lv.map(x => `<button class="seg-b ${c.level === x.level ? "on" : ""}" data-len="${x.level}" title="${esc(x.name)}${x.moves ? `: ${x.moves} of your moves` : ": named theory, then 4 of your moves from Stockfish"}">${x.level}</button>`).join("")}</span>
        <span class="muted small">${lvl ? esc(lvl.name) + (lvl.moves ? ` · ${lvl.moves} moves` : "") : ""}</span></div>` : ""}
      <div class="row st-op-act"><button class="sm primary" data-act="study">Study</button><button class="sm" data-act="lines">Lines</button>
        ${c.chosen ? `<span class="spacer" style="flex:1"></span><button class="sm ghost" data-act="del" aria-label="Remove ${esc(opName(c.opening))}" title="Remove from my repertoire">✕</button>` : ""}</div>
    </div>`;
  }).join("") + (total && lv.length ? `<div class="muted small st-note">Length 3 is the recommendation for your rating (${S.settings.rating_used ?? S.settings.rating}): ${lv[2].moves} of your moves. Lines built from your games follow the repertoire cap in Settings.</div>` : "");
  $$(".st-op").forEach(el => {
    const c = st.openings[+el.dataset.i];
    $$("[data-act]", el).forEach(b => b.onclick = async () => {
      if (b.dataset.act === "study") return sessStart({ color: c.color, opening: c.opening });
      if (b.dataset.act === "lines") return lvOpen(c);
      if (!b.dataset.armed) { b.dataset.armed = 1; b.textContent = "Remove?"; return; }
      await api("POST", "/api/repertoire/forget", { color: c.color, name: c.opening });
      stStudy();
    });
    $$("[data-len]", el).forEach(b => b.onclick = async () => {
      if (+b.dataset.len === c.level) return;
      $$("[data-len]", el).forEach(x => (x.disabled = true));
      el.querySelector(".st-len .muted:last-child").textContent = "Rebuilding the lines…";
      try { const r = await api("POST", "/api/study/level", { color: c.color, opening: c.opening, level: +b.dataset.len });
        toast(`${opName(r.opening)}: ${r.lines.lines} lines${r.trimmed ? `, ${r.trimmed} moves past the new end removed` : ""}`); }
      catch (e) { toast(e.message, true); }
      stStudy();
    });
  });
}

function stDev() {
  const box = $("#st-dev");
  if (!box) return;
  const ds = OP.dev || [];
  const ago = d => { const n = Math.round((Date.now() - new Date((d || "").replace(" ", "T") + "Z")) / 864e5); return n <= 0 ? "today" : n === 1 ? "yesterday" : `${n} days ago`; };
  box.innerHTML = `<div class="ll-head"><span class="ll-title">From your recent games</span><span class="muted small">where you or they left your lines, last 30 days</span></div>
    ${ds.length ? ds.map((d, i) => `<div class="st-dev-row">
      <span class="side ${d.color}"></span>
      <span class="op-ln"><b>${d.who === "you" ? `You played ${esc(d.played)}, your line says ${esc(d.planned)}` : `They played ${esc(d.played)}: no answer in your repertoire yet`}</b>
        <span class="muted small">vs ${esc(d.opponent || "?")} · ${ago(d.played_at)} · after ${d.san.length ? esc(sanLine(d.san)) : "the start"}</span></span>
      <span class="spacer" style="flex:1"></span>
      ${d.who === "you" ? `<button class="sm" data-dv="${i}" data-dact="due" title="Make the lines through this position due now">Review it now</button>`
        : `<button class="sm" data-dv="${i}" data-dact="add" title="Open the position under Your games to star your answer">Add my answer</button>`}
      <button class="sm ghost" data-dv="${i}" data-dact="game">Game</button></div>`).join("")
      : `<span class="muted small">${OP.st && OP.st.openings.length ? "Nothing yet: every recent game kept to your lines, or none reached them." : "Appears once you have lines."}</span>`}`;
  $$("[data-dv]", box).forEach(b => b.onclick = async () => {
    const d = ds[+b.dataset.dv];
    if (b.dataset.dact === "game") return (location.hash = `#/review/${encodeURIComponent(d.game_id)}`);
    if (b.dataset.dact === "due") { const r = await api("POST", "/api/study/due", { color: d.color, prefix: d.moves }); toast(r.lines ? `${r.lines} line${r.lines === 1 ? "" : "s"} due now` : "Those lines aren't in review yet: study them first"); return stStudy(); }
    OP.tab = "games"; OP.color = d.color; OP.flipped = d.color === "Black"; OP.path = [...d.moves, d.uci].map(uci => ({ uci }));
    VIEWS.openings();
  });
}

// ------------------------------------------------------------------ Lines of one opening
async function lvOpen(c) {
  let lines = [];
  try { lines = (await api("GET", "/api/study/lines?" + new URLSearchParams({ color: c.color, opening: c.opening }))).lines; } catch (e) { return toast(e.message, true); }
  OP.lv = { c, lines, sel: 0, w: 0, steps: [] };
  const m = $("#main");
  m.innerHTML = `<div class="page page-wide op-page">${opHead(`Openings / ${esc(opName(c.opening))}`, esc(opName(c.opening)), `${lines.length} line${lines.length === 1 ? "" : "s"} as ${c.color}. Pick one to step through it.`)}
    <div class="rv"><div class="rv-left"><div class="boardwrap"><svg class="board" id="board" role="img" aria-label="Line board"></svg></div>
      <div class="op-path" id="lv-path"></div>
      <div class="navbar"><button class="nb" data-lgo="start" title="Start (Home)">⏮</button><button class="nb" data-lgo="back" title="Back (←)">◀</button><button class="nb" data-lgo="fwd" title="Forward (→)">▶</button><button class="nb" data-lgo="end" title="End (End)">⏭</button>
        <span class="spacer"></span><button class="nb" id="lv-tree">Show under Your games</button></div></div>
      <div class="rv-right"><div class="card"><div class="ll-head"><span class="ll-title">Lines</span><span class="spacer"></span><button class="sm primary" id="lv-study">Study this opening</button><button class="sm" id="lv-back">Back</button></div>
        <div id="lv-list"></div></div><div class="card" id="lv-exp" hidden></div></div></div></div>`;
  opBindHead();
  OP.board = new ChessBoard($("#board")); OP.board.pieces = S.settings.pieces || "cburnett";
  OP.flipped = c.color === "Black";
  $("#lv-back").onclick = () => VIEWS.openings();
  $("#lv-study").onclick = () => sessStart({ color: c.color, opening: c.opening });
  $("#lv-tree").onclick = () => { const L = OP.lv.lines[OP.lv.sel]; OP.tab = "games"; OP.color = c.color; OP.flipped = c.color === "Black"; OP.path = (L ? L.moves.slice(0, OP.lv.w) : []).map(uci => ({ uci })); OP.lv = null; VIEWS.openings(); };
  $$("[data-lgo]").forEach(b => b.onclick = () => lvStep(b.dataset.lgo));
  const badge = L => L.state === "new" ? `<span class="tag">new</span>` : L.learned ? `<span class="tag st-learned">learned</span>` : `<span class="tag st-ing">${L.state === "learning" ? "learning" : `review · ${[1, 3, 7, 16, 35, 80, 180][L.ladder]} d`}</span>`;
  $("#lv-list").innerHTML = lines.map((L, i) => `<a class="op-line lv-line" data-li="${i}"><span class="op-ln"><b>${esc(opName(L.opening || c.opening))}</b>
      <span class="muted small">${esc(sanLine(L.san))}</span></span>${badge(L)}</a>`).join("") || `<span class="muted small">No lines.</span>`;
  $$("[data-li]").forEach(a => a.onclick = () => lvPick(+a.dataset.li));
  if (lines.length) lvPick(0);
}
async function lvPick(i) {
  const lv = OP.lv;
  lv.sel = i;
  $$("[data-li]").forEach(a => a.classList.toggle("on", +a.dataset.li === i));
  lv.steps = await playLineFrom(START_FEN, lv.lines[i].moves);
  lv.w = lv.steps.length;
  lvDraw();
}
function lvStep(k) {
  const lv = OP.lv; if (!lv) return;
  lv.w = k === "start" ? 0 : k === "end" ? lv.steps.length : k === "back" ? Math.max(0, lv.w - 1) : Math.min(lv.steps.length, lv.w + 1);
  lvDraw(true);
}
function lvKey(e) {
  const k = { ArrowLeft: "back", ArrowRight: "fwd", Home: "start", End: "end" }[e.key];
  if (e.key === "Escape") { VIEWS.openings(); e.preventDefault(); return; }
  if (!k) return;
  lvStep(k); e.preventDefault();
}
function lvDraw(anim) {
  const lv = OP.lv; if (!lv || !OP.board) return;
  const st = lv.steps[lv.w - 1];
  const next = lv.steps[lv.w];
  OP.board.draw({ fen: st ? st.fen : START_FEN, lastUci: st ? st.uci : null, flipped: OP.flipped, animate: anim,
    arrows: next ? [[next.uci, cssv("--accent")]] : [] });
  const name = [...lv.steps.slice(0, lv.w)].reverse().find(s => s.opening)?.opening;
  $("#lv-path").innerHTML = `<a class="mchip ${lv.w ? "" : "cur"}" data-lw="0">Start</a>` + lv.steps.map((s, i) =>
    `<a class="mchip ${i === lv.w - 1 ? "cur" : ""} ${i < lv.lines[lv.sel].start ? "pre" : ""}" data-lw="${i + 1}">${esc((i % 2 === 0 ? `${i / 2 + 1}.` : "") + s.san)}</a>`).join("")
    + (name ? `<span class="muted small" style="margin-left:6px">${esc(opName(name))}</span>` : "");
  $$("[data-lw]").forEach(a => a.onclick = () => { lv.w = +a.dataset.lw; lvDraw(); });
  stExplorer($("#lv-exp"), st ? st.fen : START_FEN, lv.c.color);
}

// what's played at your level on Lichess (only when switched on in Settings)
async function stExplorer(box, fen, color) {
  if (!box) return;
  if (!S.settings.explorer_lookup || turnOf(fen) === color) { box.hidden = true; return; }
  box.hidden = false; box.innerHTML = `<span class="muted small">Asking the Lichess explorer…</span>`;
  let x = null;
  try { x = (await api("GET", "/api/study/explorer?fen=" + encodeURIComponent(fen))).explorer; } catch (e) {}
  if (!x) { box.hidden = true; return; }
  if (x.error) { box.innerHTML = `<span class="muted small">${esc(x.error)}</span>`; return; }
  box.innerHTML = `<div class="ll-head"><span class="ll-title">Their replies at your level</span><span class="muted small">Lichess blitz + rapid, ${x.bands.join("–")}, ${x.games.toLocaleString()} games</span></div>
    ${x.moves.map(mv => `<div class="st-exp"><b>${esc(mv.san)}</b><span class="st-expbar"><i style="width:${mv.share}%"></i></span><span class="num muted small">${mv.share}%</span></div>`).join("")}`;
}

// ------------------------------------------------------------------ a study session
async function sessStart(opts) {
  let q;
  try { q = await api("GET", "/api/study/queue?" + new URLSearchParams({ color: opts.color || "", opening: opts.opening || "", more: opts.more || 0, practice: opts.practice ? "1" : "" })); }
  catch (e) { return toast(e.message, true); }
  OP.sess = { opts, q, items: q.queue.slice(), done: 0, total: q.queue.length, verified: new Set(), cur: null, results: [] };
  OP.lv = null;
  const m = $("#main");
  m.innerHTML = `<div class="page page-wide op-page">
    <div class="page-head rv-head"><div><div class="crumb">Openings / study</div><h1>${opts.practice ? "Practice" : "Study"}${opts.opening ? ` · ${esc(opName(opts.opening))}` : ""}</h1>
      <div class="small ink2" id="op-sub" style="margin-top:2px">${opts.practice ? "Extra rounds: they don't change when lines come back." : "Same-day steps first, then reviews, then new lines."}</div></div>
      <span class="spacer"></span><button id="ss-quit">Back to Openings (Esc)</button></div>
    <div class="rv"><div class="rv-left"><div class="boardwrap"><svg class="board" id="board" role="img" aria-label="Study board"></svg></div><div class="op-path" id="ss-path"></div></div>
      <div class="rv-right"><div id="ss-side"></div><div class="card" id="lv-exp" hidden></div></div></div></div>`;
  $("#ss-quit").onclick = () => { OP.sess = null; VIEWS.openings(); };
  OP.board = new ChessBoard($("#board")); OP.board.pieces = S.settings.pieces || "cburnett";
  sessNext();
}

const MODE = { learn: "New line", step: "Same-day step", review: "Review", practice: "Practice" };
const sideAt = i => i % 2 === 0 ? "White" : "Black";

async function sessNext() {
  const s = OP.sess; if (!s) return;
  const L = s.items.shift();
  if (!L) return sessEnd();
  const steps = await playLineFrom(START_FEN, L.moves);
  OP.flipped = L.color === "Black";
  const c = { L, steps, phase: L.mode === "learn" ? "watch" : "recall", w: L.start, idx: L.start, missed: false, arrows: [], msg: null, res: null };
  s.cur = c;
  if (c.phase === "recall") sessSkipVerified(c);
  sessRender();
}
// in one session, the moves you just played in another line aren't asked again
function sessSkipVerified(c) {
  const s = OP.sess, L = c.L;
  let k = c.idx;
  for (let i = L.moves.length; i > c.idx; i--) {
    if (sideAt(i) === L.color && s.verified.has(L.color + "|" + L.moves.slice(0, i).join(","))) { k = i; break; }
  }
  c.skipped = k - c.idx;
  c.idx = k;
}
function sessFen(c) { return c.idx ? c.steps[c.idx - 1].fen : START_FEN; }

function sessDraw(anim) {
  const s = OP.sess, c = s && s.cur; if (!c || !OP.board) return;
  const at = c.phase === "watch" ? c.w : c.idx;
  const st = c.steps[at - 1];
  const arrows = c.phase === "watch" && c.steps[c.w] ? [[c.steps[c.w].uci, cssv("--accent")]] : c.arrows;
  OP.board.draw({ fen: st ? st.fen : START_FEN, lastUci: st ? st.uci : null, flipped: OP.flipped, animate: anim, arrows });
  OP.board.setMoves(null);
  $("#ss-path").innerHTML = c.steps.slice(0, at).map((x, i) => `<span class="mchip ${i < c.L.start ? "pre" : ""} ${i === at - 1 ? "cur" : ""}">${esc((i % 2 === 0 ? `${i / 2 + 1}.` : "") + x.san)}</span>`).join("")
    + (c.phase === "recall" && !c.res ? `<span class="mchip ghost">…</span>` : "");
  if (c.phase === "recall" && !c.res && c.idx < c.L.moves.length && sideAt(c.idx) === c.L.color) {
    const fen = sessFen(c);
    getPos(fen).then(p => { if (OP.sess && OP.sess.cur === c && sessFen(c) === fen && !c.res && !c.busy) OP.board.setMoves(p.moves, sessMove); }).catch(() => {});
  }
  stExplorer($("#lv-exp"), st ? st.fen : START_FEN, c.L.color);
}

function sessAuto() {
  // play the opponent's moves in for you, then hand over
  const s = OP.sess, c = s && s.cur; if (!c || c.res) return;
  if (c.idx >= c.L.moves.length) return sessFinish();
  if (sideAt(c.idx) !== c.L.color) {
    c.busy = true;
    setTimeout(() => { if (OP.sess && OP.sess.cur === c) { c.idx++; c.busy = false; sessDraw(true); sessRender(true); sessAuto(); } }, 380);
  }
}

function sessMove(uci) {
  const s = OP.sess, c = s.cur;
  const want = c.L.moves[c.idx];
  if (uci === want) {
    c.idx++; c.arrows = [];
    c.msg = c.msg && c.msg.kind === "no" ? { kind: "ok", text: "That's it. On you go." } : null;
    sessDraw(true); sessRender(true); sessAuto();
    return;
  }
  c.missed = true;
  c.arrows = [[want, cssv("--accent"), { label: "★" }]];
  c.msg = { kind: "no", text: `Your line plays <b>${esc(c.steps[c.idx].san)}</b> here (purple arrow). Play it to go on.` };
  sessDraw(); sessRender(true);
}

async function sessFinish() {
  const s = OP.sess, c = s.cur;
  const practice = c.L.mode === "practice";
  try { c.res = await api("POST", "/api/study/result", { color: c.L.color, key: c.L.key, clean: !c.missed, practice }); }
  catch (e) { toast(e.message, true); c.res = {}; }
  for (let i = c.L.start + 1; i <= c.L.moves.length; i++) if (sideAt(i - 1) === c.L.color) s.verified.add(c.L.color + "|" + c.L.moves.slice(0, i).join(","));
  s.done++;
  s.results.push(!c.missed);
  // a line in its same-day steps comes back in this session when it is due
  if (!practice && c.res.state === "learning" && c.res.step >= 2) s.items.push({ ...c.L, mode: "step", step: 2 });
  sessDraw(true); sessRender();
}

function sessOutcome(c) {
  const r = c.res || {};
  if (c.L.mode === "practice") return c.missed ? "A miss, but practice doesn't change the schedule." : "Clean. Practice doesn't change the schedule.";
  if (r.state === "learning") return c.missed ? "Missed a move: it comes back in a minute." : r.step === 1 ? "Learnt. It comes back in about 10 minutes for its first same-day step." : "Once more at the end of this session.";
  if (r.state === "review") return r.learned ? `Learned. Next review in ${r.interval} day${r.interval === 1 ? "" : "s"}.` : `In review: back in ${r.interval} day${r.interval === 1 ? "" : "s"}.`;
  return "";
}

function sessRender(sideOnly) {
  const s = OP.sess, c = s && s.cur; const side = $("#ss-side");
  if (!s || !side) return;
  const dots = Array.from({ length: Math.min(Math.max(s.total, s.done + s.items.length + (c && !c.res ? 1 : 0)), 30) }, (_, i) =>
    `<i class="${i < s.done ? (s.results[i] ? "done" : "miss") : i === s.done && c && !c.res ? "now" : ""}"></i>`).join("");
  if (!c) return;
  const L = c.L;
  const name = [...c.steps].reverse().find(x => x.opening)?.opening || L.opening;
  let body;
  if (c.phase === "watch") {
    const nx = c.steps[c.w];
    const mineNext = nx && sideAt(c.w) === L.color;
    body = `<div class="pz-msg hint">${nx ? `${mineNext ? "You play" : "They play"} <b>${esc((c.w % 2 === 0 ? `${c.w / 2 + 1}.` : `${Math.floor(c.w / 2) + 1}...`) + nx.san)}</b>${nx.opening ? ` <span class="muted small">· ${esc(opName(nx.opening))}</span>` : ""}`
        : `That's the whole line: ${L.mine} of your moves. Now play it from the start.`}</div>
      <div class="row" style="gap:8px">${nx ? `<button class="primary" id="ss-fwd">Next move (→)</button><button class="sm ghost" id="ss-skip">Skip to the end</button>` : `<button class="primary" id="ss-recall">Play it from the start (Enter)</button>`}${c.w > L.start ? `<button class="sm" id="ss-bk">◀ Back</button>` : ""}</div>`;
  } else if (!c.res) {
    body = `${c.skipped ? `<div class="muted small">${c.skipped} move${c.skipped === 1 ? "" : "s"} you just played are filled in.</div>` : ""}
      ${c.msg ? `<div class="pz-msg ${c.msg.kind}">${c.msg.text}</div>` : `<div class="pz-msg">${sideAt(c.idx) === L.color ? "Your move." : "Their move…"}</div>`}
      <div class="pz-hints"><button class="sm" id="ss-show">Show my move</button><span class="muted small">Esc goes back</span></div>`;
  } else {
    body = `<div class="pz-msg ${c.missed ? "no" : "ok"}">${c.missed ? "Done, with a miss." : "Clean."} ${sessOutcome(c)}</div>
      <div class="muted small">${esc(sanLine(L.san))}</div>
      <div class="row" style="gap:8px"><button class="primary" id="ss-next">Next (Enter)</button></div>`;
  }
  side.innerHTML = `<div class="pz-card card">
    <div class="pz-top"><span class="pz-title">${MODE[L.mode] || "Line"}</span><span class="muted small">${s.done} done · ${s.items.length + (c.res ? 0 : 1)} left</span></div>
    <div class="pz-dots">${dots}</div>
    <div class="pz-head"><span class="pz-turn"><span class="side ${L.color}"></span>${esc(opName(name) || "Your line")}</span>${L.freq ? `<span class="muted small">${L.freq} of your games reached its end</span>` : ""}</div>
    ${body}</div>`;
  const on = (id, f) => { const el = $("#" + id); if (el) el.onclick = f; };
  on("ss-fwd", () => { c.w++; sessDraw(true); sessRender(true); });
  on("ss-bk", () => { c.w--; sessDraw(); sessRender(true); });
  on("ss-skip", () => { c.w = c.steps.length; sessDraw(); sessRender(true); });
  on("ss-recall", () => { c.phase = "recall"; c.idx = L.start; c.msg = null; sessDraw(); sessRender(true); sessAuto(); });
  on("ss-show", () => { c.missed = true; c.arrows = [[L.moves[c.idx], cssv("--accent"), { label: "★" }]]; c.msg = { kind: "hint", text: "This one. Play it to go on." }; sessDraw(); sessRender(true); });
  on("ss-next", () => sessNext());
  if (!sideOnly) { sessDraw(true); if (c.phase === "recall" && !c.res) sessAuto(); }
}

async function sessEnd() {
  const s = OP.sess;
  let q = null;
  if (!s.opts.practice) { try { q = await api("GET", "/api/study/queue?" + new URLSearchParams({ color: s.opts.color || "", opening: s.opts.opening || "" })); } catch (e) {} }
  if (q && q.queue.length) { s.items = q.queue; s.total = s.done + q.queue.length; return sessNext(); }   // a 10-minute step came due meanwhile
  OP.board.setMoves(null); OP.board.draw({ fen: START_FEN, flipped: false }); $("#ss-path").innerHTML = "";
  const clean = s.results.filter(Boolean).length;
  $("#ss-side").innerHTML = `<div class="pz-card card"><div class="pz-top"><span class="pz-title">${s.opts.practice ? "Practice" : "Study"}</span><span class="muted small">${s.done} line${s.done === 1 ? "" : "s"}</span></div>
    <h2>${s.done ? "Done for now" : "Nothing to study right now"}</h2>
    <p class="muted">${s.done ? `${clean} of ${s.done} clean. ` : ""}${q && q.waiting ? `${q.waiting} line${q.waiting === 1 ? "" : "s"} come${q.waiting === 1 ? "s" : ""} back ${whenTxt(q.next_step_at)} for the 10-minute step.` : "Reviews come back on their day; new lines a few at a time."}</p>
    <div class="row" style="gap:8px">${q && q.new_left ? `<button class="primary" id="ss-more">Learn ${q.per_day || 3} more</button>` : ""}<button id="ss-prac">Practice</button><button id="ss-home">Back to Openings</button></div></div>`;
  if ($("#ss-more")) $("#ss-more").onclick = () => sessStart({ ...s.opts, more: q.per_day || 3, practice: false });
  $("#ss-prac").onclick = () => sessStart({ ...s.opts, more: 0, practice: true });
  $("#ss-home").onclick = () => { OP.sess = null; VIEWS.openings(); };
  s.cur = null;
}

function sessKey(e) {
  const s = OP.sess, c = s && s.cur;
  if (e.key === "Escape") { OP.sess = null; VIEWS.openings(); }
  else if (!c) return;
  else if (c.phase === "watch" && (e.key === "ArrowRight" || e.key === " ")) { if (c.steps[c.w]) { c.w++; sessDraw(true); sessRender(true); } }
  else if (c.phase === "watch" && e.key === "ArrowLeft") { if (c.w > c.L.start) { c.w--; sessDraw(); sessRender(true); } }
  else if (c.phase === "watch" && e.key === "Enter" && !c.steps[c.w]) $("#ss-recall")?.click();
  else if (e.key === "Enter" && c.res) sessNext();
  else return;
  e.preventDefault();
}

// ------------------------------------------------------------------ Your games: the tree (V5)
async function opGames() {
  OP.mode = "tree";
  const m = $("#main");
  m.innerHTML = `<div class="page page-wide op-page">${opHead("Openings / your games", "Your games", "From all your games, analysed or not.")}
    <div class="filters" id="op-filters"></div>
    <div id="op-index"></div>
    <div class="rv">
      <div class="rv-left">
        <div class="boardwrap"><svg class="board" id="board" role="img" aria-label="Opening board"></svg></div>
        <div class="op-path" id="op-path"></div>
        <div class="navbar">
          <button class="nb" data-ogo="start" aria-label="Start" title="Start (Home)">⏮</button><button class="nb" data-ogo="back" aria-label="Back" title="Back (←)">◀</button>
          <button class="nb" id="op-flip" title="Flip (F)">Flip</button><button class="nb" id="op-board" title="Open this position on the analysis board">Analyse on the Board</button>
          <span class="hint">click a move in the table, or play it on the board</span>
        </div>
        <div class="card op-rep" id="op-rep"></div>
      </div>
      <div class="rv-right">
        <div class="card" id="op-moves"></div>
        <div class="op-scan" id="op-scan"></div>
        <div class="card" id="op-left"></div>
      </div>
    </div></div>`;
  opBindHead();
  OP.board = new ChessBoard($("#board"));
  OP.board.pieces = S.settings.pieces || "cburnett";
  $$("[data-ogo]").forEach(b => b.onclick = () => b.dataset.ogo === "start" ? opGo([]) : opGo(OP.path.slice(0, -1)));
  $("#op-flip").onclick = () => { OP.flipped = !OP.flipped; opDraw(); };
  $("#op-board").onclick = () => { S.boardSeed = { fen: START_FEN, game: OP.path.map(p => p.uci), at: OP.path.length, extra: [], flipped: OP.flipped, title: "Openings" }; location.hash = "#/board"; };
  OP.flipped = OP.color === "Black";
  opFilters();
  await opLoad(true);
}

function opFilters() {
  const chip = (k, v, l) => `<span class="chip ${OP[k] === v ? "on" : ""}" data-ok="${k}" data-ov="${v}">${l}</span>`;
  const tcs = [...new Set((S.games || []).map(g => g.tc_category).filter(x => x && x !== "unknown"))];
  $("#op-filters").innerHTML = `${chip("color", "White", "As White")}${chip("color", "Black", "As Black")}<span class="sep"></span>
    ${chip("tc", "", "All time controls")}${(tcs.length ? tcs : ["blitz", "rapid", "bullet"]).map(t => chip("tc", t, cap(t))).join("")}<span class="sep"></span>
    ${chip("period", "", "All time")}${chip("period", "90", "Last 3 months")}${chip("period", "365", "Last year")}`;
  $$("[data-ok]").forEach(c => c.onclick = () => {
    const k = c.dataset.ok, v = c.dataset.ov;
    OP[k] = v;
    if (k === "color") { OP.path = []; OP.flipped = v === "Black"; }
    opFilters(); opLoad(true);
  });
}
const opQS = extra => new URLSearchParams({ color: OP.color, tc: OP.tc, period: OP.period, ...(extra || {}) });

async function opLoad(withScan) {
  const moves = OP.path.map(p => p.uci).join(",");
  try { OP.data = await api("GET", "/api/openings/tree?" + opQS({ moves })); }
  catch (e) { toast(e.message, true); return; }
  OP.path = OP.data.path;
  if (withScan) {
    [OP.scan, OP.cov] = await Promise.all([api("GET", "/api/openings/scan?" + opQS()).catch(() => null),
      api("GET", "/api/repertoire/coverage?color=" + OP.color).catch(() => null)]);
  }
  opRender();
  const ix = OP.data.index;
  if (ix && ix.state === "running") setTimeout(() => { if (S.view === "openings" && OP.tab === "games" && !OP.sess) opLoad(true); }, 1500);
}
function opGo(path) { OP.path = path; OP.animate = true; opLoad(false); }

function opDraw() {
  const d = OP.data;
  if (!d || !OP.board || !$("#op-moves")) return;
  const last = OP.path.length ? OP.path[OP.path.length - 1].uci : null;
  const arrows = [];
  const top = d.moves.slice(0, 3);
  const maxN = top[0]?.n || 1;
  top.forEach((m, i) => arrows.push([m.uci, m.rep ? cssv("--accent") : `rgba(95,182,90,${(0.35 + 0.55 * m.n / maxN).toFixed(2)})`]));
  if (d.rep && !top.some(m => m.uci === d.rep.uci)) arrows.push([d.rep.uci, cssv("--accent")]);
  OP.board.draw({ fen: d.fen, lastUci: last, arrows, flipped: OP.flipped, animate: OP.animate });
  OP.animate = false;
  getPos(d.fen).then(p => {
    if (OP.tab !== "games" || OP.sess || !OP.data || OP.data.fen !== d.fen) return;
    OP.board.setMoves(p.moves, uci => opGo([...OP.path, { uci }]));
  }).catch(() => {});
}

function opRender() {
  const d = OP.data;
  if (S.view !== "openings" || OP.tab !== "games" || OP.sess || !$("#op-moves")) return;   // left the screen meanwhile
  const ix = d.index || {};
  $("#op-index").innerHTML = ix.state === "running" ? `<div class="card notice row" style="gap:10px;margin-bottom:12px"><span>Building your opening tree: ${ix.done} of ${ix.total} games…</span><div class="prog" style="flex:1;height:6px"><i style="width:${ix.total ? 100 * ix.done / ix.total : 0}%"></i></div></div>` : "";
  $("#op-sub").textContent = `${d.games.toLocaleString()} of your games as ${OP.color} reach this position${d.opening ? ` · ${opName(d.opening)}` : ""}.`;
  // path chips
  $("#op-path").innerHTML = `<a class="mchip ${OP.path.length ? "" : "cur"}" data-op="0">Start</a>` + OP.path.map((p, i) =>
    `<a class="mchip ${i === OP.path.length - 1 ? "cur" : ""}" data-op="${i + 1}">${esc((i % 2 === 0 ? p.label : "") + p.san)}</a>`).join("");
  $$("[data-op]").forEach(a => a.onclick = () => opGo(OP.path.slice(0, +a.dataset.op)));
  // move table
  const mine = d.my_turn;
  const rows = d.moves.slice(0, 14).map(m => {
    const sc = m.score == null ? "" : m.score >= 55 ? "good" : m.score < 45 ? "bad" : "";
    return `<div class="op-row" data-uci="${m.uci}">
      ${mine ? `<button class="ghost op-star ${m.rep ? "on" : ""}" data-star="${m.uci}" aria-label="${m.rep ? "In your repertoire" : "Add to your repertoire"}" title="${m.rep ? "Your repertoire move (click to remove)" : "Make this your repertoire move"}">${STAR(m.rep)}</button>` : `<span></span>`}
      <a class="op-mv" data-go="${m.uci}"><b>${esc(labelFrom(d.fen) + m.san)}</b></a>
      <span class="op-name" title="${esc(m.name || "")}">${esc(opName(m.name))}</span>
      <span class="num muted">${m.n ? m.n.toLocaleString() : "—"}</span>
      ${m.n ? wdlBar(m, 104) : `<span class="muted small">${m.theory_only ? "theory · not played" : ""}</span>`}
      <b class="num op-sc ${sc}">${m.score == null ? "" : m.score + "%"}</b>
      <span class="num muted small" title="${m.eval_n ? `average engine eval after the move, your view, over ${m.eval_n} analysed game${m.eval_n === 1 ? "" : "s"}` : "no analysed games here yet"}">${m.eval != null ? evalTxt(m.eval) : "—"}</span>
    </div>`;
  }).join("");
  $("#op-moves").innerHTML = `<div class="ll-head"><span class="ll-title">${mine ? "Your moves here" : "Their replies"}</span><span class="muted small">${d.turn} to play${d.rep ? ` · your move: <b>${esc(d.rep.san)}</b>` : mine ? " · no repertoire move yet" : ""}</span></div>
    ${d.moves.length ? `<div class="op-row op-head"><span></span><span>Move</span><span>Opening</span><span class="num">Games</span><span>Won · drawn · lost</span><span class="num">Score</span><span class="num">Eval</span></div>${rows}`
      : `<p class="muted">None of your games ${OP.tc || OP.period ? "with these filters " : ""}reached this position. Play a move on the board to keep exploring.</p>`}
    <div class="muted small" style="margin-top:8px">Score counts a draw as half, from your side. Eval: the engine after the move, averaged over your analysed games. Rows without games are known theory you haven't played yet; you can star them.</div>`;
  $$("[data-go]").forEach(a => a.onclick = () => opGo([...OP.path, { uci: a.dataset.go }]));
  $$("[data-star]").forEach(b => b.onclick = async e => {
    e.stopPropagation();
    const on = b.classList.contains("on");
    try { await api("POST", "/api/repertoire", { color: OP.color, moves: OP.path.map(p => p.uci), uci: on ? null : b.dataset.star }); }
    catch (err) { return toast(err.message, true); }
    OP.cov = await api("GET", "/api/repertoire/coverage?color=" + OP.color).catch(() => OP.cov);
    opLoad(false);
  });
  // line scan
  const sc = OP.scan;
  const item = (x, good) => `<a class="op-line" data-line="${x.moves.join(",")}"><span class="op-ln"><b>${esc(opName(x.name))}</b>
      <span class="muted small">${esc(x.san.map((s, i) => (i % 2 === 0 ? `${i / 2 + 1}.` : "") + s).join(" "))} · ${x.n} games</span></span>
      <b class="num ${good ? "good" : "bad"}">${x.score}%</b></a>`;
  $("#op-scan").innerHTML = sc && sc.games ? `
    <div class="card"><div class="ll-head"><span class="ll-title">Fix first</span><span class="muted small">your weakest lines</span></div>${sc.worst.map(x => item(x, false)).join("") || `<span class="muted small">Not enough games yet.</span>`}</div>
    <div class="card"><div class="ll-head"><span class="ll-title">Working for you</span><span class="muted small">your best lines</span></div>${sc.best.map(x => item(x, true)).join("") || `<span class="muted small">Not enough games yet.</span>`}</div>
    <div class="muted small op-scan-note">Lines in your first 16 half-moves with ${sc.min_games}+ games, one per opening name. Your overall score as ${OP.color}: ${pct(sc.overall)}.</div>` : "";
  $$("[data-line]").forEach(a => a.onclick = () => opGo(a.dataset.line.split(",").map(uci => ({ uci }))));
  // repertoire card
  const cv = OP.cov || {};
  $("#op-rep").innerHTML = `<div class="ll-head"><span class="ll-title">Repertoire as ${OP.color}</span><span class="muted small">${cv.lines || 0} starred move${cv.lines === 1 ? "" : "s"}</span></div>
    ${cv.lines ? `<div class="op-cov"><span class="op-covbar"><i style="width:${cv.share || 0}%"></i></span><b>${pct(cv.share)}</b></div>
      <div class="muted small">Of the ${(cv.games || 0).toLocaleString()} games that met your repertoire, this share kept to it.</div>`
      : `<p class="muted small" style="margin:0">Star the move you want to play in each position, or let the app star your most-played moves along the lines you meet often (depth follows your games, capped by your rating).</p>`}
    <div class="row" style="gap:8px;margin-top:10px"><button class="sm" id="op-build" title="Stars your most-played move along lines you meet often, using the time filter above (pick Last 3 months to build from what you play now)">${cv.lines ? "Fill gaps from my games" : "Build from my games"}${OP.period ? ` (${OP.period === "90" ? "last 3 months" : "last year"})` : ""}</button>
      <button class="sm primary" id="op-drill">Study · <span id="op-due">…</span></button></div>`;
  $("#op-build").onclick = async () => {
    $("#op-build").disabled = true;
    try { const r = await api("POST", "/api/repertoire/build", { color: OP.color, tc: OP.tc, period: OP.period }); toast(r.added ? `Starred ${r.added} move${r.added === 1 ? "" : "s"} (up to move ${r.cap}, lines with ${Math.ceil(r.floor)}+ games)` : "Nothing new to add: your common lines are covered"); }
    catch (e) { toast(e.message, true); }
    OP.cov = await api("GET", "/api/repertoire/coverage?color=" + OP.color).catch(() => OP.cov);
    opLoad(false);
  };
  $("#op-drill").onclick = () => sessStart({ color: OP.color });
  api("GET", "/api/study/queue?color=" + OP.color).then(q => { const el = $("#op-due"); if (el) el.textContent = !cv.lines ? "nothing yet" : q.queue.length ? `${q.queue.length} today` : "done for today"; }).catch(() => {});
  // where you left it
  const left = cv.left || [];
  $("#op-left").innerHTML = `<div class="ll-head"><span class="ll-title">Where you left your repertoire</span></div>
    ${left.length ? left.slice(0, 6).map(L => `<a class="op-line" data-lpath="${L.path.join(",")}"><span class="op-ln"><b>${L.path_san && L.path_san.length ? `After ${esc(L.path_san.map((p, i) => (i % 2 === 0 ? p.label : "") + p.san).join(" "))}: ` : "Move 1: "}you planned ${esc(L.planned)}</b>
      <span class="muted small">played instead: ${L.played.slice(0, 3).map(([s, n]) => `${esc(s)} ×${n}`).join(", ")}</span></span><b class="num">${L.n}</b></a>`).join("")
      : `<span class="muted small">${cv.lines ? "You kept to your repertoire in every game so far." : "Appears once you have a repertoire."}</span>`}`;
  $$("[data-lpath]").forEach(a => a.onclick = () => opGo(a.dataset.lpath ? a.dataset.lpath.split(",").map(uci => ({ uci })) : []));
  opDraw();
}

// ------------------------------------------------------------------ learn an opening: the picker
function openLearn() {
  const bg = document.createElement("div");
  bg.className = "modal-bg";
  bg.innerHTML = `<div class="modal learn" role="dialog" aria-label="Learn an opening">
    <div class="row" style="gap:10px"><h2 style="margin:0">Learn an opening</h2><span style="flex:1"></span><button class="ghost sm" id="ln-close" aria-label="Close">✕</button></div>
    <div class="learn-grid">
      <div class="learn-left">
        <input type="search" id="ln-q" placeholder="Search: King's Indian, Caro-Kann Advance, B12…" autocomplete="off">
        <div class="learn-list" id="ln-list"><div class="muted small">Loading…</div></div>
      </div>
      <div class="learn-right">
        <svg class="board" id="ln-board" role="img" aria-label="Opening preview"></svg>
        <div id="ln-info" class="learn-info"></div>
      </div>
    </div></div>`;
  document.body.appendChild(bg);
  const onKey = e => { if (e.key === "Escape") close(); };
  const close = () => { bg.remove(); document.removeEventListener("keydown", onKey, true); };
  document.addEventListener("keydown", onKey, true);
  $("#ln-close", bg).onclick = close;
  bg.addEventListener("mousedown", e => { if (e.target === bg) close(); });
  const board = new ChessBoard($("#ln-board", bg));
  board.pieces = S.settings.pieces || "cburnett";
  board.draw({ fen: START_FEN });
  let sel = null, color = OP.color, level = +(S.settings.learn_depth || 3), levels = (OP.st && OP.st.levels) || [];
  if (!levels.length) api("GET", "/api/study").then(x => { levels = x.levels || []; OP.st = OP.st || x; info(); }).catch(() => {});
  const item = (r, extra = "") => `<a class="learn-item" data-ln="${esc(r.moves.join(","))}" data-name="${esc((r.eco ? r.eco + " " : "") + (r.name || r.family))}" data-side="${r.side}">
      <span class="op-ln"><b>${esc(r.name || r.family)}</b><span class="muted small">${esc(sanLine(r.san))}</span></span>${extra}</a>`;
  const showDefault = async () => {
    let w = { recent: [], days: 90 }, b = { recent: [] }, mine = [];
    try { [w, b, mine] = await Promise.all([api("GET", "/api/theory/recent?color=White"), api("GET", "/api/theory/recent?color=Black"),
      api("GET", "/api/repertoire/openings").then(x => x.openings)]); } catch (e) {}
    if ($("#ln-q", bg).value.trim()) return;
    const had = new Set(mine.map(o => o.color + "|" + o.opening.replace(/^[A-E]\d\d\s/, "").split(":")[0]));
    const sec = (title, rs, c) => rs.length ? `<div class="learn-sec">${title}</div>` + rs.map(r => item({ ...r, side: c },
      `<span class="muted small num" title="your games in the last ${w.days} days, and before">${had.has(c + "|" + r.family) ? "learning · " : ""}${r.recent} lately${r.before ? ` · ${r.before} before` : ""}</span>`)).join("") : "";
    $("#ln-list", bg).innerHTML = (sec(`What you play now, as White · last ${w.days} days`, w.recent, "White") + sec(`What you play now, as Black · last ${w.days} days`, b.recent, "Black"))
      + `<div class="muted small" style="margin-top:8px">Ranked by your recent games, not all-time, so old habits don't crowd out what you play now. Or search any opening by name.</div>`;
    bind();
  };
  const bind = () => $$(".learn-item", bg).forEach(a => a.onclick = () => pick(a));
  const pick = async a => {
    $$(".learn-item", bg).forEach(x => x.classList.toggle("on", x === a));
    const moves = a.dataset.ln ? a.dataset.ln.split(",") : [];
    const steps = moves.length ? await playLineFrom(START_FEN, moves) : [];
    color = a.dataset.side || color;
    sel = { moves, name: a.dataset.name, steps };
    drawSel();
    info();
  };
  const drawSel = () => board.draw({ fen: sel && sel.steps.length ? sel.steps[sel.steps.length - 1].fen : START_FEN,
    lastUci: sel && sel.steps.length ? sel.steps[sel.steps.length - 1].uci : null, flipped: color === "Black" });
  const lvl = () => levels.find(x => x.level === level);
  const lenTxt = () => { const x = lvl(); return x ? (x.moves ? `${x.moves} of your moves` : "named theory, then 4 of your moves from Stockfish") : ""; };
  const info = (msg = "") => {
    if (!sel) { $("#ln-info", bg).innerHTML = `<p class="muted small">Pick an opening on the left to preview it.</p>`; return; }
    $("#ln-info", bg).innerHTML = `<b>${esc(opName(sel.name))}</b><div class="muted small">${esc(sanLine(sel.steps.map(s => s.san)))}</div>
      <div class="row" style="gap:6px;margin:8px 0"><span class="muted small">I play it as</span>
        <span class="chip ${color === "White" ? "on" : ""}" data-lc="White">White</span><span class="chip ${color === "Black" ? "on" : ""}" data-lc="Black">Black</span></div>
      <div class="row" style="gap:6px;margin:0 0 8px"><span class="muted small">Length</span><span class="seg" role="group" aria-label="Line length">${levels.map(x => `<button class="seg-b ${level === x.level ? "on" : ""}" data-lvl="${x.level}" title="${esc(x.name)}">${x.level}</button>`).join("")}</span>
        <span class="muted small">${lvl() ? `${esc(lvl().name)}: ${lenTxt()}` : ""}</span></div>
      <p class="muted small" style="margin:0 0 10px">Adds your moves along this line, then its main line and every named reply from the opening list, then Stockfish's moves past the end of theory. 3 is the recommendation for your rating (${S.settings.rating_used ?? S.settings.rating}); you can change it later on the opening's card. Where you already starred a different move, this line's move takes its place.</p>
      <div class="row" style="gap:8px"><button class="primary" id="ln-add">Add to my repertoire</button><span class="muted small" id="ln-msg">${msg}</span></div>`;
    $$("[data-lc]", bg).forEach(c => c.onclick = () => { color = c.dataset.lc; drawSel(); info(); });
    $$("[data-lvl]", bg).forEach(b => b.onclick = () => { level = +b.dataset.lvl; info(); });
    $("#ln-add", bg).onclick = async () => {
      const btn = $("#ln-add", bg); btn.disabled = true; $("#ln-msg", bg).textContent = "Adding… Stockfish fills in past the end of theory (a few seconds)";
      try {
        const r = await api("POST", "/api/repertoire/learn", { color, moves: sel.moves, level });
        $("#ln-info", bg).innerHTML = `<b>${esc(opName(r.opening))}</b><p>Added ${r.added} move${r.added === 1 ? "" : "s"} as ${color}: ${r.theory} from theory, ${r.engine} from Stockfish${r.replaced ? `; ${r.replaced} earlier star${r.replaced === 1 ? "" : "s"} changed to fit` : ""}. That makes ${r.lines.lines} line${r.lines.lines === 1 ? "" : "s"} as ${color}; you learn ${S.settings.new_lines_per_day ?? 3} new ones a day.</p>
          <div class="row" style="gap:8px"><button class="primary" id="ln-drill">Study it now</button><button id="ln-more">Add another</button><button class="ghost" id="ln-done">Done</button></div>`;
        $("#ln-drill", bg).onclick = () => { close(); sessStart({ color, opening: r.opening }); };
        $("#ln-more", bg).onclick = () => { sel = null; info(); showDefault(); };
        $("#ln-done", bg).onclick = () => { close(); OP.tab = "study"; VIEWS.openings(); };
      } catch (e) { $("#ln-msg", bg).textContent = e.message; btn.disabled = false; }
    };
  };
  let t;
  $("#ln-q", bg).oninput = e => {
    clearTimeout(t);
    const q = e.target.value.trim();
    if (!q) return showDefault();
    t = setTimeout(async () => {
      const r = (await api("GET", "/api/theory/search?q=" + encodeURIComponent(q))).results;
      if ($("#ln-q", bg).value.trim() !== q) return;
      $("#ln-list", bg).innerHTML = r.length ? r.map(x => item(x)).join("") : `<div class="muted small">No opening by that name.</div>`;
      bind();
    }, 180);
  };
  $("#ln-q", bg).focus();
  info();
  showDefault();
}
