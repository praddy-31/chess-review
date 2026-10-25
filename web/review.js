// Chess Review - the Review: board, eval graph, move card, Moves / Summary / Table / Export tabs. Shares the page's globals with app.js (api, S, VIEWS, $, esc, ...).

// ------------------------------------------------------------------ Review
const R = { idx: 0, flipped: false, line: null, retry: null, whatif: null, tab: "move", board: null, flaggedOnly: false };

// a player's name in the Review header: your repeat opponents link to their page
function oppName(g, side) {
  const name = side === "White" ? g.white : g.black;
  if (!g.me || g.me === side || !name) return esc(name);
  const n = oppCounts()[name.toLowerCase()] || 0;
  return n >= 2 ? `<a class="opp-link" href="#/opponent/${encodeURIComponent(name)}" title="${n} games against them">${esc(name)}</a>` : esc(name);
}

// Review with no game open: pick one (most recently played analysed games first).
async function renderReviewPicker() {
  await loadGames();
  const done = S.games.filter(g => g.analysed);
  const m = $("#main");
  const row = g => `<tr class="click" data-id="${esc(g.id)}"><td class="muted">${esc((g.played_at || "").slice(0, 10) || "—")}</td>
    <td>${g.me ? `<span class="side ${g.me}"></span> ` : ""}<b>${esc(g.opponent ?? `${g.white} – ${g.black}`)}</b>${g.opp_elo ? ` <span class="muted">(${g.opp_elo})</span>` : ""}</td>
    <td><span class="res ${g.outcome}">${g.outcome === "unknown" ? esc(g.result) : cap(g.outcome)}</span></td>
    <td class="muted c-tc">${esc(g.tc_category && g.tc_category !== "unknown" ? cap(g.tc_category) : "")}</td>
    <td class="muted c-op" title="${esc(g.opening || "")}">${esc(g.opening || "")}</td>
    <td class="num"><b>${g.accuracy != null ? g.accuracy.toFixed(1) : ""}</b></td></tr>`;
  m.innerHTML = `<div class="page" style="max-width:980px">
    <div class="page-head"><h1>Review</h1><span class="muted">Choose a game</span><span class="spacer"></span><a class="btn" href="#/library">Open the Library</a></div>
    ${done.length ? `<div class="filters"><input type="search" id="rp-q" placeholder="Opponent or opening…"></div>
      <div class="card fitwrap" style="padding:4px 6px"><table class="list fit picks"><thead><tr><th class="c-date">Date</th><th class="c-who">Opponent</th><th class="c-res">Result</th><th class="c-tc">Time</th><th class="c-op">Opening</th><th class="num c-acc">Accuracy</th></tr></thead>
      <tbody id="rp-rows"></tbody></table></div>
      <div class="muted small" style="margin-top:8px">Analysed games only. To review a new game, tick it in the Library and press Analyse.</div>`
      : `<div class="card empty"><h2>No analysed games yet</h2><p class="muted">Pick games in the Library and press Analyse; they show up here.</p></div>`}
  </div>`;
  const draw = () => {
    const words = normSearch($("#rp-q")?.value || "").split(" ").filter(Boolean);
    const rows = done.filter(g => { const hay = normSearch([g.white, g.black, g.opening].join(" ")); return words.every(w => hay.includes(w)); }).slice(0, 50);
    $("#rp-rows").innerHTML = rows.map(row).join("") || `<tr><td colspan="6" class="muted" style="text-align:center;padding:16px">No games match.</td></tr>`;
    $$("#rp-rows tr.click").forEach(tr => tr.onclick = () => (location.hash = `#/review/${encodeURIComponent(tr.dataset.id)}`));
  };
  if (done.length) { $("#rp-q").oninput = draw; draw(); }
}

VIEWS.review = async function (id, opts = {}) {
  if (!id) return renderReviewPicker();
  const g = await api("GET", `/api/games/${encodeURIComponent(id)}`);
  if (!S.games) { try { await loadGames(); } catch (e) {} }
  const sameGame = S.review && S.review.id === id;
  S.review = g;
  R.lastId = id; $("#nav-review").href = `#/review/${encodeURIComponent(id)}`;
  const m = $("#main");
  const me = g.me;
  const res = g.outcome === "win" ? "You won" : g.outcome === "loss" ? "You lost" : g.outcome === "draw" ? "Draw" : esc(g.result);
  const acc = g.analysed && g.accuracy != null ? `accuracy ${g.accuracy.toFixed(1)}${g.opp_accuracy != null ? ` vs ${g.opp_accuracy.toFixed(1)}` : ""}` : "";
  const sub = [res, g.tc_category && g.tc_category !== "unknown" ? `${cap(g.tc_category)} ${fmtTC(g.time_control)}` : "", (g.played_at || "").slice(0, 10), g.opening, acc].filter(Boolean).join(" · ");
  m.innerHTML = `<div class="page page-wide">
    <div class="page-head rv-head">
      <div><div class="crumb"><a href="#/review">Review</a> / this game</div><h1>${oppName(g, "White")} vs ${oppName(g, "Black")}</h1><div class="small ink2" style="margin-top:2px">${esc(sub)}</div></div>
      <span class="spacer"></span>
      ${g.url ? `<button class="ghost" id="rv-open">Open on ${g.source === "lichess" ? "Lichess" : "chess.com"}</button>` : ""}
      ${g.analysed ? `<button id="rv-again" title="Run the engine again with the current settings">Re-analyse</button>` : ""}
      <button class="ghost danger" id="rv-del">Delete</button>
    </div>
    <div id="rv-body"></div></div>`;
  if ($("#rv-open")) $("#rv-open").onclick = () => api("POST", "/api/open", { url: g.url }).catch(e => toast(e.message, true));
  if ($("#rv-again")) $("#rv-again").onclick = () => { analyse(g.id, me); toast("Re-analysing…"); };
  $("#rv-del").onclick = async () => {
    if (!$("#rv-del").dataset.armed) { $("#rv-del").dataset.armed = 1; $("#rv-del").textContent = "Click again to delete"; return; }
    await api("DELETE", `/api/games/${encodeURIComponent(g.id)}`); S.review = null; R.lastId = null; $("#nav-review").href = "#/review";
    toast("Deleted"); location.hash = "#/library";
  };
  if (!g.analysed) return renderUnanalysed(g);
  const rv = g.review;
  R.whatif = null;
  if (S.reviewJump && S.reviewJump.id === id) { R.idx = S.reviewJump.ply; R.line = null; R.retry = null; S.reviewJump = null; R.flipped = rv.orientation === "black"; if (!sameGame) R.tab = "move"; }
  else if (!sameGame || opts.keepPly === false) {
    const fl = rv.plies.filter(p => p.flagged);
    R.idx = sameGame && opts.keepPly !== false ? R.idx : (fl.length ? fl[0].ply : 0);
    R.flipped = rv.orientation === "black"; R.line = null;
    if (!sameGame) R.tab = "move";
  }
  renderReview();
  pollJobs();
};

function renderUnanalysed(g) {
  const j = S.jobs[g.id] || g.job;
  const body = $("#rv-body");
  body.innerHTML = `<div class="card" style="max-width:560px">
    <h2>Not analysed yet</h2>
    <div id="rv-job"></div></div>`;
  updateReviewJob(j || { state: "none" });
}

function updateReviewJob(j) {
  const box = $("#rv-job");
  if (!box) {
    if (j.state === "running" || j.state === "queued") {
      const btn = $("#rv-again"); if (btn) { btn.disabled = true; btn.textContent = j.state === "running" ? `Re-analysing ${j.total ? Math.round(100 * j.done / j.total) : 0}%` : "Queued"; }
    }
    return;
  }
  const g = S.review;
  if (j.state === "running" || j.state === "queued") {
    const pct = j.total ? Math.round(100 * j.done / j.total) : 0;
    box.innerHTML = `<p>${j.state === "queued" ? "Waiting for the game ahead of it…" : `Stockfish is going through the game: move ${Math.ceil(j.done / 2)} of ${Math.ceil(j.total / 2) || "?"}.`}</p>
      <div class="prog" style="width:100%;height:8px"><i style="width:${pct}%"></i></div>
      <div class="row" style="margin-top:10px"><button id="rv-cancel">Cancel</button></div>`;
    $("#rv-cancel").onclick = () => api("POST", `/api/games/${encodeURIComponent(g.id)}/cancel`).then(pollJobs);
    return;
  }
  const noSf = !S.status?.engines?.stockfish;
  box.innerHTML = `${j.state === "error" ? `<p class="status-no">${esc(j.error)}</p>` : ""}
    ${noSf ? `<p class="status-no">Stockfish isn't installed yet - see <a href="#/setup">Setup</a>.</p>` : ""}
    <p class="muted">${g.n_plies} half-moves. At depth ${S.settings.depth} this takes about ${estMin(g.n_plies)} min.</p>
    <div class="row">${g.player_color
      ? `<span>You played <span class="side ${g.player_color}"></span> <b>${g.player_color}</b></span> <a id="rv-swap" class="small">switch</a><span style="flex:1"></span><button class="primary" id="rv-go" ${noSf ? "disabled" : ""}>Analyse</button>`
      : `<span>Which side were you?</span><span style="flex:1"></span><button class="primary" data-c="White" ${noSf ? "disabled" : ""}><span class="side White"></span> White</button><button class="primary" data-c="Black" ${noSf ? "disabled" : ""}><span class="side Black"></span> Black</button>`}
    </div>`;
  if ($("#rv-go")) $("#rv-go").onclick = () => analyse(g.id, g.player_color);
  if ($("#rv-swap")) $("#rv-swap").onclick = async () => {
    const c = g.player_color === "White" ? "Black" : "White";
    await api("POST", `/api/games/${encodeURIComponent(g.id)}/side`, { color: c }); g.player_color = c; updateReviewJob(j);
  };
  $$("button[data-c]", box).forEach(b => b.onclick = () => analyse(g.id, b.dataset.c));
}

function renderReview() {
  const rv = S.review.review;
  const body = $("#rv-body");
  const stale = (rv.analysis_version || 1) < rv.current_version;
  body.innerHTML = `<div class="rv-meta" id="rv-meta"></div>${stale ? `<div class="card row notice" style="margin-bottom:12px;gap:10px"><span class="muted">Analysed with an older version: no explanations, no Great / Brilliant labels and no labels for your opponent's moves.</span><span style="flex:1"></span><button class="sm" id="stale-go">Re-analyse</button></div>` : ""}
  <div class="rv">
    <div class="rv-left">
      <div class="player" id="pl-top"></div>
      <div class="boardwrap"><div class="evalbar" id="evalbar"><i></i><b></b></div><svg class="board" id="board" role="img" aria-label="Board"></svg></div>
      <div class="player" id="pl-bot"></div>
      <div class="navbar">
        <button class="nb" data-go="start" aria-label="Start" title="Start (Home)">⏮</button><button class="nb" data-go="-1" aria-label="Previous move" title="Previous move (←)">◀</button>
        <button class="nb" data-go="1" aria-label="Next move" title="Next move (→)">▶</button><button class="nb" data-go="end" aria-label="End" title="End (End)">⏭</button>
        <button class="nb" data-flag="-1" title="Previous flagged move (↑)">Previous flagged</button><button class="nb" data-flag="1" title="Next flagged move (↓)">Next flagged</button>
        <button class="nb" id="flip" title="Flip the board (F)">Flip</button>
        <span class="hint">← → moves · ↑ ↓ flagged · B best line · R reply</span>
      </div>
      <div class="card graphcard"><svg class="evalgraph" id="graph" role="img" aria-label="Win chance over the game"></svg></div>
    </div>
    <div class="rv-right">
      <div class="tabs" role="tablist">${[["move", "Moves"], ["summary", "Summary"], ["table", "Table"], ["notes", "Notes"], ["export", "Export"]].map(([k, l]) => `<a role="tab" data-tab="${k}" class="${R.tab === k ? "on" : ""}">${l}</a>`).join("")}</div>
      <div id="rv-tab"></div>
    </div>
  </div>`;
  R.board = new ChessBoard($("#board"));
  R.board.pieces = S.settings.pieces || "cburnett";
  if ($("#stale-go")) $("#stale-go").onclick = () => { analyse(S.review.id, S.review.me); toast("Re-analysing…"); $("#stale-go").disabled = true; };
  $$("[data-go]", body).forEach(b => b.onclick = () => go(b.dataset.go === "start" || b.dataset.go === "end" ? b.dataset.go : +b.dataset.go));
  $$("[data-flag]", body).forEach(b => b.onclick = () => jumpFlag(+b.dataset.flag));
  $("#flip").onclick = () => { R.flipped = !R.flipped; draw(); };
  $$(".tabs a", body).forEach(a => a.onclick = () => { R.tab = a.dataset.tab; R.retry = null; $$(".tabs a", body).forEach(x => x.classList.toggle("on", x === a)); renderTab(); draw(); });
  $("#graph").onclick = e => {
    const r = e.currentTarget.getBoundingClientRect(), g = R.graphGeom;
    if (!g) return;
    const x = (e.clientX - r.left) / r.width * g.W;
    setIdx(Math.round((x - g.padl) / g.gw * rv.plies.length));
  };
  document.onkeydown = e => {
    if (e.target.closest("input,textarea,select")) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key;
    if (k === "ArrowRight") go(1); else if (k === "ArrowLeft") go(-1);
    else if (k === "ArrowDown") jumpFlag(1); else if (k === "ArrowUp") jumpFlag(-1);
    else if (k === "Home") go("start"); else if (k === "End") go("end");
    else if (k === "f") { R.flipped = !R.flipped; draw(); }
    else if (k === "b") playLine("best"); else if (k === "r") playLine("ref");
    else if (k === "Escape") { R.line = null; R.retry = null; R.whatif = null; draw(); }
    else return;
    e.preventDefault();
  };
  window.onresize = () => { if (S.view === "review" && S.review?.review) { drawGraph(); if (R.tab === "summary") renderTab(); } };
  renderTab();
  draw();
  loadNotes(S.review.id);
}

// ---------------------------------------------------------------- V7: your notes and tags on a game
async function loadNotes(id) {
  try { R.notes = await api("GET", `/api/games/${encodeURIComponent(id)}/notes`); } catch (e) { R.notes = { notes: {}, tags: [] }; }
  R.notesId = id;
  notesBar(); notesTabLabel();
  if (R.tab === "move" || R.tab === "notes") renderTab();
}
// V11: the Notes tab counts the game note and every move note
function notesTabLabel() {
  const a = $('.tabs a[data-tab="notes"]'); if (!a || !R.notes) return;
  const n = Object.keys(R.notes.notes).length;
  a.innerHTML = `Notes${n ? ` <span class="muted small">${n}</span>` : ""}`;
}
function notesBar() {
  const el = $("#rv-meta"); if (!el || !R.notes) return;
  const id = S.review.id, n = R.notes, note = n.notes[0] || "";
  el.innerHTML = `<div class="rv-tags"><span class="muted small">Tags</span>${n.tags.map(t => `<span class="chip on tagchip">${esc(t)}<button class="x" data-untag="${esc(t)}" aria-label="Remove tag ${esc(t)}">×</button></span>`).join("")}
      <input id="tag-in" list="tag-list" placeholder="+ tag" style="width:110px"><datalist id="tag-list"></datalist>
      <span class="spacer" style="flex:1"></span><a class="small" id="gnote-tog">${note ? "Game note" : "+ Note on this game"}</a></div>
    <div id="gnote-box" ${note ? "" : "hidden"}><textarea id="gnote" rows="2" placeholder="What to remember from this game…">${esc(note)}</textarea></div>`;
  const setTags = async tags => { try { n.tags = (await api("POST", `/api/games/${encodeURIComponent(id)}/tags`, { tags })).tags; } catch (e) { toast(e.message, true); } notesBar(); if (S.games) { const g = S.games.find(x => x.id === id); if (g) g.tags = n.tags; } };
  $$("[data-untag]", el).forEach(b => b.onclick = () => setTags(n.tags.filter(t => t !== b.dataset.untag)));
  const tin = $("#tag-in");
  tin.onkeydown = e => { if (e.key === "Enter" && tin.value.trim()) { e.preventDefault(); setTags([...n.tags, tin.value.trim()]); } };
  tin.onfocus = () => api("GET", "/api/tags").then(x => { const dl = $("#tag-list"); if (dl) dl.innerHTML = x.tags.map(t => `<option value="${esc(t.tag)}">`).join(""); }).catch(() => {});
  $("#gnote-tog").onclick = () => { $("#gnote-box").hidden = false; $("#gnote").focus(); };
  $("#gnote").onchange = () => saveNote(0, $("#gnote").value);
}
async function saveNote(ply, text) {
  const id = S.review.id;
  try { R.notes = await api("POST", `/api/games/${encodeURIComponent(id)}/notes`, { ply, text }); toast(text.trim() ? "Note saved" : "Note removed"); }
  catch (e) { toast(e.message, true); }
  notesTabLabel(); if (R.tab === "notes") renderTab();
}

function setIdx(i) { const n = S.review.review.plies.length; R.line = null; R.retry = null; R.whatif = null; R.idx = Math.max(0, Math.min(n, i)); draw(); }
function go(d) {
  if (R.retry) return;
  if (R.whatif) { if (typeof d === "string") { R.whatif = null; draw(); return; } return whatifGo(d); }
  if (R.line) {
    if (d === 1 && R.line.pos < R.line.steps.length) R.line.pos++;
    else if (d === -1) { if (R.line.pos > 1) R.line.pos--; else R.line = null; }
    else if (typeof d === "string") R.line = null;
    if (typeof d !== "string") return draw();
  }
  if (d === "start") setIdx(0); else if (d === "end") setIdx(S.review.review.plies.length); else setIdx(R.idx + d);
}
function jumpFlag(d) {
  const fl = S.review.review.plies.filter(p => p.flagged).map(p => p.ply);
  if (!fl.length) return;
  let t = d > 0 ? fl.find(x => x > R.idx) : [...fl].reverse().find(x => x < R.idx);
  if (t === undefined) t = d > 0 ? fl[0] : fl[fl.length - 1];
  setIdx(t);
}
function playLine(kind, pos) {
  if (!R.idx || R.retry || R.whatif) return;
  const p = S.review.review.plies[R.idx - 1];
  if (!p.severity) return;
  const steps = kind === "best" ? p.best_line : p.refutation;
  if (!steps || !steps.length) return;
  R.line = { kind, steps, pos: pos || 1 };
  draw();
}

const nameOf = (rv, color) => color === "White" ? rv.white : rv.black;
const shows_before = p => p && (p.mine || p.flagged);   // my moves and flagged ones: the position before, with arrows

function draw() {
  const rv = S.review.review;
  const p = R.idx ? rv.plies[R.idx - 1] : null;
  let fen, last = null, arrows = [], selected = null, dots = [];
  R.board.onSquare = null;
  R.board.setMoves(null);
  let animate = !!R.whatifAnimate; R.whatifAnimate = false;
  if (R.retry) {
    fen = R.retry.fen;
    if (R.retry.result && R.retry.result.uci) arrows = [[R.retry.result.uci, sevColor(R.retry.result.label)]];
  } else if (R.whatif) {
    const w = R.whatif;
    fen = whatifFen(); last = w.pos ? w.steps[w.pos - 1].uci : null;
  } else if (R.line) { const st = R.line.steps[R.line.pos - 1]; fen = st.fen; last = st.uci; arrows = [[st.uci, cssv("--accent")]]; }
  else if (!p) fen = rv.start_fen;
  else if (shows_before(p)) {
    fen = p.fen_before;
    if (p.best_uci !== p.played_uci) arrows.push([p.best_uci, cssv("--sev-best")]);
    arrows.push([p.played_uci, sevColor(p.severity)]);
    const prev = R.idx > 1 ? rv.plies[R.idx - 2] : null;
    if (prev) last = prev.played_uci;
  } else { fen = p.fen_after; last = p.played_uci; }
  R.board.draw({ fen, lastUci: last, arrows, flipped: R.flipped, selected, dots, animate });
  if (R.retry) { if (!R.retry.done && !R.retry.busy && R.retry.moves.length) R.board.setMoves(R.retry.moves, retryMove); }
  else if (R.whatif) { const f = fen; getPos(f).then(ps => { if (R.whatif && whatifFen() === f && R.board.state.fen === f) R.board.setMoves(ps.moves, whatifPlay); }).catch(() => {}); }
  else if (!R.line) reviewPlayable();
  // eval bar = the position on the board
  const evalAt = i => (i > 0 ? rv.plies[i - 1].eval_num : 0);
  if (!R.line && !R.retry && !R.whatif) R.shownEval = shows_before(p) ? evalAt(R.idx - 1) : evalAt(R.idx);
  const e = R.shownEval ?? 0;
  const white = winPct(e) / 100;
  const bar = $("#evalbar");
  bar.classList.toggle("flip", R.flipped);
  $("i", bar).style.height = ((R.flipped ? 1 - white : white) * 100) + "%";
  $("b", bar).textContent = Math.abs(e) >= 10 ? "M" : (e >= 0 ? "+" : "") + e.toFixed(1);
  const clockOf = color => { for (let i = R.idx - 1; i >= 0; i--) if (rv.plies[i].color === color) return rv.plies[i].clock; return null; };
  const pl = color => {
    const elo = color === "White" ? S.review.white_elo : S.review.black_elo;
    return `<span class="side ${color}"></span><b>${esc(nameOf(rv, color))}</b>${elo ? `<span class="muted">${elo}</span>` : ""}${color === rv.player ? '<span class="you">you</span>' : ""}<span style="flex:1"></span>${clockOf(color) != null ? `<span class="clock">${fmtClock(clockOf(color))}</span>` : ""}`;
  };
  $("#pl-top").innerHTML = pl(R.flipped ? "White" : "Black");
  $("#pl-bot").innerHTML = pl(R.flipped ? "Black" : "White");
  drawGraph();
  if (R.tab === "move") renderMoveTab();
}

// Eval graph under the board: White's win chance over the game, labelled axes,
// opening shaded, errors marked (missed chances ringed), current move as a line.
function drawGraph() {
  const rv = S.review.review, svg = $("#graph"), n = rv.plies.length;
  if (!svg || !n) return;
  const W = Math.max(320, svg.clientWidth || 560), H = 118;
  const padl = 82, gw = W - padl - 6, gh = H - 26, top = 6;
  R.graphGeom = { W, padl, gw };
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("height", H);
  const X = i => padl + i / n * gw, Y = w => top + gh - w / 100 * gh;
  const pts = [[X(0), Y(rv.start_win)], ...rv.plies.map((p, i) => [X(i + 1), Y(winPct(p.eval_num))])];
  const area = `M${X(0)},${Y(0)} ` + pts.map(([a, b]) => `L${a.toFixed(1)},${b.toFixed(1)}`).join(" ") + ` L${X(n)},${Y(0)} Z`;
  // phases by Lichess's divider (engine/divider.py): the band ends at the first move of the next phase
  const openEnd = (() => { const i = rv.plies.findIndex(p => p.game_phase !== "Opening"); return i < 0 ? n : i; })();
  const endStart = (() => { const i = rv.plies.findIndex(p => p.game_phase === "Endgame"); return i < 0 ? null : i; })();
  let s = `<text x="0" y="${top + 10}" font-size="11.5" fill="var(--ink-2)">White better</text>
    <text x="0" y="${top + gh / 2 + 4}" font-size="11.5" fill="var(--muted)">Equal</text>
    <text x="0" y="${top + gh - 1}" font-size="11.5" fill="var(--ink-2)">Black better</text>
    <rect x="${padl}" y="${top}" width="${gw}" height="${gh}" fill="#2c2c2c"/>
    <rect x="${padl}" y="${top}" width="${X(openEnd) - padl}" height="${gh}" fill="#232323"/>
    ${endStart != null ? `<rect x="${X(endStart)}" y="${top}" width="${X(n) - X(endStart)}" height="${gh}" fill="#232323"/>` : ""}
    <path d="${area}" fill="#e9e9e9"/>
    <line x1="${padl}" x2="${padl + gw}" y1="${top + gh / 2}" y2="${top + gh / 2}" stroke="#7a7a7a" stroke-dasharray="3 4"/>
    <text x="${padl + 5}" y="${top + 12}" font-size="10.5" fill="#8a8a8a">Opening</text>
    ${X(openEnd) + 70 < padl + gw && openEnd !== endStart ? `<text x="${X(openEnd) + 5}" y="${top + 12}" font-size="10.5" fill="#8a8a8a">${endStart != null && X(endStart) - X(openEnd) < 80 ? "" : "Middlegame"}</text>` : ""}
    ${endStart != null ? `<text x="${X(endStart) + 5}" y="${top + 12}" font-size="10.5" fill="#8a8a8a">Endgame</text>` : ""}`;
  rv.plies.forEach((p, i) => {
    if (!marked(p)) return;
    const x = X(i + 1), y = Y(winPct(p.eval_num));
    const col = ERRS.includes(p.severity) || ["Brilliant", "Great"].includes(p.severity) ? sevColor(p.severity) : cssv("--sev-missed");
    s += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${p.mine ? 5.5 : 4.5}" fill="${col}" stroke="${p.missed ? cssv("--sev-missed") : "#111"}" stroke-width="${p.missed ? 2.5 : 1}"><title>${esc(nameOf(rv, p.color))}: ${esc(p.label + p.san)} · ${p.severity}${p.missed ? " · missed chance" : ""}</title></circle>`;
  });
  const step = n > 120 ? 20 : n > 60 ? 10 : 5;
  for (let mv = step; mv <= Math.ceil(n / 2); mv += step) s += `<text x="${X(2 * mv - 1).toFixed(1)}" y="${H - 4}" font-size="10.5" text-anchor="middle" fill="var(--muted)">${mv}</text>`;
  s += `<text x="${padl}" y="${H - 4}" font-size="10.5" fill="var(--muted)">move</text>`;
  s += `<line x1="${X(R.idx)}" x2="${X(R.idx)}" y1="2" y2="${top + gh + 2}" stroke="var(--accent)" stroke-width="2.5"/>`;
  svg.innerHTML = s;
}

// ---------------------------------------------------------------- Moves tab
function badge(sev, size = 14) {
  if (!sev) return "";
  const g = GLYPH[sev] || "";
  const icon = sev === "Best" ? `<svg width="${size * .62}" height="${size * .62}" viewBox="0 0 10 10" fill="none" stroke="#fff" stroke-width="2"><path d="M1.5 5.2 4 7.6 8.6 2.4"/></svg>`
    : sev === "Book" ? `<svg width="${size * .7}" height="${size * .62}" viewBox="0 0 12 10" fill="none" stroke="#fff" stroke-width="1.5"><path d="M6 2.2C4.6 1.3 2.8 1 1 1.2v7.4c1.8-.2 3.6.1 5 1 1.4-.9 3.2-1.2 5-1V1.2C9.2 1 7.4 1.3 6 2.2zM6 2.2v7.4"/></svg>` : g;
  return `<span class="badge-sev b-${sev}" style="--s:${size}px" title="${esc(sev)}">${icon}</span>`;
}
const missedBadge = (size = 13) => `<span class="badge-missed" style="--s:${size}px" title="Missed chance"><i></i></span>`;

function chips(steps, kind, strongFirst) {
  if (!steps || !steps.length) return "";
  return steps.map((st, i) => `<a class="mchip ${i === 0 && strongFirst ? "strong" : ""} ${R.line && R.line.kind === kind && R.line.pos === i + 1 ? "cur" : ""}" data-line="${kind}" data-pos="${i + 1}">${esc(st.label)}</a>`).join("");
}

const PHASE_SENT = {
  Attack: "had a concrete threat", Defense: "was facing a threat", Neutral: "",
};

function coachCard(p, rv) {
  if (R.retry) return retryCard(p, rv);
  if (R.whatif) return whatifCard();
  if (!p) return `<div class="coach"><div class="coach-head"><span class="mv-big">Start</span></div><p class="coach-text">Press → to step through the game, or ↓ to jump to the first flagged move. Move a piece on the board to try your own idea.</p></div>`;
  if (!p.severity) return `<div class="coach"><div class="coach-head"><span class="mv-big">${esc(p.label + p.san)}</span><span style="flex:1"></span><span class="muted small">${p.mine ? "your move" : esc(nameOf(rv, p.color)) + "’s move"}</span></div></div>`;
  const you = p.mine;
  const who = you ? "your" : `${esc(nameOf(rv, p.color))}’s`;
  const ex = p.explain || {};
  let text = ex.verdict || ex.sentence;
  if ((p.severity === "Brilliant" || p.severity === "Great") && p.special) text = cap(p.special) + ".";
  if (!text) {
    text = p.severity === "Book" ? "Known opening theory."
      : p.severity === "Brilliant" ? "A sound sacrifice: the engine’s move, and it leaves material that can be taken."
      : p.severity === "Great" ? "The only good move: everything else would have cost at least 20 points of win chance."
      : p.severity === "Best" ? "The engine’s move." : `Close to the engine’s move (${p.best_san} was a little better).`;
  }
  const errCol = ERRS.includes(p.severity) ? sevColor(p.severity) : cssv("--sev-best");
  const changed = p.win_before !== p.win_after;
  const sit = [p.standing === "Winning" ? `${you ? "You were" : esc(nameOf(rv, p.color)) + " was"} winning.` : p.standing === "Losing" ? `${you ? "You were" : esc(nameOf(rv, p.color)) + " was"} worse.` : "The position was balanced.",
    p.phase !== "Neutral" && p.phase_why && p.phase_why !== "threat probes not run" ? cap(esc(p.phase_why)).replace(/^Your/, "Your") + "." : ""].join(" ");
  const time = p.spent != null ? ` · ${p.spent.toFixed(0)} s` : "";
  return `<div class="coach">
    <div class="coach-head"><span class="mv-big">${esc(p.label + p.san)}</span>${badge(p.severity, 18)}<span class="sev-word">${p.severity}</span>
      ${p.missed ? `${missedBadge(16)}<span class="sev-word">Missed chance</span>` : ""}
      <span style="flex:1"></span><span class="muted small">${you ? "your move" : who + " move"}${time}</span></div>
    <p class="coach-text">${esc(text)}</p>${(ex.tags || []).length || (p.rep && !p.rep.followed) ? `<div class="coach-tags">${(ex.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join("")}${p.rep && !p.rep.followed ? `<span class="tag rep" title="Your repertoire move here">left your repertoire (planned ${esc(p.rep.planned)})</span>` : ""}</div>` : ""}
    ${changed || ERRS.includes(p.severity) ? `<div class="winbar"><div class="wb-track"><i class="ghost" style="width:${p.win_before}%;background:${errCol}"></i><i style="width:${p.win_after}%;background:${errCol}"></i></div>
      <span class="small">${who} win chance <b>${p.win_before}% → ${p.win_after}%</b></span></div>` : ""}
    <div class="coach-rows">
      ${p.played_uci !== p.best_uci ? `<span class="muted">Better was</span><span>${chips(p.best_line, "best", true)}</span>` : (p.best_line.length > 1 ? `<span class="muted">Engine’s line</span><span>${chips(p.best_line, "best", false)}</span>` : "")}
      ${p.refutation.length && p.played_uci !== p.best_uci ? `<span class="muted">What happened</span><span>${chips(p.refutation, "ref", false)}</span>` : ""}
      ${ERRS.includes(p.severity) || p.missed ? `<span class="muted">Situation</span><span class="ink2">${sit}</span>` : ""}
      ${pracRow(p)}
      ${p.maia ? `<span class="muted">At your level</span><span class="ink2">Most players would play <b>${esc(p.maia.top)}</b>; ${p.maia.p_best}% find the engine’s move.${p.maia.tags.length ? " " + p.maia.tags.map(t => `<span class="tag">${t}</span>`).join(" ") : ""}</span>` : ""}
    </div>
    <div class="coach-actions">
      ${you && (ERRS.includes(p.severity) || p.missed) ? `<button id="retry-go" class="primary sm">Retry this move</button>` : ""}
      ${!R.line ? `<button class="sm ghost" id="to-board" title="Open this position on the analysis board">Analyse on the Board</button>` : ""}
      ${R.line ? `<button class="sm" id="exit-line">Back to the game (Esc)</button><span class="muted small">${R.line.kind === "best" ? "Better line" : "What happened"}, move ${R.line.pos} of ${R.line.steps.length}</span>` : ""}
    </div>
  </div>`;
}

// ---------------------------------------------------------------- practical move (V8)
// Maia at your rating + Stockfish: the move people at your level find that is nearly as good as the best.
let PRAC_OFF = false;
const PRAC = new Map();      // fen -> result | "pending" | null
function pracWanted(p) { return p && p.mine && p.played_uci !== p.best_uci && !PRAC_OFF; }
function pracRow(p) {
  if (!pracWanted(p)) return "";
  const r = PRAC.get(p.fen_before);
  if (!r || r === "pending" || r.same || r.uci === p.played_uci) return "";
  return `<span class="muted" title="The most likely move for players at your level that is within 5 points of win chance of the best">Practical</span><span class="ink2"><a class="mchip" data-prac="${esc(r.uci)}">${esc(r.san)}</a> ${r.p}% at your level${r.gap ? `, ${r.gap} points off the best` : ", as good as the best"} (${esc(r.best_san)} is found by ${r.p_best}%).</span>`;
}
function pracFetch(p, redraw) {
  if (!pracWanted(p) || PRAC.has(p.fen_before)) return;
  PRAC.set(p.fen_before, "pending");
  api("GET", "/api/practical?fen=" + encodeURIComponent(p.fen_before)).then(d => {
    PRAC.set(p.fen_before, d.practical || null);
    if (!d.available) PRAC_OFF = true;
    if (d.practical && !d.practical.same) redraw();
  }).catch(() => PRAC.set(p.fen_before, null));
}

// ---------------------------------------------------------------- retry this move
async function startRetry() {
  const rv = S.review.review, p = rv.plies[R.idx - 1];
  R.line = null;
  R.retry = { ply: p.ply, fen: p.fen_before, moves: [], result: null, tries: 0, done: false };
  R.whatif = null;
  draw();
  try { R.retry.moves = (await getPos(p.fen_before)).moves; draw(); } catch (e) { toast(e.message, true); }
}
async function retryMove(uci, mv) {
  const r = R.retry;
  if (!r || r.busy) return;
  {
    r.busy = true; r.result = { pending: true, san: mv.san, uci: null, label: "Good" };
    draw();
    try {
      const res = await api("POST", "/api/grade", { fen: r.fen, uci, game_id: S.review.id, ply: r.ply });
      res.uci = uci; r.result = res; r.tries++;
      if (res.solved) r.done = true;
    } catch (e) { toast(e.message, true); r.result = null; }
    r.busy = false; draw();
  }
}
function retryCard(p, rv) {
  const r = R.retry, res = r.result;
  let body;
  if (!res) body = `<p class="coach-text">Find a better move for ${p.color} here: drag a piece, or click it and then a square. Your game move was ${esc(p.label + p.san)}.</p>`;
  else if (res.pending) body = `<p class="coach-text">Checking ${esc(res.san)}…</p>`;
  else if (res.solved) body = `<p class="coach-text">${badge(res.label, 16)} <b>${esc(res.san)}</b> ${res.label === "Best" ? "is the engine’s move." : `works too (${res.pp} points off the best, ${esc(res.best_san)}).`}${r.tries > 1 ? ` Found on try ${r.tries}.` : ""}</p>`;
  else if (res.label === "Good" || res.label === "Best") body = `<p class="coach-text">${badge(res.label, 16)} <b>${esc(res.san)}</b> is playable, but there is something clearly better (${res.pp} points off). Try again.</p>`;
  else body = `<p class="coach-text">${badge(res.label, 16)} <b>${esc(res.san)}</b> is a${res.label === "Inaccuracy" ? "n" : ""} ${res.label.toLowerCase()}: it costs ${res.pp} points of win chance${res.reply_line.length ? `, because of ${esc(res.reply_line[0])}` : ""}. Try again.</p>`;
  return `<div class="coach retry">
    <div class="coach-head"><span class="mv-big">Retry move ${esc(p.label.replace(/\.+$/, ""))}</span><span class="muted small">${p.color} to play</span><span style="flex:1"></span><span class="muted small">${r.tries} ${r.tries === 1 ? "try" : "tries"}</span></div>
    ${body}
    <div class="coach-actions">
      ${!r.done ? `<button class="sm" id="retry-show">Show the answer</button>` : ""}
      <button class="sm" id="retry-exit">${r.done ? "Back to the game" : "Cancel (Esc)"}</button>
      ${r.done || res?.solved ? "" : `<span class="muted small">Missed ones come back as puzzles.</span>`}
    </div></div>`;
}

function keyMoments(rv) {
  const km = rv.key_moments || [];
  if (!km.length) return "";
  return `<div class="km"><span class="muted small">Key moments</span><div class="km-row">${km.map(k => `<a class="km-card ${R.idx === k.ply ? "on" : ""}" data-ply="${k.ply}">
      <span class="km-title">${badge(k.severity, 14)}${k.missed && !ERRS.includes(k.severity) ? missedBadge(13) : ""}${esc(k.label)}</span>
      <span class="km-text">${esc(k.text)}</span></a>`).join("")}</div></div>`;
}

function moveCell(q) {
  if (!q) return `<span></span>`;
  const err = ERRS.includes(q.severity);
  const marks = (GLYPH[q.severity] ? badge(q.severity, 13) : "") + (q.missed ? missedBadge(12) : "");
  const bar = (err || q.missed) && q.pp ? `<span class="loss"><i style="width:${Math.min(q.pp, 50) * 2}%;background:${err ? sevColor(q.severity) : cssv("--sev-missed")}"></i></span>` : "";
  const noted = R.notes && R.notesId === S.review?.id && R.notes.notes[q.ply];
  return `<a class="mc ${q.mine ? "mine" : "theirs"} ${R.idx === q.ply ? "cur" : ""} ${err || q.missed ? "flag" : ""}" data-ply="${q.ply}" id="mv${q.ply}" title="${esc(q.severity || "")}${noted ? " · has a note" : ""}">${esc(q.san)}${marks}${noted ? `<span class="mnote" aria-label="has a note">✎</span>` : ""}${bar}</a>`;
}

function renderMoveTab() {
  const rv = S.review.review, el = $("#rv-tab");
  if (!el) return;
  const p = R.idx ? rv.plies[R.idx - 1] : null;
  const rows = [];
  for (let i = 0; i < rv.plies.length; i += 2) {
    const w = rv.plies[i];
    if (w.color !== "White") { rows.push(`<div class="mrow"><span class="mn">${w.label.replace("...", "")}</span><span></span>${moveCell(w)}</div>`); i--; continue; }
    rows.push(`<div class="mrow"><span class="mn">${w.label.replace(".", "")}</span>${moveCell(w)}${moveCell(rv.plies[i + 1])}</div>`);
  }
  const mnote = p && R.notes && R.notesId === S.review.id ? (R.notes.notes[p.ply] || "") : null;
  el.innerHTML = `<div class="stack">${coachCard(p, rv)}${mnote !== null ? `<div class="mv-note"><textarea id="mv-note" rows="${mnote ? 2 : 1}" placeholder="Note on ${esc(p.label + p.san)}…">${esc(mnote)}</textarea></div>` : ""}${keyMoments(rv)}<div class="mlist" id="movelist">${rows.join("")}</div></div>`;
  if ($("#mv-note")) $("#mv-note").onchange = e => saveNote(p.ply, e.target.value);
  if (p && !R.retry && !R.whatif) pracFetch(p, () => { if (S.review?.review === rv && R.idx === p.ply) renderMoveTab(); });
  $$("[data-prac]", el).forEach(x => x.onclick = () => { R.board.state.arrows = [[x.dataset.prac, "#4a8fd4"]]; R.board._overlay(); });
  $$("[data-ply]", el).forEach(x => x.onclick = () => setIdx(+x.dataset.ply));
  $$("[data-line]", el).forEach(x => x.onclick = () => playLine(x.dataset.line, +x.dataset.pos));
  if ($("#exit-line")) $("#exit-line").onclick = () => { R.line = null; draw(); };
  if ($("#retry-go")) $("#retry-go").onclick = startRetry;
  if ($("#to-board")) $("#to-board").onclick = openBoardFromReview;
  if (R.whatif) bindWhatif();
  if ($("#retry-exit")) $("#retry-exit").onclick = () => { R.retry = null; draw(); };
  if ($("#retry-show")) $("#retry-show").onclick = async () => {
    const r = R.retry; r.done = true;
    api("POST", "/api/retry-gave-up", { game_id: S.review.id, ply: r.ply, fen: r.fen }).catch(() => {});
    const q = rv.plies[r.ply - 1];
    r.result = { solved: true, label: "Best", san: q.best_san, uci: q.best_uci, pp: 0, best_san: q.best_san, reply_line: [] };
    draw();
  };
  const cur = $("#mv" + R.idx), list = $("#movelist");
  if (cur && list) list.scrollTop = Math.max(0, cur.offsetTop - list.offsetTop - list.clientHeight / 2);
}

// ---------------------------------------------------------------- Summary tab
function faceOff(rv) {
  const a = rv.summary, b = rv.opp_summary;
  const me = rv.player, them = me === "White" ? "Black" : "White";
  const rows = SEV.map(k => [k, a.severity[k] || 0, b ? b.severity[k] || 0 : 0]);
  const mx = Math.max(1, ...rows.map(r => Math.max(r[1], r[2])));
  const bar = (n, k, right) => `<span class="fo-bar ${right ? "r" : ""}"><i style="width:${n / mx * 100}%;background:${sevColor(k)};${right ? "opacity:.6" : ""}"></i></span>`;
  const phases = ["Opening", "Middlegame", "Endgame"].filter(k => a.by_phase[k].moves || (b && b.by_phase[k].moves));
  return `<div class="card fo">
    <p class="story">${esc(rv.story || "")}</p>
    <div class="fo-head"><div class="fo-side"><span class="muted small">${esc(nameOf(rv, me))} (you)</span><span class="fo-acc">${a.accuracy.toFixed(1)}</span></div>
      <span class="muted small fo-mid">accuracy</span>
      <div class="fo-side r"><span class="muted small">${esc(nameOf(rv, them))}</span><span class="fo-acc ink2">${b ? b.accuracy.toFixed(1) : "—"}</span></div></div>
    ${phases.length ? `<div class="fo-phases">${phases.map(k => `<span>${k} <b>${a.by_phase[k].accuracy != null ? a.by_phase[k].accuracy.toFixed(0) : "—"}</b> vs <b>${b && b.by_phase[k].accuracy != null ? b.by_phase[k].accuracy.toFixed(0) : "—"}</b></span>`).join("")}</div>` : ""}
    <div class="fo-rows">${rows.map(([k, x, y]) => `<div class="fo-row">${bar(x, k, false)}<b class="num">${x}</b><span class="fo-lab">${badge(k, 13)}${k}</span><b>${b ? y : "—"}</b>${bar(y, k, true)}</div>`).join("")}
      <div class="fo-row"><span></span><b class="num">${a.missed}</b><span class="fo-lab">${missedBadge(13)}Missed chances</span><b>${b ? b.missed : "—"}</b><span></span></div></div>
    ${a.maia_match != null ? `<div class="muted small">Maia predicted ${a.maia_match}% of your moves.</div>` : ""}
  </div>`;
}

const fmtS = s => s >= 60 ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}` : `${Math.round(s)} s`;

function clockSection(rv, width) {
  const c = rv.clock;
  if (!c) return rv.has_clocks ? "" : `<div class="card muted small">No clock times in this game, so there is no clock analysis.</div>`;
  const me = rv.player, them = me === "White" ? "Black" : "White";
  const budgetRow = (label, side, faded) => {
    if (!side) return "";
    const base = c.base + c.inc * side.moves;
    const segs = ["Opening", "Middlegame", "Endgame"].map((k, i) => [k, side.by_phase[k]?.secs || 0, i]).filter(x => x[1]);
    return `<div class="bud"><b>${label}</b><span class="bud-mid"><span class="bud-bar">${segs.map(([k, s, i]) => `<i class="seg s${i} ${faded ? "faded" : ""}" style="width:${s / base * 100}%" title="${k}: ${fmtS(s)}"></i>`).join("")}</span>
      <span class="muted small">used: ${segs.map(([k, s]) => `${k.toLowerCase()} ${fmtS(s)}`).join(" · ")}</span></span>
      <span class="bud-left"><b>${side.end_clock != null ? fmtS(side.end_clock) : "—"}</b> <span class="muted">left</span></span></div>`;
  };
  // time per move: mine up, theirs down
  const W = Math.max(360, width), H = 290, padl = 46, padr = 8, mid = 145, hh = 112;
  const mine = c.me.per_move, opp = c.opp ? c.opp.per_move : [];
  const n = Math.max(mine.length, opp.length, 1), bw = (W - padl - padr) / n;
  const cap = Math.max(c.long * 2, 30);     // seconds at full height; longer thinks are clipped and labelled
  const scaleTicks = [c.long, cap].map(v => Math.round(v));
  const bars = (ms, up, faded) => ms.map((m, k) => {
    const h = Math.max(1, Math.min(m.spent, cap) / cap * hh), x = padl + k * bw + 0.8, y = up ? mid - 9 - h : mid + 9;
    const col = m.flagged && ERRS.includes(m.severity) ? sevColor(m.severity) : faded ? "var(--grid)" : "var(--axis)";
    const over = m.spent > cap ? `<text x="${x + bw / 2}" y="${up ? y - 3 : y + h + 11}" font-size="10" text-anchor="middle" fill="var(--ink-2)">${fmtS(m.spent)}</text>` : "";
    return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${Math.max(1, bw - 1.6).toFixed(1)}" height="${h.toFixed(1)}" rx="1.5" fill="${col}" data-ply="${m.ply}" style="cursor:pointer"><title>${esc(m.label)} · ${m.spent.toFixed(0)} s${m.severity ? " · " + m.severity : ""}${m.clock != null ? " · " + fmtClock(m.clock) + " left" : ""}</title></rect>${over}`;
  }).join("");
  let grid = "";
  for (const v of scaleTicks) {
    const d = v / cap * hh;
    grid += `<line x1="${padl}" x2="${W - padr}" y1="${mid - 9 - d}" y2="${mid - 9 - d}" stroke="var(--grid)"/><line x1="${padl}" x2="${W - padr}" y1="${mid + 9 + d}" y2="${mid + 9 + d}" stroke="var(--grid)"/>
      <text x="${padl - 6}" y="${mid - 9 - d + 4}" font-size="10.5" text-anchor="end" fill="var(--muted)">${v}s</text><text x="${padl - 6}" y="${mid + 9 + d + 4}" font-size="10.5" text-anchor="end" fill="var(--muted)">${v}s</text>`;
  }
  const qd = c.quick / cap * hh;
  grid += `<line x1="${padl}" x2="${W - padr}" y1="${mid - 9 - qd}" y2="${mid - 9 - qd}" stroke="var(--accent)" stroke-dasharray="4 3"/><line x1="${padl}" x2="${W - padr}" y1="${mid + 9 + qd}" y2="${mid + 9 + qd}" stroke="var(--accent)" stroke-dasharray="4 3"/>
    <text x="${W - padr}" y="${mid - 13 - qd}" font-size="10" text-anchor="end" fill="var(--accent)">snap move</text>`;
  let xt = "";
  const tstep = n > 60 ? 20 : 10;
  for (const mv of [1, ...Array.from({ length: Math.floor(n / tstep) }, (_, i) => (i + 1) * tstep)]) if (mv <= n) xt += `<text x="${(padl + (mv - 1) * bw + bw / 2).toFixed(1)}" y="${mid + 4}" font-size="10" text-anchor="middle" fill="var(--ink-2)">${mv}</text>`;
  const svg = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" class="tpm" role="img" aria-label="Seconds spent on each move">
    ${grid}${bars(mine, true, false)}${bars(opp, false, true)}
    <text x="${padl - 6}" y="${mid + 4}" font-size="10" text-anchor="end" fill="var(--muted)">move</text>${xt}
    <text x="${padl}" y="12" font-size="12" font-weight="700" fill="var(--ink)">${esc(nameOf(rv, me))} (you) ↑</text>
    <text x="${padl}" y="${H - 4}" font-size="12" font-weight="700" fill="var(--ink-2)">${esc(nameOf(rv, them))} ↓</text></svg>`;
  const q = c.quick < 10 ? c.quick.toFixed(1).replace(/\.0$/, "") : Math.round(c.quick);
  return `<div class="card clock">
    <div class="row" style="align-items:baseline;gap:10px"><h2 style="margin:0">Clock</h2><span class="muted">${esc(c.tc)}</span></div>
    <div class="stack" style="gap:10px">${budgetRow("You", c.me, false)}${budgetRow(esc(nameOf(rv, them)), c.opp, true)}
      <div class="muted small bud-note">Each bar is the whole clock. Shaded parts are time spent in the opening, middlegame and endgame; the empty part is what was left at the end.</div></div>
    <h3 style="margin:6px 0 0">Time spent on each move</h3>
    <p class="small ink2" style="margin:0;max-width:72ch">One bar per move, numbered along the middle. Taller bar = longer think. Your moves rise above the line, your opponent’s hang below. Coloured bars are errors. The dashed line marks a snap move: under ${q} s, a third of the ${fmtS(c.budget)} this time control gives each move (${esc(c.moves_source)} lasts about ${Math.round(c.expected_moves)} moves).</p>
    ${svg}
    ${c.notes.length ? `<ul class="notes">${c.notes.map(t => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
  </div>`;
}

function renderTab() {
  const el = $("#rv-tab"), rv = S.review.review;
  if (R.tab === "move") return renderMoveTab();
  if (R.tab === "summary") {
    el.innerHTML = `<div class="stack">${faceOff(rv)}<div id="clock-slot"></div>
      <div class="muted small">${esc(rv.engine)} · depth ${rv.depth}${rv.maia_used ? (rv.maia_band ? ` · Maia ${rv.maia_band} (nearest your ${rv.player_rating ? `${rv.player_rating} ` : ""}rating in this game)` : " · Maia") : rv.maia_error ? ` · Maia off: ${esc(rv.maia_error)}` : ""}${rv.book_used ? " · opening book" : ""}</div></div>`;
    const slot = $("#clock-slot");
    slot.innerHTML = clockSection(rv, slot.clientWidth - 36);
    $$("[data-ply]", el).forEach(x => x.onclick = () => { R.tab = "move"; $$(".tabs a").forEach(a => a.classList.toggle("on", a.dataset.tab === "move")); setIdx(+x.dataset.ply); });
    return;
  }
  if (R.tab === "table") {
    R.side = R.side || "me";
    const rows = rv.plies.filter(p => p.severity && (R.side === "both" || (R.side === "me") === p.mine) && (!R.flaggedOnly || p.flagged));
    el.innerHTML = `<div class="row" style="margin-bottom:8px">${[["me", "My moves"], ["opp", "Opponent's"], ["both", "Both"]].map(([k, l]) => `<span class="chip ${R.side === k ? "on" : ""}" data-side="${k}">${l}</span>`).join("")}
      <label class="check" style="margin:0 0 0 10px"><input type="checkbox" id="fl-only" ${R.flaggedOnly ? "checked" : ""}> Flagged moves only</label></div>
      <div class="card tablewrap" style="padding:0"><table class="moves"><thead><tr><th>Move</th><th>Played</th><th>Best</th><th>Eval</th><th>Lost</th><th>Label</th><th class="c-minor">Position</th><th class="c-minor" title="Who was making threats: you (attacking), them (defending) or nobody">Initiative</th><th class="c-minor2">Type</th>${rv.has_clocks ? "<th>Time</th>" : ""}${rv.maia_used ? "<th>Maia</th>" : ""}</tr></thead><tbody>
      ${rows.map(p => `<tr data-ply="${p.ply}"><td class="muted">${esc(p.label)}</td><td><b>${esc(p.san)}</b></td><td>${p.best_uci === p.played_uci ? '<span class="muted">=</span>' : esc(p.best_san)}</td>
        <td class="num">${esc(p.eval_before)} → ${esc(p.eval_after)}</td><td class="num">${p.pp ? "−" + p.pp : ""}</td>
        <td>${badge(p.severity, 13)} ${p.severity}${p.missed ? ` ${missedBadge(12)} missed` : ""}</td>
        <td class="c-minor">${p.standing}</td><td class="c-minor">${INITIATIVE[p.phase] || p.phase}</td><td class="c-minor2">${p.type}</td>${rv.has_clocks ? `<td class="num">${p.spent != null ? p.spent.toFixed(0) + " s" : ""}</td>` : ""}
        ${rv.maia_used ? `<td>${p.maia ? `${p.maia.p_best}% <span class="muted">${p.maia.tags.join(", ")}</span>` : ""}</td>` : ""}</tr>`).join("")}
      </tbody></table></div>`;
    $("#fl-only").onchange = e => { R.flaggedOnly = e.target.checked; renderTab(); };
    $$("[data-side]", el).forEach(c => c.onclick = () => { R.side = c.dataset.side; renderTab(); });
    $$("tr[data-ply]", el).forEach(x => x.onclick = () => { R.tab = "move"; $$(".tabs a").forEach(a => a.classList.toggle("on", a.dataset.tab === "move")); setIdx(+x.dataset.ply); });
    return;
  }
  if (R.tab === "notes") {
    const n = (R.notes && R.notesId === S.review.id) ? R.notes.notes : {};
    const moves = rv.plies.filter(p => n[p.ply]);
    el.innerHTML = `<div class="stack">
      <div class="card"><h3 style="margin:0 0 6px">This game</h3>${n[0] ? `<div class="note-text">${esc(n[0])}</div>` : `<span class="muted small">No game note. <a id="nt-add">+ Note on this game</a> (above the board).</span>`}</div>
      <div class="card"><h3 style="margin:0 0 6px">Moves <span class="muted small" style="font-weight:400">${moves.length ? "click one to go there" : ""}</span></h3>
      ${moves.length ? `<div class="notes-list">${moves.map(p => `<div class="notes-row click" data-ply="${p.ply}"><span class="muted">${esc(p.label)}</span> <b>${esc(p.san)}</b> ${p.severity ? badge(p.severity, 12) : ""}<div class="note-text">${esc(n[p.ply])}</div></div>`).join("")}</div>`
        : `<span class="muted small">No move notes yet. On the Moves tab, the box under a move's card keeps a note for that move.</span>`}</div></div>`;
    if ($("#nt-add")) $("#nt-add").onclick = () => { $("#gnote-box").hidden = false; $("#gnote").focus(); };
    $$("[data-ply]", el).forEach(x => x.onclick = () => { R.tab = "move"; $$(".tabs a").forEach(a => a.classList.toggle("on", a.dataset.tab === "move")); setIdx(+x.dataset.ply); });
    return;
  }
  if (R.tab === "export") {
    const pgn = R.exportFmt === "pgn";
    el.innerHTML = `<div class="card stack">
      <div class="row" role="radiogroup" aria-label="Format">${[["md", "Obsidian note"], ["pgn", "Annotated PGN"]].map(([k, l]) => `<span class="chip ${(R.exportFmt || "md") === k ? "on" : ""}" role="radio" tabindex="0" aria-checked="${(R.exportFmt || "md") === k}" data-fmt="${k}">${l}</span>`).join("")}</div>
      <div class="muted small">${pgn
        ? "Standard PGN for a Lichess study, ChessBase or any PGN reader: labels as PGN codes ($6 $2 $4 $3 $1) that those show as ?! ? ?? !! !, the verdict line as a comment, the eval after every move (Lichess draws the graph from it), clocks, your notes and tags."
        : "A Markdown note for Obsidian: a header, the flagged moves in plain sentences, and the game in a <code>\`\`\`chess</code> block (Chess Tree format). No tags or links - those stay yours."}</div>
      <div class="row"><label class="check" style="margin:0"><input type="checkbox" id="ex-lines" ${S.settings.export_lines ? "checked" : ""}> Engine lines as variations</label>
        <label class="check" style="margin:0"><input type="checkbox" id="ex-com" ${S.settings.export_comments ? "checked" : ""}> ${pgn ? "Verdict comments" : "Short comments"}</label></div>
      <textarea id="ex-md" rows="16" readonly></textarea>
      <div class="row"><button class="primary" id="ex-copy">Copy</button><button id="ex-save">Save to Downloads</button></div></div>`;
    const load = async () => {
      const l = $("#ex-lines").checked ? 1 : 0, c = $("#ex-com").checked ? 1 : 0;
      const id = encodeURIComponent(S.review.id);
      if (pgn) $("#ex-md").value = (await api("GET", `/api/games/${id}/pgn?lines=${l}&comments=${c}`)).pgn;
      else $("#ex-md").value = (await api("GET", `/api/games/${id}/export?lines=${l}&comments=${c}`)).markdown;
    };
    const save = async () => { S.settings = await api("POST", "/api/settings", { export_lines: $("#ex-lines").checked, export_comments: $("#ex-com").checked }); load(); };
    $("#ex-lines").onchange = save; $("#ex-com").onchange = save;
    $$("[data-fmt]", el).forEach(b => b.onclick = () => { R.exportFmt = b.dataset.fmt; renderTab(); });
    $("#ex-copy").onclick = () => copyText($("#ex-md").value);
    $("#ex-save").onclick = async () => {
      const g = S.review, name = `${(g.played_at || "").slice(0, 10)} ${g.white} vs ${g.black}.${pgn ? "pgn" : "md"}`.trim();
      const r = await api("POST", "/api/save-download", { name, text: $("#ex-md").value });
      toast(`Saved to ${r.path.replace(/^.*[\/\\]Downloads[\/\\]/, "Downloads/")}`);
    };
    load();
  }
}
