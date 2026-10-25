// V10: play a game against Maia. The engine keeps the game (/api/play/...);
// this file draws it, runs your clock between moves and shows the result.
const PL = { o: null, g: null, board: null, busy: false, fen: null, last: null, sans: [], over: null, clocks: null, turnAt: 0, tick: null, color: "random", clock: null, band: null, paused: false, pending: 0 };
// V11: the usual bullet / blitz / rapid / classical controls, plus your own (minutes + seconds a move)
const PL_CLOCKS = [["none", "No clock"], ["1+0", "1+0"], ["2+1", "2+1"], ["3+0", "3+0"], ["3+2", "3+2"], ["5+0", "5+0"], ["5+3", "5+3"],
  ["10+0", "10+0"], ["10+5", "10+5"], ["15+10", "15+10"], ["30+0", "30+0"], ["30+20", "30+20"]];

VIEWS.play = async function () {
  const m = $("#main");
  m.innerHTML = `<div class="page page-wide">
    <div class="page-head"><h1>Play</h1><span class="muted" id="pl-sub">a game against Maia, which plays like people at the rating you pick</span></div>
    <div class="rv"><div class="rv-left"><div class="pl-clock" id="pl-top"></div><div class="boardwrap"><svg class="board" id="board" role="img" aria-label="Game board"></svg></div><div class="pl-clock" id="pl-bot"></div><div class="op-path" id="pl-path"></div></div>
      <div class="rv-right" id="pl-side"><div class="card muted">Loading…</div></div></div></div>`;
  PL.board = new ChessBoard($("#board")); PL.board.pieces = S.settings.pieces || "cburnett";
  if (PL.g && !PL.over) { plDraw(); plSide(); if (!PL.paused) plTick(); return; }      // a game in progress: carry on (paused if you left)
  try { PL.o = await api("GET", "/api/play"); } catch (e) { $("#pl-side").innerHTML = `<div class="card status-no">${esc(e.message)}</div>`; return; }
  if (PL.over) { plDraw(); plSide(); return; }
  plSetup();
};

function plSetup() {
  const o = PL.o, side = $("#pl-side");
  PL.g = null; PL.over = null; PL.sans = []; PL.last = null; plStopTick();
  PL.board.setMoves(null); PL.board.draw({ fen: "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", flipped: PL.color === "Black" });
  $("#pl-top").innerHTML = $("#pl-bot").innerHTML = $("#pl-path").innerHTML = "";
  if (!o.available) {
    side.innerHTML = `<div class="card stack"><h2>Maia isn't installed</h2>
      <p class="muted">Play needs lc0 and at least one Maia net. ${o.lc0 ? "lc0 is here; the Maia weights aren't." : "Neither lc0 nor the Maia weights were found."} Setup shows the commands (about 2 minutes).</p>
      <a class="btn primary" href="#/setup">Open Setup</a></div>`;
    return;
  }
  PL.band = PL.band || o.band; PL.clock = PL.clock || o.clock;
  side.innerHTML = `<div class="card stack pl-card">
    <div class="field wide"><label for="pl-band">Maia's rating</label>
      <select id="pl-band">${o.bands.map(b => `<option value="${b}" ${b === PL.band ? "selected" : ""}>Maia ${b}${b === o.band && Math.abs(b - o.rating) <= 100 ? " · about your rating" : b > o.rating ? " · stronger" : " · weaker"}</option>`).join("")}</select></div>
    <div class="field wide"><label>You play</label><div class="row" role="radiogroup" aria-label="Your colour">${[["White", "White"], ["random", "Random"], ["Black", "Black"]].map(([k, l]) => `<span class="chip ${PL.color === k ? "on" : ""}" role="radio" tabindex="0" aria-checked="${PL.color === k}" data-plc="${k}">${k !== "random" ? `<span class="side ${k}"></span>` : ""}${l}</span>`).join("")}</div></div>
    <div class="field wide"><label>Clock</label><div class="row" role="radiogroup" aria-label="Clock" style="flex-wrap:wrap">${PL_CLOCKS.map(([k, l]) => `<span class="chip ${PL.clock === k ? "on" : ""}" role="radio" tabindex="0" aria-checked="${PL.clock === k}" data-plk="${k}">${l}</span>`).join("")}${(() => { const own = PL.clock && !PL_CLOCKS.some(([k]) => k === PL.clock); return `<span class="chip ${own ? "on" : ""}" role="radio" tabindex="0" aria-checked="${own}" data-plk="custom">${own ? esc(PL.clock) : "Custom"}</span>`; })()}</div>
      <div class="row" id="pl-custom" style="gap:6px;margin-top:6px" hidden><input type="number" id="pl-cm" min="1" max="180" value="${PL.clock && PL.clock !== "none" ? +PL.clock.split("+")[0] || 7 : 7}" style="width:70px" aria-label="Minutes each"> <span class="muted small">min +</span>
        <input type="number" id="pl-cs" min="0" max="180" value="${PL.clock && PL.clock !== "none" ? +PL.clock.split("+")[1] || 0 : 0}" style="width:70px" aria-label="Seconds added per move"> <span class="muted small">s a move</span><button class="sm" id="pl-cset">Use</button></div>
      <span class="muted small">Minutes + seconds added per move. No takebacks.</span></div>
    <button class="primary" id="pl-go">Start the game</button>
    <p class="muted small">Maia picks among the moves people at that rating play, so no two games are the same. Finished games go to your Library as "vs Maia", not analysed until you ask, and don't count in Insights unless you switch that on in Settings.</p>
  </div>${plRecentHtml(o.recent)}`;
  if (o.saved) {   // V11: a game you paused, or one still going when the app closed
    side.insertAdjacentHTML("afterbegin", `<div class="card stack pl-card" id="pl-saved"><div class="pz-top"><span class="pz-title">Your paused game</span><span class="muted small">${o.saved.moves} moves</span></div>
      <div><span class="side ${o.saved.color}"></span> You vs Maia ${o.saved.band}, started ${esc(o.saved.started.slice(0, 10))}</div>
      <div class="row" style="gap:8px"><button class="primary" id="pl-resume">Resume</button></div>
      <span class="muted small">Starting a new game drops it.</span></div>`);
    $("#pl-resume").onclick = () => plResume(o.saved.id);
  }
  $("#pl-band").onchange = e => { PL.band = +e.target.value; };
  $$("[data-plc]", side).forEach(c => c.onclick = () => { PL.color = c.dataset.plc; plSetup(); });
  $$("[data-plk]", side).forEach(c => c.onclick = () => { if (c.dataset.plk === "custom") { $("#pl-custom").hidden = false; $("#pl-cm").focus(); return; } PL.clock = c.dataset.plk; plSetup(); });
  $("#pl-cset").onclick = () => {
    const m = Math.round(+$("#pl-cm").value), sec = Math.round(+$("#pl-cs").value);
    if (!(m >= 1 && m <= 180 && sec >= 0 && sec <= 180)) { toast("1 to 180 minutes, 0 to 180 seconds a move", true); return; }
    PL.clock = `${m}+${sec}`; plSetup();
  };
  $("#pl-go").onclick = plStart;
  plBindRecent(side);
}

function plRecentHtml(rows) {
  if (!rows || !rows.length) return "";
  const word = { win: "Won", loss: "Lost", draw: "Drew" };
  return `<div class="card"><div class="ll-head"><span class="ll-title">Recent games against Maia</span></div>
    <table class="moves"><tbody>${rows.map(r => `<tr class="click" data-plg="${esc(r.id)}"><td><span class="side ${r.color}"></span> vs ${esc(r.maia)}</td>
      <td><span class="res ${r.outcome}">${word[r.outcome]}</span></td><td class="muted small">${esc(r.date)}</td><td class="muted small">${r.analysed ? "analysed" : "not analysed"}</td></tr>`).join("")}</tbody></table></div>`;
}
function plBindRecent(root) { $$("[data-plg]", root).forEach(tr => tr.onclick = () => (location.hash = `#/review/${encodeURIComponent(tr.dataset.plg)}`)); }

async function plStart() {
  const b = $("#pl-go"); b.disabled = true; b.textContent = "Starting Maia…";
  try { PL.g = await api("POST", "/api/play/start", { band: PL.band, color: PL.color, clock: PL.clock }); }
  catch (e) { toast(e.message, true); b.disabled = false; b.textContent = "Start the game"; return; }
  PL.over = null; PL.sans = PL.g.maia ? [PL.g.maia.san] : []; PL.fen = PL.g.fen; PL.last = PL.g.maia ? PL.g.maia.uci : null;
  PL.clocks = PL.g.clocks; PL.turnAt = Date.now(); PL.paused = false; PL.pending = 0;
  plDraw(true); plSide(); plTick();
}

// V11: pause and resume. Your clock is measured here: time while paused isn't counted,
// and `pending` keeps what you'd used on this move before the pause.
function plMyTurn() { return PL.g && PL.fen && (PL.fen.split(" ")[1] === "w" ? "White" : "Black") === PL.g.color; }
function plSpent() { return PL.pending + (PL.paused || PL.busy || !plMyTurn() ? 0 : (Date.now() - PL.turnAt) / 1000); }
async function plPause() {
  if (!PL.g || PL.over || PL.paused || PL.busy || !PL.clocks) return;
  PL.pending = plMyTurn() ? plSpent() : 0; PL.paused = true; plStopTick();
  try { await api("POST", `/api/play/${PL.g.id}/pause`, { spent: PL.pending }); } catch (e) { toast(e.message, true); }
  if (S.view === "play") { plDraw(); plSide(); }
}
async function plResume(id) {
  let r;
  try { r = await api("POST", `/api/play/${id || PL.g.id}/resume`); } catch (e) { toast(e.message, true); return; }
  PL.g = { id: r.id, color: r.color, band: r.band, clock: r.clock }; PL.over = null; PL.busy = false;
  PL.fen = r.fen; PL.sans = r.sans; PL.last = r.last; PL.clocks = r.clocks;
  PL.pending = r.pending || 0; PL.paused = false; PL.turnAt = Date.now();
  plDraw(); plSide(); plTick();
}
// leaving Play (or closing the window) pauses a timed game, so the clock doesn't run while you're away
function plLeave() { if (PL.g && !PL.over && PL.clocks && !PL.paused) plPause(); }
window.addEventListener("pagehide", () => {
  if (!PL.g || PL.over || !PL.clocks || PL.paused) return;
  try { fetch(`/api/play/${PL.g.id}/pause`, { method: "POST", keepalive: true, headers: { "X-Token": TOKEN, "Content-Type": "application/json" }, body: JSON.stringify({ spent: plMyTurn() ? plSpent() : 0 }) }); } catch (e) {}
});

function plDraw(anim) {
  const g = PL.g; if (!g) return;
  PL.board.draw({ fen: PL.fen, lastUci: PL.paused && !PL.over ? null : PL.last, flipped: g.color === "Black", animate: anim });
  PL.board.setMoves(null);
  const wrap = $("#board")?.closest(".boardwrap"); if (wrap) wrap.classList.toggle("pl-paused", PL.paused && !PL.over);
  $("#pl-path").innerHTML = PL.sans.map((s, i) => `${i % 2 === 0 ? `<span class="muted small">${i / 2 + 1}.</span>` : ""}<span class="mchip">${esc(s)}</span>`).join("");
  plClocks();
  if (PL.over || PL.busy || PL.paused) return;
  const f = PL.fen;
  getPos(f).then(p => { if (PL.fen === f && !PL.busy && !PL.over) PL.board.setMoves(p.moves, plMove); }).catch(() => {});
}

const plFmt = s => { s = Math.max(0, s); const m = Math.floor(s / 60), r = s - 60 * m; return s < 10 ? `${m}:${r.toFixed(1).padStart(4, "0")}` : `${m}:${String(Math.floor(r)).padStart(2, "0")}`; };
function plLeft(color) {
  if (!PL.clocks) return null;
  const mine = PL.g.color, turn = PL.fen.split(" ")[1] === "w" ? "White" : "Black";
  let v = PL.clocks[color];
  if (!PL.over && color === mine && turn === mine) v -= plSpent();
  return v;
}
function plClocks() {
  const g = PL.g; if (!g) return;
  const me = g.color, maia = me === "White" ? "Black" : "White";
  const turn = PL.fen.split(" ")[1] === "w" ? "White" : "Black";
  const row = (who, name, color) => {
    const left = plLeft(color);
    return `<span class="side ${color}"></span><b>${esc(name)}</b>${who === "maia" && PL.busy && !PL.over ? ` <span class="muted small">thinking…</span>` : ""}
      ${left != null ? `<span class="pl-time ${turn === color && !PL.over ? "on" : ""} ${left < 20 ? "low" : ""}" aria-label="${esc(name)}'s clock">${plFmt(left)}</span>` : ""}`;
  };
  $("#pl-top").innerHTML = row("maia", `Maia ${g.band}`, maia);
  $("#pl-bot").innerHTML = row("you", "You", me);
}
function plTick() {
  plStopTick();
  if (!PL.clocks || PL.over) return;
  PL.tick = setInterval(() => {
    if (!$("#pl-bot")) return plStopTick();
    plClocks();
    const left = plLeft(PL.g.color);
    if (left != null && left <= 0 && !PL.busy && !PL.over) plFlag();
  }, 100);
}
function plStopTick() { if (PL.tick) clearInterval(PL.tick); PL.tick = null; }

async function plMove(uci, m) {
  if (PL.busy || PL.over) return;
  if (PL.paused) return;
  const spent = plSpent();
  PL.busy = true; PL.fen = m.fen; PL.last = uci; plDraw(true); plSide();
  let r;
  try { r = await api("POST", `/api/play/${PL.g.id}/move`, { uci, spent }); }
  catch (e) { toast(e.message, true); PL.busy = false; PL.over = { result: "*", outcome: "lost", termination: "an error" }; plSide(); return; }
  if (r.you) PL.sans.push(r.you.san);
  if (r.maia) {
    await new Promise(res => setTimeout(res, 350));
    PL.sans.push(r.maia.san); PL.last = r.maia.uci;
  }
  PL.fen = r.fen; PL.clocks = r.clocks; PL.busy = false; PL.turnAt = Date.now(); PL.pending = 0;
  if (r.over) plEnd(r.over);
  plDraw(true); plSide();
}
async function plFlag() {
  PL.busy = true;
  try { const r = await api("POST", `/api/play/${PL.g.id}/flag`); PL.clocks = r.clocks; plEnd(r.over); }
  catch (e) { toast(e.message, true); }
  PL.busy = false; plDraw(); plSide();
}
function plEnd(over) { PL.over = over; plStopTick(); if (PL.o) PL.o.recent = null; }

function plSide() {
  const side = $("#pl-side"), g = PL.g, r = PL.over;
  if (!side || !g) return;
  if (!r) {
    side.innerHTML = `<div class="card stack pl-card"><div class="pz-top"><span class="pz-title">vs Maia ${g.band}</span><span class="muted small">${g.clock === "none" ? "no clock" : g.clock}</span></div>
      <div class="pz-msg">${PL.paused ? "Paused: both clocks are stopped." : PL.busy ? "Maia is thinking…" : "Your move."}</div>
      <div class="row" style="gap:8px">${PL.paused ? `<button class="primary" id="pl-unpause">Resume</button>` : PL.clocks ? `<button class="sm" id="pl-pause">Pause</button>` : ""}<button class="sm ghost danger" id="pl-resign">Resign</button></div>
      <p class="muted small">No takebacks. The game is kept until you finish it, even if you quit the app${PL.clocks ? "; leaving Play pauses the clocks" : ""}.</p></div>`;
    if ($("#pl-pause")) $("#pl-pause").onclick = plPause;
    if ($("#pl-unpause")) $("#pl-unpause").onclick = () => plResume();
    $("#pl-resign").onclick = async e => {
      const b = e.target;
      if (!b.dataset.armed) { b.dataset.armed = "1"; b.textContent = "Resign? Click again"; setTimeout(() => { if (b.isConnected) { delete b.dataset.armed; b.textContent = "Resign"; } }, 4000); return; }
      try { const x = await api("POST", `/api/play/${g.id}/resign`); plEnd(x.over); } catch (err) { toast(err.message, true); }
      plDraw(); plSide();
    };
    return;
  }
  const head = { win: "You won", loss: "You lost", draw: "Draw" }[r.outcome] || "Game over";
  side.innerHTML = `<div class="card stack pl-card"><div class="pz-top"><span class="pz-title">vs Maia ${g.band}</span><span class="muted small">${r.moves ? `${Math.ceil(r.moves / 2)} moves` : ""}</span></div>
    <div class="pz-head"><span class="pz-res ${r.outcome === "win" ? "ok" : r.outcome === "loss" ? "no" : ""}">${head}</span><span class="muted">by ${esc(r.termination)} · ${esc(r.result)}</span></div>
    ${r.game_id ? `<p class="muted small">Saved to your Library. It isn't analysed yet: analyse it to see where the game turned.</p>
    <div class="row" style="gap:8px"><button class="primary" id="pl-an">Analyse this game</button><a class="btn" href="#/review/${encodeURIComponent(r.game_id)}">Open it</a></div>` : ""}
    <div class="row" style="gap:8px"><button id="pl-again">Play again</button><button class="ghost" id="pl-new">Change settings</button></div></div>`;
  if ($("#pl-an")) $("#pl-an").onclick = async () => { await analyse(r.game_id); toast("Analysis queued: Open it to watch it fill in"); };
  $("#pl-again").onclick = () => { PL.over = null; PL.g = null; plSetup(); $("#pl-go").click(); };
  $("#pl-new").onclick = async () => { PL.o = await api("GET", "/api/play"); plSetup(); };
}
