// Chess Review - the Library: your games, Sync, filters, ticked-game actions. Shares the page's globals with app.js (api, S, VIEWS, $, esc, ...).

// ------------------------------------------------------------------ Library
const LIB = { q: "", outcome: "all", tc: "all", status: "all", side: "all", period: "all", oppMin: "", oppMax: "", fresh: false, shown: 100 };
const SEL = new Set();   // selected game ids (for "Analyse selected")
let syncTimer = null;

VIEWS.library = async function () {
  await loadGames();
  const m = $("#main");
  const hasUser = !!(S.settings.chesscom_user || S.settings.lichess_user);
  m.innerHTML = `<div class="page">
    <div class="page-head"><h1>Library</h1><span class="muted">${S.games.length} game${S.games.length === 1 ? "" : "s"}</span>
      <span class="spacer"></span>
      <span class="muted small" id="sync-last"></span>
      <button id="lib-sync" title="${hasUser ? "Fetch new games from your accounts" : "Add your usernames in Settings first"}">⟳ Sync</button>
      <button class="primary" id="lib-add">+ Add games</button></div>
    ${S.status?.engines?.stockfish ? "" : `<div class="card lib-nosf"><b>Stockfish isn't installed yet,</b> so games can't be analysed. You can still sync, paste and browse them. <a href="#/setup">Set it up</a></div>`}
    <div id="sync-box"></div>
    <div id="lib-plan"></div>
    <div id="lib-body"></div></div>`;
  if (typeof planStrip === "function") planStrip($("#lib-plan"));
  $("#lib-add").onclick = openImport;
  $("#lib-sync").onclick = startSync;
  renderLibrary();
  pollJobs();
  pollSync(true);
};

async function startSync() {
  if (!S.settings.chesscom_user && !S.settings.lichess_user) { toast("Add your chess.com / Lichess username in Settings first", true); location.hash = "#/settings"; return; }
  try { await api("POST", "/api/sync"); pollSync(); }
  catch (e) { toast(e.message, true); }
}

const ago = t => {
  const s = (Date.now() / 1000) - t;
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(t * 1000).toLocaleDateString();
};

async function pollSync(once) {
  clearTimeout(syncTimer);
  let st;
  try { st = await api("GET", "/api/sync"); } catch (e) { return; }
  S.sync = st;
  const box = $("#sync-box"), last = $("#sync-last"), btn = $("#lib-sync");
  if (!box) return;
  if (st.last) last.textContent = `Synced ${ago(st.last.finished || st.last.at)}`;
  if (st.state === "running") {
    btn.disabled = true;
    box.innerHTML = `<div class="card row" style="margin-bottom:12px;gap:12px"><span class="spin"></span>
      <span>${esc(st.step)} <span class="muted">· ${st.added} new so far</span></span><span class="spacer" style="flex:1"></span>
      <button class="sm" id="sync-stop">Stop</button></div>`;
    $("#sync-stop").onclick = () => api("POST", "/api/sync/cancel");
    syncTimer = setTimeout(() => pollSync(), 700);
    return;
  }
  btn.disabled = false;
  if (!once && (st.state === "done" || st.state === "cancelled" || st.state === "error")) {
    await loadGames();
    LIB.fresh = st.added > 0; LIB.shown = 100;
    box.innerHTML = `<div class="card row" style="margin-bottom:12px;gap:10px">
      <span>${st.state === "cancelled" ? "Sync stopped" : "Sync finished"}: <b>${st.added}</b> new game${st.added === 1 ? "" : "s"}${st.added ? " - showing them below. Nothing is analysed until you pick games." : "."}${st.filtered ? ` <span class="muted">${st.filtered.toLocaleString()} skipped by your <a href="#/settings">sync filters</a>.</span>` : ""}</span>
      ${st.errors.length ? `<span class="status-no small">${esc(st.errors.join(" · "))}</span>` : ""}
      <span class="spacer" style="flex:1"></span><button class="sm ghost" id="sync-x">✕</button></div>`;
    $("#sync-x").onclick = () => (box.innerHTML = "");
    $(".page-head .muted").textContent = `${S.games.length} games`;
    renderLibrary();
  }
}

function renderLibrary() {
  const body = $("#lib-body");
  if (!body) return;
  if (!S.games.length) {
    const hasUser = !!(S.settings.chesscom_user || S.settings.lichess_user);
    body.innerHTML = `<div class="card empty"><h2>No games yet</h2>
      <p class="muted">${hasUser ? "Press <b>Sync</b> to fetch your game list, or paste a game." : "Add your chess.com / Lichess username in <a href='#/settings'>Settings</a> to sync your games, or paste a PGN or link."}</p>
      <div class="row" style="justify-content:center">${hasUser ? `<button class="primary" id="emp-sync">⟳ Sync my games</button>` : ""}<button id="emp-add">+ Add games</button></div></div>`;
    $("#emp-add").onclick = openImport;
    if ($("#emp-sync")) $("#emp-sync").onclick = startSync;
    return;
  }
  const tcs = [...new Set(S.games.map(g => g.tc_category).filter(x => x && x !== "unknown"))];
  const chip = (key, val, label) => `<span class="chip ${LIB[key] === val ? "on" : ""}" data-k="${key}" data-v="${val}">${label}</span>`;
  const fresh = S.sync?.last && S.games.some(g => g.imported_at >= S.sync.last.at);
  body.innerHTML = `<div class="filters">
      <input type="search" id="lib-q" placeholder="Opponent, opening, ECO…" value="${esc(LIB.q)}">
      ${chip("outcome", "all", "All")}${chip("outcome", "win", "Wins")}${chip("outcome", "loss", "Losses")}${chip("outcome", "draw", "Draws")}
      <span class="sep"></span>
      ${chip("side", "all", "Both colours")}${chip("side", "White", "White")}${chip("side", "Black", "Black")}
      <span class="sep"></span>
      ${chip("status", "all", "Any")}${chip("status", "analysed", "Analysed")}${chip("status", "new", "Not analysed")}
      ${fresh ? `<span class="chip ${LIB.fresh ? "on" : ""}" id="f-fresh">New from last sync</span>` : ""}
    </div>
    <div class="filters">
      <select id="lib-period">${[["all", "Any date"], ["7", "Last 7 days"], ["30", "Last 30 days"], ["90", "Last 3 months"], ["365", "Last year"]].map(([v, l]) => `<option value="${v}" ${LIB.period === v ? "selected" : ""}>${l}</option>`).join("")}</select>
      ${tcs.length > 1 ? `<select id="lib-tc"><option value="all">All time controls</option>${tcs.map(t => `<option value="${t}" ${LIB.tc === t ? "selected" : ""}>${cap(t)}</option>`).join("")}</select>` : ""}
      ${(() => { const tags = [...new Set((S.games || []).flatMap(g => g.tags || []))].sort(); return tags.length ? `<select id="lib-tag" aria-label="Tag"><option value="">Any tag</option>${tags.map(t => `<option value="${esc(t)}" ${LIB.tag === t ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>` : ""; })()}
      <span class="oppr"><span class="muted small">Opponent rating</span><input type="number" id="opp-min" placeholder="min" value="${esc(LIB.oppMin)}" style="width:80px"><span class="muted">–</span><input type="number" id="opp-max" placeholder="max" value="${esc(LIB.oppMax)}" style="width:80px"></span>
      <span class="spacer" style="flex:1"></span>
      <span class="muted small" id="sel-count"></span>
      <a class="small" id="sel-matching" hidden></a>
      <button class="ghost danger" id="sel-del" disabled>Delete</button>
      <button class="ghost" id="sel-pgn" disabled title="Annotated PGN of the ticked games, saved to Downloads">Export PGN</button>
      <button class="primary" id="sel-go" disabled>Analyse selected</button>
    </div>
    <div class="card fitwrap" style="padding:4px 6px"><table class="list fit games"><thead><tr>
      <th class="c-sel"><input type="checkbox" id="sel-all" title="Select all shown"></th>
      <th class="c-date">Date</th><th class="c-who">Opponent</th><th class="c-side"></th><th class="c-res">Result</th><th class="c-tc">Time</th><th class="c-op">Opening</th><th class="num c-acc">You</th><th class="num c-opp">Opp.</th><th class="c-err">Errors</th><th class="c-st">Status</th>
    </tr></thead><tbody id="lib-rows"></tbody></table></div>
    <div class="row" style="justify-content:center;margin-top:10px" id="more-box"></div>`;
  let nt;
  $("#lib-q").oninput = e => {
    LIB.q = e.target.value; LIB.shown = 100; renderRows();
    clearTimeout(nt);
    const q = LIB.q.trim();
    if (!q) { LIB.noteIds = null; return; }
    nt = setTimeout(() => api("GET", "/api/notes/search?q=" + encodeURIComponent(q)).then(r => { if (LIB.q.trim() === q) { LIB.noteIds = new Set(r.ids); renderRows(); } }).catch(() => {}), 200);
  };
  if ($("#lib-tag")) $("#lib-tag").onchange = e => { LIB.tag = e.target.value; LIB.shown = 100; renderRows(); };
  $$(".chip[data-k]", body).forEach(c => c.onclick = () => { LIB[c.dataset.k] = c.dataset.v; LIB.shown = 100; renderLibrary(); });
  if ($("#f-fresh")) $("#f-fresh").onclick = () => { LIB.fresh = !LIB.fresh; renderLibrary(); };
  $("#lib-period").onchange = e => { LIB.period = e.target.value; renderRows(); };
  if ($("#lib-tc")) $("#lib-tc").onchange = e => { LIB.tc = e.target.value; renderRows(); };
  $("#opp-min").onchange = e => { LIB.oppMin = e.target.value; renderRows(); };
  $("#opp-max").onchange = e => { LIB.oppMax = e.target.value; renderRows(); };
  $("#sel-all").onchange = e => {
    const ids = filteredGames().slice(0, LIB.shown).map(g => g.id);
    ids.forEach(id => e.target.checked ? SEL.add(id) : SEL.delete(id));
    renderRows();
  };
  $("#sel-matching").onclick = e => { e.preventDefault(); filteredGames().forEach(g => SEL.add(g.id)); renderRows(); };
  $("#sel-del").onclick = async () => {
    const b = $("#sel-del"), n = SEL.size;
    if (!n) return;
    if (!b.dataset.armed) { b.dataset.armed = "1"; b.textContent = `Delete ${n} game${n === 1 ? "" : "s"}? Click again`; setTimeout(() => { if (b.isConnected) { delete b.dataset.armed; updateSel(); } }, 5000); return; }
    delete b.dataset.armed; b.disabled = true; b.textContent = "Deleting…";
    try {
      const r = await api("POST", "/api/games/delete-many", { ids: [...SEL] });
      toast(`Deleted ${r.deleted} game${r.deleted === 1 ? "" : "s"}. Sync won't bring them back (see Settings).`);
    } catch (err) { toast(err.message, true); }
    SEL.clear(); await loadGames(); renderLibrary();
  };
  $("#sel-pgn").onclick = async () => {
    const b = $("#sel-pgn"), n = SEL.size;
    if (!n) return;
    b.disabled = true; b.textContent = "Exporting…";
    try {
      const r = await api("POST", "/api/export/pgn", { ids: [...SEL] });
      const day = new Date().toISOString().slice(0, 10);
      const f = await api("POST", "/api/save-download", { name: `${day} chess review ${r.count} game${r.count === 1 ? "" : "s"}.pgn`, text: r.pgn });
      toast(`Saved ${r.count} game${r.count === 1 ? "" : "s"} (${r.analysed} with analysis) to ${f.path.replace(/^.*[\/\\]Downloads[\/\\]/, "Downloads/")}`);
    } catch (err) { toast(err.message, true); }
    b.textContent = "Export PGN"; updateSel();
  };
  $("#sel-go").onclick = async () => {
    const ids = [...SEL].filter(id => { const g = S.games.find(x => x.id === id); return g && !g.analysed && g.player_color; });
    const r = await api("POST", "/api/analyse-many", { ids });
    SEL.clear();
    toast(`${r.queued} game${r.queued === 1 ? "" : "s"} queued`);
    pollJobs(); renderRows();
  };
  renderRows();
}

// search text: lower case, ’ ' ` dropped, - _ : , turned into spaces, so "kings indian", "King's Indian"
// and "king’s-indian" all match "King's Indian Defense"
const normSearch = s => (s || "").toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "").replace(/['’‘`´]/g, "").replace(/[-_:,./()]+/g, " ").replace(/\s+/g, " ").trim();
function filteredGames() {
  const words = normSearch(LIB.q).split(" ").filter(Boolean);
  const since = LIB.period === "all" ? "" : new Date(Date.now() - (+LIB.period) * 86400e3).toISOString().slice(0, 10);
  const lo = LIB.oppMin === "" ? -1 : +LIB.oppMin, hi = LIB.oppMax === "" ? 1e9 : +LIB.oppMax;
  const freshAt = LIB.fresh && S.sync?.last ? S.sync.last.at : null;
  return S.games.filter(g =>
    (LIB.outcome === "all" || g.outcome === LIB.outcome) &&
    (LIB.tc === "all" || g.tc_category === LIB.tc) &&
    (LIB.side === "all" || g.me === LIB.side) &&
    (LIB.status === "all" || (LIB.status === "analysed") === g.analysed) &&
    (!since || (g.played_at || "") >= since) &&
    ((lo < 0 && hi >= 1e9) || (g.opp_elo != null && g.opp_elo >= lo && g.opp_elo <= hi)) &&
    (!freshAt || g.imported_at >= freshAt) &&
    (!LIB.tag || (g.tags || []).includes(LIB.tag)) &&
    (!words.length || (LIB.noteIds && LIB.noteIds.has(g.id)) || (hay => words.every(w => hay.includes(w)))(normSearch([g.white, g.black, g.opening, g.eco, ...(g.tags || [])].join(" ")))));
}

function statusCell(g) {
  const j = S.jobs[g.id] || g.job;
  if (j && j.state === "running") {
    const pct = j.total ? Math.round(100 * j.done / j.total) : 0;
    return `<span class="prog sm" title="Analysing: ${pct}%"><i style="width:${pct}%"></i></span><button class="sm ghost x" data-act="cancel" title="Stop">×</button>`;
  }
  if (j && j.state === "queued") return `<span class="muted small" title="Queued">Queued</span><button class="sm ghost x" data-act="cancel" title="Cancel">×</button>`;
  if (g.analysed) return `<span class="st-done" title="Analysed · depth ${g.depth}">✓ <span class="muted small">d${g.depth}</span></span>`;
  if (!g.player_color) return `<span class="muted small" title="Which side were you?">Side?</span> <button class="sm" data-act="White" title="I was White"><span class="side White"></span></button><button class="sm" data-act="Black" title="I was Black"><span class="side Black"></span></button>`;
  return `<button class="sm" data-act="analyse">Analyse</button>${j && j.state === "error" ? ` <span class="status-no small" title="${esc(j.error)}">!</span>` : ""}`;
}

function renderRows() {
  const tb = $("#lib-rows");
  if (!tb) return;
  const all = filteredGames(), rows = all.slice(0, LIB.shown);
  const seen = oppCounts();
  tb.innerHTML = rows.map(g => {
    const opp = g.opponent ?? `${g.white} – ${g.black}`;
    const selectable = true;
    const counts = g.analysed ? `<span class="counts">${g.brilliant ? `<span class="br" title="Brilliant">${g.brilliant}!!</span>` : ""}${g.great ? `<span class="gr" title="Great">${g.great}!</span>` : ""}${g.blunders ? `<span class="b">${g.blunders}B</span>` : ""}${g.mistakes ? `<span class="m">${g.mistakes}M</span>` : ""}${g.inaccuracies ? `<span class="i">${g.inaccuracies}I</span>` : ""}${!g.blunders && !g.mistakes && !g.inaccuracies && !g.brilliant && !g.great ? `<span class="z">none</span>` : ""}</span>` : "";
    return `<tr class="click ${SEL.has(g.id) ? "sel" : ""}" data-id="${esc(g.id)}">
      <td>${selectable ? `<input type="checkbox" class="sel" ${SEL.has(g.id) ? "checked" : ""}>` : ""}</td>
      <td class="muted">${esc((g.played_at || "").slice(0, 10) || "—")}</td>
      <td title="${esc(opp)}${g.opp_elo ? ` (${g.opp_elo})` : ""}${(g.tags || []).length ? " · " + esc(g.tags.join(", ")) : ""}${g.notes ? " · has notes" : ""}">${g.opponent && seen[g.opponent.toLowerCase()] >= 2 ? `<a class="opp-link" href="#/opponent/${encodeURIComponent(g.opponent)}" title="${seen[g.opponent.toLowerCase()]} games against them: open their page"><b>${esc(opp)}</b></a>` : `<b>${esc(opp)}</b>`}${g.opp_elo ? ` <span class="muted">(${g.opp_elo})</span>` : ""}${(g.tags || []).map(t => ` <span class="tag sm">${esc(t)}</span>`).join("")}${g.notes ? ` <span class="mnote" aria-label="has notes">✎</span>` : ""}</td>
      <td>${g.me ? `<span class="side ${g.me}" title="You played ${g.me}"></span>` : ""}</td>
      <td><span class="res ${g.outcome}">${g.outcome === "unknown" ? esc(g.result) : cap(g.outcome)}</span></td>
      <td class="muted c-tc">${esc(g.tc_category && g.tc_category !== "unknown" ? cap(g.tc_category) + (g.tc_category === "daily" ? "" : " " + fmtTC(g.time_control)) : "—")}</td>
      <td class="muted c-op" title="${esc(g.opening || "")}">${esc(g.opening || g.eco || "")}</td>
      <td class="num">${g.analysed ? `<b>${g.accuracy.toFixed(1)}</b>` : `<span class="muted">—</span>`}</td>
      <td class="num muted c-opp">${g.analysed && g.opp_accuracy != null ? g.opp_accuracy.toFixed(1) : ""}</td>
      <td class="c-err">${counts}</td>
      <td class="st">${statusCell(g)}</td></tr>`;
  }).join("") || `<tr><td colspan="11" class="muted" style="text-align:center;padding:20px">No games match.</td></tr>`;
  $$("tr.click", tb).forEach(tr => {
    tr.onclick = e => {
      const id = tr.dataset.id, b = e.target.closest("button");
      if (e.target.classList.contains("sel")) {
        e.stopPropagation();
        e.target.checked ? SEL.add(id) : SEL.delete(id);
        tr.classList.toggle("sel", e.target.checked); updateSel(); return;
      }
      if (e.target.closest(".opp-link")) { e.stopPropagation(); return; }
      if (b) {
        e.stopPropagation();
        if (b.dataset.act === "cancel") api("POST", `/api/games/${encodeURIComponent(id)}/cancel`).then(pollJobs);
        else {
          const side = b.dataset.act === "analyse" ? null : b.dataset.act, g = S.games.find(x => x.id === id);
          if (side && g) g.player_color = side;   // the side is saved even when Analyse is refused (no Stockfish)
          analyse(id, side).then(() => updateLibraryJobs(false));
        }
        return;
      }
      if (e.target.closest("td") === tr.firstElementChild) return;
      location.hash = `#/review/${encodeURIComponent(id)}`;
    };
  });
  const more = $("#more-box");
  more.innerHTML = all.length > rows.length ? `<button id="more">Show ${Math.min(200, all.length - rows.length)} more</button><span class="muted small">${rows.length} of ${all.length}</span>` : (all.length > 20 ? `<span class="muted small">${all.length} games</span>` : "");
  if ($("#more")) $("#more").onclick = () => { LIB.shown += 200; renderRows(); };
  updateSel();
}

function updateSel() {
  for (const id of [...SEL]) { if (!S.games.some(x => x.id === id)) SEL.delete(id); }
  const btn = $("#sel-go"), c = $("#sel-count"), del = $("#sel-del"), mt = $("#sel-matching");
  if (!btn) return;
  const toAnalyse = [...SEL].map(id => S.games.find(x => x.id === id)).filter(g => g && !g.analysed && g.player_color);
  const n = toAnalyse.length;
  btn.disabled = !n;
  btn.textContent = n ? `Analyse ${n} selected` : "Analyse selected";
  const px = $("#sel-pgn");
  if (px && px.textContent === "Export PGN") px.disabled = !SEL.size;
  if (del && !del.dataset.armed) { del.disabled = !SEL.size; del.textContent = SEL.size ? `Delete ${SEL.size}` : "Delete"; }
  const plies = toAnalyse.reduce((a, g) => a + (g.n_plies || 80), 0);
  c.textContent = SEL.size ? `${SEL.size} selected${n ? ` · analysing ${n} takes about ${estMin(plies)} min at depth ${S.settings.depth}` : ""}` : "Tick games to analyse, export or delete them";
  if (mt) {
    const all = filteredGames().length;
    mt.hidden = !(SEL.size && SEL.size < all);
    mt.textContent = `Select all ${all.toLocaleString()} matching`;
  }
}

async function updateLibraryJobs(reload) {
  if (reload) { await loadGames(); renderRows(); return; }
  $$("#lib-rows tr.click").forEach(tr => {
    const g = S.games.find(x => x.id === tr.dataset.id);
    if (g) $(".st", tr).innerHTML = statusCell(g);
  });
}
