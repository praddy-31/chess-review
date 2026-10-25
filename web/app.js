// Chess Review - the UI. Talks to the local engine process (engine/server.py)
// over 127.0.0.1 with the per-launch token the native shell put in the URL.
"use strict";

// ------------------------------------------------------------------ basics
const TOKEN = (location.hash.match(/^#([A-Za-z0-9_\-]{8,})/) || [])[1] || sessionStorage.getItem("token") || "";
if (TOKEN) { try { sessionStorage.setItem("token", TOKEN); } catch (e) {} }
if (/^#[A-Za-z0-9_\-]{8,}$/.test(location.hash)) history.replaceState(null, "", "#/library");

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const SEV = ["Brilliant", "Great", "Best", "Book", "Good", "Inaccuracy", "Mistake", "Blunder"];
const SEV_VAR = { Brilliant: "--sev-brilliant", Great: "--sev-great", Best: "--sev-best", Book: "--sev-book", Good: "--sev-good",
  Inaccuracy: "--sev-inacc", Mistake: "--sev-mistake", Blunder: "--sev-blunder" };
const GLYPH = { Brilliant: "!!", Great: "!", Inaccuracy: "?!", Mistake: "?", Blunder: "??" };
const ERRS = ["Inaccuracy", "Mistake", "Blunder"];
// V11: a move's "phase" from the threat probes is shown as initiative (game phases are opening/middlegame/endgame)
const INITIATIVE = { Attack: "Attacking", Defense: "Defending", Neutral: "Neutral" };
const SEV_HELP = {
  Brilliant: "a sound sacrifice: the engine's move, and it leaves a piece (2+ points) that can be taken, counting the whole exchange. Not when you were already winning, and not a recapture",
  Great: "critical: the only good move (the next best costs 20+ points of win chance), or the move that turns the game after the opponent's mistake (losing to equal, or equal to winning)",
  Best: "the engine's move", Book: "known opening theory", Good: "close to the engine's move (under 5 points lost)",
  Inaccuracy: "5-10 points of win chance lost", Mistake: "10-20 points lost", Blunder: "20+ points lost",
};
// moves worth a dot in the move list and a marker on the graph
const marked = q => q.severity && (q.flagged || q.severity === "Brilliant" || q.severity === "Great");
const markColor = q => q.missed && !ERRS.includes(q.severity) ? cssv("--sev-missed") : sevColor(q.severity);
const estMin = plies => Math.max(1, Math.round(plies * 0.45 * Math.pow(1.35, (S.settings?.depth || 16) - 16) / 60));
const cssv = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const sevColor = s => cssv(SEV_VAR[s] || "--muted");

async function api(method, path, body) {
  const r = await fetch(path, {
    method, headers: { "X-Token": TOKEN, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = {};
  try { data = await r.json(); } catch (e) {}
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

let toastTimer;
function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg; t.className = err ? "err" : ""; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.hidden = true), err ? 6000 : 2600);
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); }
  catch (e) {
    const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand("copy"); ta.remove();
  }
  toast("Copied");
}

const S = { settings: null, status: null, games: [], jobs: {}, view: null, review: null };

function applyCollapsed() {
  const on = !!S.settings?.sidebar_collapsed;
  $("#app").classList.toggle("collapsed", on);
  const b = $("#nav-toggle");
  if (b) {
    b.setAttribute("aria-label", on ? "Expand sidebar" : "Collapse sidebar");
    b.title = (on ? "Expand" : "Collapse") + " sidebar (⌘\\)";
    b.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="${on ? "M9 6l6 6-6 6" : "M15 6l-6 6 6 6"}"/></svg>`;
  }
  $$("#nav a.item").forEach(x => x.title = on ? x.textContent.trim() : "");
}
async function toggleSidebar() {
  S.settings.sidebar_collapsed = !S.settings.sidebar_collapsed;
  applyCollapsed();
  if (S.view === "review" && S.review?.review) setTimeout(() => { drawGraph(); if (R.tab === "summary") renderTab(); }, 180);
  try { await api("POST", "/api/settings", { sidebar_collapsed: S.settings.sidebar_collapsed }); } catch (e) {}
}
document.addEventListener("keydown", e => { if ((e.metaKey || e.ctrlKey) && e.key === "\\") { e.preventDefault(); toggleSidebar(); } });

function applyLook() {
  const root = document.documentElement, v = S.settings?.follow_palette && PAL.s?.valid ? PAL.s.vars : null;
  root.dataset.board = S.settings?.board || "green";
  // V11: following Palette, its colours go over the closest built-in theme (light or dark rules)
  root.dataset.theme = v ? (PAL.s.mode === "light" ? "latte" : "mocha") : (S.settings?.theme || "mocha");
  PAL_VARS.forEach(k => v ? root.style.setProperty(k, v[k]) : root.style.removeProperty(k));
}

// ------------------------------------------------------------------ V11: follow Palette (engine/palette.py)
// While "Follow Palette" is on, ask every 2 s whether its colours file changed (a local file, no network).
const PAL = { s: null, timer: null };
const PAL_VARS = ["--page", "--surface", "--surface-2", "--ink", "--ink-2", "--muted", "--grid", "--axis", "--border",
  "--good", "--critical", "--warning", "--accent", "--accent-soft", "--on-accent"];
async function paletteSync() {
  clearTimeout(PAL.timer); PAL.timer = null;
  if (!S.settings?.follow_palette) { PAL.s = null; applyLook(); return; }
  try {
    const s = await api("GET", "/api/palette"), was = PAL.s;
    PAL.s = s;
    if (!was || was.modified !== s.modified || was.valid !== s.valid) {
      applyLook();
      if (was && s.valid && was.theme !== s.theme) toast("Palette: " + s.theme);
      if (S.view === "settings" && typeof paletteSettings === "function") paletteSettings();
    }
  } catch (e) {}
  if (S.settings?.follow_palette) PAL.timer = setTimeout(paletteSync, 2000);
}

const fmtTC = tc => {
  const m = /^(\d+)(?:\+(\d+))?$/.exec(tc || "");
  if (!m) return tc || "—";
  const base = +m[1], inc = +(m[2] || 0);
  const b = base >= 60 ? (base % 60 ? (base / 60).toFixed(1) : base / 60) : base + "s";
  return `${b}+${inc}`;
};
// how many games you have against each opponent (lower-case name)
function oppCounts() {
  const c = {};   // games against Maia don't count: they're left out of opponent pages, so no link to an empty page
  for (const g of S.games || []) if (g.opponent && g.source !== "maia") c[g.opponent.toLowerCase()] = (c[g.opponent.toLowerCase()] || 0) + 1;
  return c;
}
const fmtClock = s => s == null ? "" : `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const cap = s => s ? s[0].toUpperCase() + s.slice(1) : s;

// ------------------------------------------------------------------ router
const VIEWS = {};
async function route() {
  const h = location.hash || "#/library";
  const [, name, arg] = h.match(/^#\/(\w+)(?:\/(.+))?/) || [, "library"];
  S.view = name;
  if (typeof liveStop === "function") liveStop();
  if (name !== "play" && typeof plLeave === "function") plLeave();   // a timed game against Maia pauses while you're away
  if (name !== "review") R.whatif = null;
  $$("#nav a.item").forEach(a => a.classList.toggle("on", a.dataset.nav === name));
  const v = VIEWS[name] || VIEWS.library;
  document.onkeydown = null;
  try { await v(arg ? decodeURIComponent(arg) : null); showTip(name === "puzzles" && arg === "convert" ? "convert" : name === "review" && !arg ? "" : name); }
  catch (e) { $("#main").innerHTML = `<div class="page"><div class="card status-no">${esc(e.message)}</div></div>`; }
}

// ------------------------------------------------------------------ V11: a short note the first time you open each screen
const TIPS = {
  library: ["Your games", "<b>Sync</b> fetches new games from your accounts, only when you press it; <b>+ Add games</b> takes a PGN or game links. Nothing is analysed until you tick games and press <b>Analyse</b>. Click a game to open its review."],
  review: ["How to read a review", () => {
    const t = S.settings.thresholds, chip = s => `<button type="button" class="tip-sev" style="color:var(${SEV_VAR[s]})" data-rule="${esc(s)}" title="${esc(SEV_HELP[s])}">${GLYPH[s] ? `<b>${GLYPH[s]}</b> ` : ""}${s}</button>`;
    return `Every move is graded by how much <b>win chance</b> it gave away against the engine's best move, in <b>points</b>: from 60% to 45% costs 15 points.
      <div class="tip-sevs">${chip("Inaccuracy")} ${t.inaccuracy_pp}-${t.mistake_pp} points ${chip("Mistake")} ${t.mistake_pp}-${t.blunder_pp} ${chip("Blunder")} ${t.blunder_pp}+
      · ${chip("Great")} the only good move ${chip("Brilliant")} a sound sacrifice</div>
      <div class="tip-rule muted" hidden></div>
      Click a move, a sentence or the graph and the board goes there. <b>Retry this move</b> lets you try a flagged move again. Click a label above for its full rule.`;
  }],
  board: ["Analysis board", "Load any position or game and the engine shows its best lines as you move. A move opened from a review comes here, with a way back."],
  puzzles: ["Puzzles from your games", "Each puzzle is a moment from your analysed games where a better move was there: your mistakes and your opponents'. Solve a few a day; the ones you miss come back sooner."],
  convert: ["Convert the win", "Positions from games you drew or lost while clearly winning. Play them out against an opponent at their rating until the win is safe."],
  openings: ["Your openings", "What you play, move by move, with how each line scores for you. Star moves to build a repertoire, or pick an opening to <b>learn</b>: its lines come back a few at a time until you know them."],
  insights: ["Where your points go", "Built from your analysed games: where your points go, your skills, tilt, clock and endgames, and how they change over the months. The more games you analyse, the steadier the numbers."],
  play: ["Play against Maia", "Maia plays like people at the rating you pick, not like an engine. Finished games go to your Library, ready to analyse."],
};
function showTip(id) {
  const tip = TIPS[id], head = $("#main .page-head");
  if (!tip || !head || (S.settings.tips_seen || []).includes(id)) return;
  const body = typeof tip[1] === "function" ? tip[1]() : tip[1];
  head.insertAdjacentHTML("afterend", `<div class="card tip" data-tip="${id}"><button class="sm ghost x" data-tip-off title="Got it, don't show again" aria-label="Dismiss">×</button><h3>${tip[0]}</h3><div class="small">${body}</div></div>`);
  $$("#main .tip [data-rule]").forEach(b => b.onclick = () => {
    const r = $("#main .tip-rule"), s = b.dataset.rule;
    r.hidden = r.dataset.on === s && !r.hidden; r.dataset.on = s;
    r.innerHTML = `<b>${esc(s)}</b>: ${esc(SEV_HELP[s])}.`;
  });
  $("#main [data-tip-off]").onclick = async e => {
    e.currentTarget.closest(".tip").remove();
    S.settings = await api("POST", "/api/settings", { tips_seen: [...(S.settings.tips_seen || []), id] });
  };
}
window.addEventListener("hashchange", route);

// ------------------------------------------------------------------ job queue polling
let pollTimer = null;
async function pollJobs() {
  clearTimeout(pollTimer);
  try {
    const { jobs } = await api("GET", "/api/jobs");
    const before = S.jobs;
    S.jobs = Object.fromEntries(jobs.map(j => [j.id, j]));
    const active = jobs.filter(j => j.state === "queued" || j.state === "running");
    renderQueue(active);
    const justFinished = jobs.filter(j => j.state === "done" && before[j.id] && before[j.id].state !== "done");
    const justFailed = jobs.filter(j => j.state === "error" && before[j.id] && before[j.id].state !== "error");
    justFailed.forEach(j => toast(j.error, true));
    if (S.view === "library") updateLibraryJobs(justFinished.length > 0 || justFailed.length > 0);
    if (S.view === "review" && S.review) {
      const j = S.jobs[S.review.id];
      if (justFinished.some(x => x.id === S.review.id)) VIEWS.review(S.review.id, { keepPly: false });
      else if (j) updateReviewJob(j);
    }
    if (active.length) pollTimer = setTimeout(pollJobs, 800);
  } catch (e) { pollTimer = setTimeout(pollJobs, 3000); }
}
function renderQueue(active) {
  const q = $("#queue");
  if (!active.length) { q.hidden = true; return; }
  const run = active.find(j => j.state === "running");
  const pct = run && run.total ? Math.round(100 * run.done / run.total) : 0;
  const g = run && S.games.find(x => x.id === run.id);
  q.hidden = false;
  q.innerHTML = `Analysing ${run ? (g ? "vs " + esc(g.opponent || g.black) : "game") + ` · ${pct}%` : "…"}${active.length > 1 ? ` <span class="muted">+${active.length - 1} queued</span>` : ""}
    <div class="bar"><i style="width:${pct}%"></i></div>`;
}

async function analyse(id, color) {
  try {
    await api("POST", `/api/games/${encodeURIComponent(id)}/analyse`, color ? { color } : {});
    pollJobs();
  } catch (e) { toast(e.message, true); }
}

// ------------------------------------------------------------------ import modal
function openImport() {
  const bg = document.createElement("div");
  bg.className = "modal-bg";
  bg.innerHTML = `<div class="modal">
    <h2>Add games</h2>
    <div class="muted small">Paste a PGN (one or many games), a move list, or chess.com / Lichess game links - one per line.
      ${S.settings.chesscom_user ? "" : "chess.com links need your chess.com username in Settings."}</div>
    <textarea id="imp-text" placeholder="https://www.chess.com/game/live/…&#10;https://lichess.org/…&#10;&#10;or [Event &quot;…&quot;] 1. e4 e5 …"></textarea>
    <div class="row"><span class="muted small" id="imp-msg"></span><span style="flex:1"></span>
      <button class="ghost" id="imp-cancel">Cancel</button><button class="primary" id="imp-go">Add to Library</button></div>
  </div>`;
  document.body.appendChild(bg);
  const close = () => bg.remove();
  $("#imp-cancel", bg).onclick = close;
  bg.addEventListener("mousedown", e => { if (e.target === bg) close(); });
  bg.addEventListener("keydown", e => { if (e.key === "Escape") close(); });
  $("#imp-text", bg).focus();
  $("#imp-go", bg).onclick = async () => {
    const btn = $("#imp-go", bg); btn.disabled = true; $("#imp-msg", bg).textContent = "Adding…";
    try {
      const r = await api("POST", "/api/import", { text: $("#imp-text", bg).value });
      const parts = [];
      if (r.added.length) parts.push(`${r.added.length} added`);
      if (r.existing.length) parts.push(`${r.existing.length} already in the Library`);
      if (r.errors.length) parts.push(`${r.errors.length} problem${r.errors.length > 1 ? "s" : ""}: ${r.errors.join("; ")}`);
      if (r.errors.length && !r.added.length && !r.existing.length) { $("#imp-msg", bg).textContent = parts.join(" · "); btn.disabled = false; return; }
      close(); toast(parts.join(" · "), r.errors.length > 0);
      await loadGames();
      if (r.added.length === 1 && !r.existing.length) location.hash = `#/review/${encodeURIComponent(r.added[0])}`;
      else route();
    } catch (e) { $("#imp-msg", bg).textContent = e.message; btn.disabled = false; }
  };
}

async function loadGames() { S.games = (await api("GET", "/api/games")).games; return S.games; }
