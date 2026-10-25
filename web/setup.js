// Chess Review - Setup (engines and downloads) and the first-run welcome. Shares the page's globals with app.js (api, S, VIEWS, $, esc, ...).

// ------------------------------------------------------------------ Setup
VIEWS.setup = async function () {
  S.status = await api("GET", "/api/status");
  const e = S.status.engines, m = $("#main");
  const su = e.setup;   // this system's install commands (engine/system.py)
  const cmd = (c) => `<pre class="cmd">${esc(c)}<button class="sm" data-copy="${esc(c)}">Copy</button></pre>`;
  const weights = Object.keys(e.maia_weights);
  const step = (ok, optional, title, body) => `<div class="setup-step"><div class="ic ${ok ? "status-ok" : optional ? "status-opt" : "status-no"}">${ok ? "✓" : optional ? "○" : "✕"}</div><div><h3>${title}</h3>${body}</div></div>`;
  m.innerHTML = `<div class="page" style="max-width:820px">
    <div class="page-head"><h1>Setup</h1><span class="spacer"></span><button id="recheck">Check again</button></div>
    <div class="card">
      <p class="muted" style="margin-top:0">The engines aren't bundled, which keeps the app small. Install them once: open ${su.shell} and paste each command.</p>
      ${step(!!e.stockfish, false, "Stockfish - required", e.stockfish ? `<div class="muted small">Found at <span class="mono">${esc(e.stockfish)}</span></div>` : `<div>The engine that does the analysis.</div>${cmd(su.stockfish)}<div class="muted small">${esc(su.stockfish_note)}</div>`)}
      ${step(!!e.lc0 && weights.length > 0, true, "Maia - optional", `<div class="muted small" style="margin-bottom:4px">A neural net trained on human games at each rating. It tells you whether a missed move is one players at your level usually find - worth training - or a computer-only move.</div>
        ${e.lc0 ? `<div class="muted small">lc0 found at <span class="mono">${esc(e.lc0)}</span></div>` : su.lc0 ? cmd(su.lc0) : `<div class="muted small">${esc(su.lc0_note)}</div>`}
        ${weights.length ? `<div class="muted small">Nets found: ${weights.join(", ")}</div>` : ""}${e.maia_missing.length && weights.length ? `<div class="muted small">Missing: ${e.maia_missing.join(", ")} (Play can only offer the ratings you have). This fetches them:</div>` : ""}${e.maia_missing.length ? cmd(su.maia) : ""}`)}
      ${step(!!e.book, true, "Opening book - optional", e.book ? `<div class="muted small">Found at <span class="mono">${esc(e.book)}</span></div>` : `<div class="muted small">Recognises when you're still in known opening theory. Without it the first 10 moves count as the opening.</div>${cmd(su.book)}`)}
      ${step(!!(S.settings.chesscom_user || S.settings.lichess_user), true, "Your usernames", `<div class="muted small">So the app knows which side you played. <a href="#/settings">Add them in Settings</a>${S.settings.chesscom_user ? ` - chess.com: <b>${esc(S.settings.chesscom_user)}</b>` : ""}${S.settings.lichess_user ? ` · Lichess: <b>${esc(S.settings.lichess_user)}</b>` : ""}.</div>`)}
    </div>
    <div class="muted small" style="margin-top:10px">Installed an engine somewhere else? Point at it in <a href="#/settings">Settings</a> > Engines.</div>
    ${!S.status.setup_done ? `<div class="row" style="margin-top:14px"><span class="spacer" style="flex:1"></span><button class="primary" id="done" ${e.stockfish ? "" : "disabled"}>Done - go to the Library</button></div>` : ""}
  </div>`;
  $$("[data-copy]", m).forEach(b => b.onclick = () => copyText(b.dataset.copy.replaceAll("&quot;", '"')));
  $("#recheck").onclick = async () => { await VIEWS.setup(); updateBadge(); toast("Checked"); };
  if ($("#done")) $("#done").onclick = async () => { await api("POST", "/api/setup-done"); S.status.setup_done = true; location.hash = "#/library"; };
  updateBadge();
};

function updateBadge() { $("#setup-badge").hidden = !!S.status?.engines?.stockfish; }

// ------------------------------------------------------------------ V7: first run - a short welcome that gets you to your games
VIEWS.welcome = async function () {
  const w = await api("GET", "/api/welcome");
  S.status = await api("GET", "/api/status");
  const s = S.settings, sf = !!S.status.engines.stockfish;
  const m = $("#main");
  const step = (n, title, body, done) => `<div class="card wl-step ${done ? "done" : ""}"><div class="wl-n">${done ? "✓" : n}</div><div class="wl-b"><h3>${title}</h3>${body}</div></div>`;
  m.innerHTML = `<div class="page" style="max-width:760px">
    <div class="page-head"><div><h1>Welcome to Chess Review</h1><div class="muted">A few steps to your first reviewed games. Everything stays on this ${S.status.platform === "mac" ? "Mac" : "computer"}.</div></div><span class="spacer"></span><a class="small" id="wl-skip">Skip, I'll set it up myself</a></div>
    ${step(1, "Your accounts", `<p class="muted small">Your games are fetched from these, only when you press Sync. Either is enough.</p>
      <div class="field"><label>chess.com username</label><input id="wl-cc" value="${esc(s.chesscom_user || "")}" placeholder="your chess.com name"></div>
      <div class="field"><label>Lichess username</label><input id="wl-li" value="${esc(s.lichess_user || "")}"></div>
      <div class="field"><label>Your rating</label><span><input id="wl-r" type="number" min="400" max="3000" step="10" value="${s.rating || 1200}" style="width:90px"> <span class="muted small">until your synced games show your rating; then each time control's own is used</span></span></div>`, w.users)}
    ${step(2, "The engine", sf ? `<p class="muted small">Stockfish found at <span class="mono">${esc(S.status.engines.stockfish)}</span>.</p>`
      : `<p class="muted small">The analysis needs Stockfish. Open ${esc(S.status.engines.setup.shell)}, paste this, then press Check again. ${esc(S.status.engines.setup.stockfish_note)}</p><pre class="cmd">${esc(S.status.engines.setup.stockfish)}<button class="sm" data-copy="${esc(S.status.engines.setup.stockfish)}">Copy</button></pre><button class="sm" id="wl-recheck">Check again</button>`, sf)}
    ${step(3, "Which games", `<p class="muted small">Recent games keep the app quick; you can change this in Settings > Sync.</p>
      <div class="field"><label>Period</label><select id="wl-win">${[["3m", "Last 3 months"], ["6m", "Last 6 months"], ["12m", "Last 12 months"], ["24m", "Last 2 years"], ["all", "All my games"]].map(([k, l]) => `<option value="${k}" ${(s.sync_window === "all" && !w.games ? "6m" : s.sync_window) === k ? "selected" : ""}>${l}</option>`).join("")}</select></div>`, false)}
    ${step(4, "A study plan (optional)", `<p class="muted small">How much time a week do you want to train? The app splits it across puzzles, openings, convert drills and reviewing games, and shows what to do next. You can change it or switch it off in Settings.</p>
      <div class="field"><label>Time per week</label>${planSelect(s.plan_minutes ?? 120)}<input type="number" id="pl-custom" min="15" max="3000" step="15" placeholder="minutes" style="width:90px" hidden></div>`, false)}
    ${step(5, "Fetch and analyse", `<p class="muted small">Sync fetches the games; nothing is analysed until you ask. Analysing 10 games takes a few minutes.</p>
      <div class="row" style="gap:8px"><button class="primary" id="wl-sync">Save and sync</button><button id="wl-an" disabled>Analyse my last 10</button><button class="ghost" id="wl-done">Open the Library</button></div>
      <div class="small" id="wl-msg" style="margin-top:8px"></div>`, false)}
  </div>`;
  $$("[data-copy]", m).forEach(b => b.onclick = () => copyText(b.dataset.copy));
  if ($("#wl-recheck")) $("#wl-recheck").onclick = () => VIEWS.welcome();
  const wlPlan = () => { const v = $("#pl-sel").value; return v === "custom" ? Math.max(15, Math.round(+$("#pl-custom").value || 0)) || 120 : +v; };
  $("#pl-sel").onchange = e => { $("#pl-custom").hidden = e.target.value !== "custom"; };
  const finish = async (skip) => {
    if (skip !== true) S.settings = await api("POST", "/api/settings", { plan_minutes: wlPlan() });
    await api("POST", "/api/welcome/done"); location.hash = "#/library";
  };
  $("#wl-skip").onclick = () => finish(true);
  $("#wl-done").onclick = finish;
  $("#wl-sync").onclick = async () => {
    const cc = $("#wl-cc").value.trim(), li = $("#wl-li").value.trim();
    if (!cc && !li) { $("#wl-msg").innerHTML = `<span class="status-no">Add a chess.com or Lichess username first.</span>`; return; }
    S.settings = await api("POST", "/api/settings", { chesscom_user: cc, lichess_user: li, rating: +$("#wl-r").value || 1200, sync_window: $("#wl-win").value, plan_minutes: wlPlan() });
    $("#wl-sync").disabled = true;
    try { await api("POST", "/api/sync"); } catch (e) { $("#wl-msg").innerHTML = `<span class="status-no">${esc(e.message)}</span>`; $("#wl-sync").disabled = false; return; }
    const tick = async () => {
      if (S.view !== "welcome") return;
      const st = await api("GET", "/api/sync").catch(() => null);
      if (!st) return;
      if (st.state === "running") { $("#wl-msg").innerHTML = `<span class="spin"></span> ${esc(st.step || "Syncing…")} · ${st.added} games so far`; setTimeout(tick, 800); return; }
      $("#wl-msg").innerHTML = `${st.added} game${st.added === 1 ? "" : "s"} fetched.${st.errors && st.errors.length ? ` <span class="status-no">${esc(st.errors.join(" · "))}</span>` : ""}`;
      $("#wl-sync").disabled = false; $("#wl-sync").textContent = "Sync again";
      $("#wl-an").disabled = !st.added && !(await api("GET", "/api/welcome")).games;
    };
    tick();
  };
  $("#wl-an").onclick = async () => {
    if (!sf) { $("#wl-msg").innerHTML = `<span class="status-no">Install Stockfish first (step 2).</span>`; return; }
    const r = await api("POST", "/api/analyse-recent", { n: 10 });
    $("#wl-an").disabled = true;
    $("#wl-msg").textContent = r.queued ? `${r.queued} games queued. The Library shows their progress; open any of them when it's done.` : "Nothing left to analyse.";
    pollJobs();
  };
};
