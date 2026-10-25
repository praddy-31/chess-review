// Chess Review - Settings. Shares the page's globals with app.js (api, S, VIEWS, $, esc, ...).

// ------------------------------------------------------------------ Settings
const THEMES = [["mocha", "Mocha"], ["macchiato", "Macchiato"], ["tokyo", "Tokyo Night"], ["nord", "Nord"], ["rosepine", "Rosé Pine"],
  ["dracula", "Dracula"], ["gruvbox", "Gruvbox"], ["kanagawa", "Kanagawa"], ["onedark", "One Dark"], ["everforest", "Everforest"],
  ["frappe", "Frappé"], ["monokai", "Monokai"], ["ayu", "Ayu Mirage"], ["nightowl", "Night Owl"], ["palenight", "Palenight"],
  ["synthwave", "Synthwave '84"], ["poimandres", "Poimandres"], ["solarized-dark", "Solarized Dark"], ["github-dark", "GitHub Dark"], ["horizon", "Horizon"]];
const LIGHT_THEMES = [["latte", "Latte"], ["solarized", "Solarized Light"], ["github", "GitHub Light"], ["dawn", "Rosé Pine Dawn"]];
const PIECE_SETS = [["cburnett", "Classic"], ["merida", "Merida"], ["chessnut", "Chessnut"], ["fantasy", "Fantasy"]];
const BOARDS = [["green", "#ebecd0", "#739552"], ["brown", "#f0d9b5", "#b58863"], ["blue", "#dee3e6", "#8ca2ad"], ["slate", "#aab3c0", "#5a6678"]];
const TH_LABELS = {
  inaccuracy_pp: ["Inaccuracy from", "points of win chance lost"], mistake_pp: ["Mistake from", "points"], blunder_pp: ["Blunder from", "points"],
  missed_opportunity_cp: ["Missed chance gap", "centipawns better"], missed_still_ok_cp: ["…while your move kept", "centipawns or better"],
  opening_ply: ["Book moves count until move", "(after that a known move is graded like any other)"],
  winning_cp: ["Winning / losing from", "centipawns"], threat_cp: ["A threat gains", "centipawns or more"], tactical_swing_cp: ["Tactical swing", "centipawns or more"],
  great_pp: ["Great when next-best loses", "points of win chance"], great_max_win: ["…and you're below", "% win chance"],
  brilliant_sac: ["Brilliant sacrifice of", "points of material or more"], brilliant_max_win: ["…and you're below", "% win chance "],
};

// study plan choices (minutes per week; 0 = no plan)
const PLAN_CHOICES = [[0, "No plan"], [60, "1 hour"], [120, "2 hours"], [180, "3 hours"], [240, "4 hours"], [360, "6 hours"]];
function planSelect(cur) {
  const known = PLAN_CHOICES.some(([v]) => v === (cur ?? 0));
  return `<select id="pl-sel">${PLAN_CHOICES.map(([v, l]) => `<option value="${v}" ${known && v === (cur ?? 0) ? "selected" : ""}>${l}</option>`).join("")}<option value="custom" ${known ? "" : "selected"}>Custom…</option></select>`;
}

const TC_LIST = ["bullet", "blitz", "rapid", "classical", "daily"];   // V11: your rating per time control

VIEWS.settings = async function () {
  S.settings = await api("GET", "/api/settings");
  const s = S.settings, m = $("#main");
  const num = (k, min, max, step = 1) => `<input type="number" data-k="${k}" min="${min}" max="${max}" step="${step}" value="${s[k]}" style="width:90px">`;
  m.innerHTML = `<div class="page">
    <div class="page-head"><h1>Settings</h1><span class="spacer"></span><span class="muted small" id="saved"></span></div>
    <nav class="set-jump" aria-label="Settings sections">${[["you", "You"], ["plan", "Study plan"], ["sync", "Sync"], ["look", "Appearance"], ["analysis", "Analysis"], ["puzzles", "Puzzles"], ["openings", "Openings"], ["coach", "Coach"], ["labels", "Labels"], ["data", "Engines & data"]].map(([k, l]) => `<a href="#" data-jump="set-${k}">${l}</a>`).join("")}</nav>
    <div class="settings">
      <div class="card" id="set-you"><h2>You</h2>
        <div class="field"><label>chess.com username</label><input type="text" data-k="chesscom_user" value="${esc(s.chesscom_user)}" placeholder="your chess.com name"></div>
        <div class="field"><label>Lichess username</label><input type="text" data-k="lichess_user" value="${esc(s.lichess_user)}"></div>
        <div class="field wide"><label>Rating</label><div>
          <label class="check" style="margin:0 0 6px"><input type="checkbox" data-k="rating_auto" ${s.rating_auto ? "checked" : ""}> From my games</label>
          ${s.rating_auto ? (Object.keys(s.ratings || {}).length ? `<div class="rt-list">${TC_LIST.filter(t => s.ratings[t]).map(t => `<span class="chip ${s.rating_main_tc === t ? "on" : ""}" data-rtc="${t}" role="radio" aria-checked="${s.rating_main_tc === t}" tabindex="0" title="Your latest ${t} game on ${s.ratings[t].site === "chesscom" ? "chess.com" : "Lichess"}, ${esc(s.ratings[t].at)}">${t[0].toUpperCase() + t.slice(1)} <b>${s.ratings[t].elo}</b></span>`).join("")}</div>
            <div class="hint">Each game uses your rating at its speed (the one in the game). Where there's no game, as for Play's default Maia and opening study, the highlighted one counts: ${s.rating_tc ? "your pick" : "the time control you analyse most"}. Click another to use it.</div>`
            : `<div class="hint">No rated games yet: until there are, this counts:</div>${num("rating", 400, 3000, 10)}`)
          : `${num("rating", 400, 3000, 10)}<div class="hint">Used for Maia's level and opening study, and for games that don't show a rating.</div>`}
        </div></div>
      </div>
      <div class="card" id="set-plan"><h2>Study plan</h2>
        <div class="muted small" style="margin-bottom:6px">Your training time for the week, split across puzzles, opening study, convert drills and reviewing your games, and tilted toward your weekly focus. It shows on Insights and above the Library. Pick "No plan" to switch it off.</div>
        <div class="field"><label>Time per week</label><span class="row" style="gap:8px">${planSelect(s.plan_minutes)}<input type="number" id="pl-custom" min="15" max="3000" step="15" value="${s.plan_minutes || ""}" placeholder="minutes" style="width:90px" ${PLAN_CHOICES.some(([v]) => v === (s.plan_minutes ?? 0)) ? "hidden" : ""}></span></div>
      </div>
      <div class="card" id="set-sync"><h2>Sync</h2>
        <div class="muted small" style="margin-bottom:6px">Only games inside these are downloaded, to keep the Library small. Changing them re-checks the months in range on the next Sync.</div>
        <div class="field"><label>Period</label><span class="row" style="gap:8px">
          <select id="sy-win">${[["all", "All games"], ["3m", "Last 3 months"], ["6m", "Last 6 months"], ["12m", "Last 12 months"], ["24m", "Last 2 years"], ["since", "Since a date…"]].map(([k, l]) => `<option value="${k}" ${s.sync_window === k ? "selected" : ""}>${l}</option>`).join("")}</select>
          <input type="date" id="sy-since" value="${esc(s.sync_since || "")}" ${s.sync_window === "since" ? "" : "hidden"}></span></div>
        <div class="field"><label>Time controls</label><span class="sy-tcs">${["bullet", "blitz", "rapid", "classical", "daily"].map(t => `<label class="check inline"><input type="checkbox" data-tc="${t}" ${!(s.sync_tcs || []).length || s.sync_tcs.includes(t) ? "checked" : ""}> ${cap(t)}</label>`).join("")}</span></div>
        <div class="field"><label>Opponent rating</label><span class="oppr"><input type="number" id="sy-min" placeholder="min" value="${s.sync_opp_min ?? ""}" style="width:80px"><span class="muted">–</span><input type="number" id="sy-max" placeholder="max" value="${s.sync_opp_max ?? ""}" style="width:80px"></span></div>
        <div class="field"><label>Outside these</label><span class="small" id="sy-out">…</span></div>
      </div>
      <div class="card" id="set-look"><h2>Appearance</h2>
        <div id="pal-box"></div>
        ${[["Dark", THEMES], ["Light", LIGHT_THEMES]].map(([grp, list]) => `<div class="small muted" style="margin:${grp === "Dark" ? 0 : 12}px 0 6px">${grp}</div>
        <div class="themes">${list.map(([k, l]) => `<button type="button" class="theme-tile ${s.theme === k ? "on" : ""}" data-theme="${k}" data-pick="${k}" aria-pressed="${s.theme === k}"><span class="sw"><i style="background:var(--surface)"></i><i style="background:var(--accent)"></i><i style="background:var(--good)"></i><i style="background:var(--critical)"></i></span>${l}</button>`).join("")}</div>`).join("")}
        <div class="field wide" style="margin-top:14px"><label>Pieces</label><div class="piece-sets">${PIECE_SETS.map(([k, l]) => `<button type="button" class="piece-tile ${(s.pieces || "cburnett") === k ? "on" : ""}" data-piece-pick="${k}" aria-pressed="${(s.pieces || "cburnett") === k}"><img src="pieces/${k}/wN.svg" alt=""><img src="pieces/${k}/bQ.svg" alt=""><span>${l}</span></button>`).join("")}</div></div>
        <div class="field wide" style="margin-top:6px"><label>Board</label><div class="boards">${BOARDS.map(([k, a, b]) => `<div class="board-tile ${(s.board || "green") === k ? "on" : ""}" data-board-pick="${k}"><i style="background:${a}"></i><i style="background:${b}"></i><i style="background:${b}"></i><i style="background:${a}"></i></div>`).join("")}</div></div>
        <div class="field" style="margin-top:6px"><label>Tips</label><span><button type="button" class="sm" id="tips-again" ${(s.tips_seen || []).length ? "" : "disabled"}>Show the tips again</button> <span class="muted small">the short note each screen shows the first time</span></span></div>
      </div>
      <div class="card" id="set-analysis"><h2>Analysis</h2>
        <div class="field"><label>Depth</label>${num("depth", 8, 30)}<div class="hint">16 is the default. 12 for a quick pass, 20+ when it matters.</div></div>
        <div class="field"><label>CPU threads</label>${num("threads", 1, 16)}<div class="hint">1 gives repeatable numbers; more is faster.</div></div>
        <div class="field"><label>Engine memory (MB)</label>${num("hash_mb", 16, 4096, 16)}</div>
        <label class="check"><input type="checkbox" data-k="use_maia" ${s.use_maia ? "checked" : ""}> Compare with Maia (how players at your level move) when it's installed</label>
        <label class="check"><input type="checkbox" data-k="probe_threats" ${s.probe_threats ? "checked" : ""}> Detect threats (who has the initiative: attacking / defending; costs a little time per move)</label>
      </div>
      <div class="card" id="set-puzzles"><h2>Puzzles</h2>
        <div class="muted small" style="margin-bottom:6px">Built from your analysed games: your mistakes and missed chances, retries you didn't solve, and - if ticked - the moment right after your opponent's mistakes, to punish them.</div>
        <div class="field"><label>Puzzles per day</label>${num("puzzles_per_day", 1, 100)}</div>
        <div class="field"><label>Convert drills per day</label>${num("convert_per_day", 0, 30)}<div class="hint">Winning positions from your games to play out against Maia at your opponent's rating.</div></div>
        <label class="check"><input type="checkbox" data-k="puzzles_include_opponent" ${s.puzzles_include_opponent ? "checked" : ""}> Also make "punish it" puzzles from my opponents' mistakes</label>
        <label class="check"><input type="checkbox" data-k="puzzle_judgement" ${s.puzzle_judgement !== false ? "checked" : ""}> Ask "one move or several?" before each puzzle</label>
        <label class="check"><input type="checkbox" data-k="puzzle_clock" ${s.puzzle_clock ? "checked" : ""}> Puzzle clock: your per-move time for that game's time control (over time = back sooner, not a miss)</label>
        <label class="check"><input type="checkbox" data-k="insights_include_maia" ${s.insights_include_maia ? "checked" : ""}> Count games I play against Maia in Insights, opponents and the weekly note (they always make puzzles; never part of your opening tree)</label>
      </div>
      <div class="card" id="set-openings"><h2>Openings</h2>
        <div class="muted small" style="margin-bottom:6px">You study your repertoire line by line: a few new lines a day, plus every review that's due. Repertoires built from your games go up to ${s.rating_used < 1000 ? 6 : s.rating_used < 1400 ? 8 : s.rating_used < 1800 ? 10 : 12} of your moves at your rating (${s.rating_used}), along lines with at least 3 games and 1% of your games.</div>
        <div class="field"><label>New lines per day</label>${num("new_lines_per_day", 0, 50)}</div>
        <div class="field"><label>Length when you learn an opening</label><span>${num("learn_depth", 1, 5)} <span class="muted small">1 short … 3 recommended for your rating … 5 to the end of theory</span></span></div>
        <label class="check"><input type="checkbox" data-k="explorer_lookup" ${s.explorer_lookup ? "checked" : ""}> Show what's played at my level on Lichess (asks the Lichess explorer over the internet)</label>
        <div class="field"><label>Lichess token</label><span><input type="password" data-k="explorer_token" value="${esc(s.explorer_token || "")}" placeholder="lip_…" autocomplete="off" style="width:220px">
          <div class="hint muted small">The explorer needs a Lichess login since 2025. Make a personal token with no scopes at lichess.org/account/oauth/token and paste it here; it stays on this Mac.</div></span></div>
      </div>
      <div class="card" id="set-coach"><h2>Coach</h2>
        <div class="muted small" style="margin-bottom:6px">"Ask the coach" on the Board gives Stockfish's facts about any move. A local model from <a id="ollama-link">Ollama</a> can put them into a few plain sentences; it runs on this Mac and is told to use only those facts.</div>
        <label class="check"><input type="checkbox" data-k="coach_ollama" ${s.coach_ollama ? "checked" : ""}> Explain in words with a local Ollama model</label>
        <div class="field"><label>Model</label><span id="coach-models" class="small muted">Looking for Ollama…</span></div>
      </div>
      <div class="card" id="set-labels"><h2>Labels <span class="muted small" style="font-weight:400">— advanced</span></h2>
        <div class="muted small">Changing these relabels every analysed game instantly; no re-analysis.</div>
        ${Object.entries(TH_LABELS).map(([k, [l, h]]) => `<div class="field"><label>${l}</label><span><input type="number" data-th="${k}" value="${s.thresholds[k]}" style="width:90px"> <span class="muted small">${h}</span></span></div>`).join("")}
        <button class="sm" id="th-reset">Reset to defaults</button>
      </div>
      <div class="card" id="set-data"><h2>Engines &amp; data</h2>
        <div class="field"><label>Stockfish</label><input type="text" data-k="stockfish_path" value="${esc(s.stockfish_path)}" placeholder="${esc(S.status?.engines?.stockfish || "not found")}"></div>
        <div class="field"><label>lc0</label><input type="text" data-k="lc0_path" value="${esc(s.lc0_path)}" placeholder="${esc(S.status?.engines?.lc0 || "not found")}"></div>
        <div class="field"><label>Maia weights folder</label><input type="text" data-k="maia_dir" value="${esc(s.maia_dir)}" placeholder="default folder"></div>
        <div class="field"><label>Opening book</label><input type="text" data-k="book_path" value="${esc(s.book_path)}" placeholder="${esc(S.status?.engines?.book || "none")}"></div>
        <div class="hint muted small">Leave empty to find them automatically (the PATH, the usual install folders, then the data folder's engines and maia folders).</div>
        <div class="field"><label>Data folder</label><span class="mono small">${esc(S.status?.engines?.data_dir || "")}</span></div>
        <div class="field"><label>Storage</label><span class="small" id="storage">…</span></div>
        <label class="check"><input type="checkbox" data-k="restore_deleted" ${s.restore_deleted ? "checked" : ""}> Bring back the games I deleted on the next Sync</label>
        <div class="field"><label>Backups</label><span id="backups" class="small">…</span></div>
        <div class="field"><label>Version</label><span class="small" id="app-version">Chess Review ${esc(S.status?.version || "")}</span></div>
      </div>
    </div></div>`;
  let t;
  const flash = () => { const el = $("#saved"); if (!el) return; el.textContent = "Saved"; clearTimeout(t); t = setTimeout(() => { const x = $("#saved"); if (x) x.textContent = ""; }, 1500); };
  const save = async patch => {
    try { S.settings = await api("POST", "/api/settings", patch); applyLook(); flash(); }
    catch (e) { toast(e.message, true); }
  };
  $$("[data-k]", m).forEach(inp => inp.onchange = () => {
    const k = inp.dataset.k;
    let v = inp.type === "checkbox" ? inp.checked : inp.type === "number" ? +inp.value : inp.value.trim();
    save({ [k]: v }).then(() => { if (k === "rating_auto") VIEWS.settings(); });
    if (k.endsWith("_path") || k === "maia_dir") api("GET", "/api/status").then(x => (S.status = x));
  });
  $$("[data-th]", m).forEach(inp => inp.onchange = () => save({ thresholds: { ...S.settings.thresholds, [inp.dataset.th]: +inp.value } }));
  $("#th-reset").onclick = async () => { await save({ thresholds: { inaccuracy_pp: 5, mistake_pp: 10, blunder_pp: 20, missed_opportunity_cp: 150, missed_still_ok_cp: -50, opening_ply: 20, endgame_material: 14, winning_cp: 100, threat_cp: 150, tactical_swing_cp: 300, great_pp: 20, great_max_win: 95, brilliant_sac: 2, brilliant_max_win: 90 } }); VIEWS.settings(); };
  $$("[data-pick]", m).forEach(tile => tile.onclick = async () => {
    $$("[data-pick]", m).forEach(x => x.classList.toggle("on", x === tile));
    const was = S.settings.follow_palette;
    await save({ theme: tile.dataset.pick, follow_palette: false });   // picking a theme here stops following Palette
    if (was) { paletteSync(); paletteSettings(); toast("Stopped following Palette"); }
  });
  paletteSettings();
  $$("[data-rtc]", m).forEach(c => c.onclick = async () => { await save({ rating_tc: c.dataset.rtc }); VIEWS.settings(); });
  $$("[data-piece-pick]", m).forEach(tile => tile.onclick = () => { $$("[data-piece-pick]", m).forEach(x => x.classList.toggle("on", x === tile)); save({ pieces: tile.dataset.piecePick }); });
  $("#tips-again").onclick = async e => { e.target.disabled = true; await save({ tips_seen: [] }); toast("Each screen shows its note again"); };
  $$("[data-board-pick]", m).forEach(tile => tile.onclick = () => { $$("[data-board-pick]", m).forEach(x => x.classList.toggle("on", x === tile)); save({ board: tile.dataset.boardPick }); });
  // ---- study plan
  $("#pl-sel").onchange = e => {
    const v = e.target.value;
    $("#pl-custom").hidden = v !== "custom";
    if (v === "custom") { $("#pl-custom").focus(); return; }
    save({ plan_minutes: +v });
  };
  $("#pl-custom").onchange = e => { const v = Math.max(15, Math.round(+e.target.value || 0)); if (v) save({ plan_minutes: v }); };
  // ---- coach: which Ollama models are here
  const coachModels = async () => {
    const el = $("#coach-models"); if (!el) return;
    const c = await api("GET", "/api/coach/status").catch(() => null);
    if (!c || !c.running) { el.innerHTML = `Ollama isn't running on this Mac. Open the Ollama app (or run <code>ollama serve</code>); new to it? Get it at ollama.com and <code>ollama pull gemma3:4b</code>. Then <a href="#" id="coach-re">check again</a>.`;
      if ($("#coach-re")) $("#coach-re").onclick = e => { e.preventDefault(); el.textContent = "Looking…"; coachModels(); }; return; }
    if (!c.models.length) { el.innerHTML = `Ollama is running but has no models yet: <code>ollama pull gemma3:4b</code>`; return; }
    el.innerHTML = `<select id="coach-model">${["", ...c.models].map(mm => `<option value="${esc(mm)}" ${mm === (s.coach_model || "") ? "selected" : ""}>${mm ? esc(mm) : "Pick a model…"}</option>`).join("")}</select> <span class="muted small">smaller models answer faster</span>`;
    $("#coach-model").onchange = e => save({ coach_model: e.target.value });
  };
  coachModels();
  // ---- backups
  const backups = async () => {
    const el = $("#backups"); if (!el) return;
    const b = await api("GET", "/api/backups").catch(() => null);
    if (!b) { el.textContent = ""; return; }
    const when = t => new Date(t * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
    const mb = x => (x / 1e6).toFixed(1) + " MB";
    el.innerHTML = `${b.pending ? `<div class="pz-msg hint" style="margin-bottom:6px">A restore is ready: quit and reopen the app to finish it. <a href="#" id="bk-cancel">Cancel the restore</a></div>` : ""}
      <div class="row" style="gap:8px;margin-bottom:6px"><button class="sm" id="bk-now">Back up now</button><button class="sm ghost" id="bk-show">Show in ${esc(S.status?.file_manager || "Finder")}</button>
        <span class="muted small">${b.backups.length ? `${b.backups.length} kept; a new one each week on its own` : "A backup is made each week on its own; none yet"}</span></div>
      ${b.backups.slice(0, 5).map(x => `<div class="bk-row"><span>${when(x.at)}</span><span class="muted small">${x.kind === "auto" ? "automatic" : "manual"} · ${mb(x.bytes)}</span><button class="sm ghost" data-restore="${esc(x.name)}">Restore</button></div>`).join("")}`;
    $("#bk-now").onclick = async () => { $("#bk-now").disabled = true; try { await api("POST", "/api/backups"); toast("Backed up"); } catch (e) { toast(e.message, true); } backups(); };
    $("#bk-show").onclick = () => api("POST", "/api/backups/reveal");
    if ($("#bk-cancel")) $("#bk-cancel").onclick = async e => { e.preventDefault(); await api("POST", "/api/backups/cancel"); backups(); };
    $$("[data-restore]", el).forEach(btn => btn.onclick = async () => {
      if (!btn.dataset.armed) { btn.dataset.armed = 1; btn.textContent = "Replace today's data?"; return; }
      try { const r = await api("POST", "/api/backups/restore", { name: btn.dataset.restore }); toast(`Ready: ${r.games.toLocaleString()} games. Quit and reopen the app to finish.`); }
      catch (e) { toast(e.message, true); }
      backups();
    });
  };
  backups();
  // ---- selective sync
  const syncOut = async () => {
    const el = $("#sy-out"); if (!el) return;
    const o = await api("GET", "/api/sync/outside").catch(() => null);
    if (!o) { el.textContent = ""; return; }
    if (!o.active) { el.innerHTML = `<span class="muted">No filter: every game is synced.</span>`; return; }
    if (!o.games) { el.innerHTML = `<span class="muted">Every synced game in your Library is inside these.</span>`; return; }
    const un = o.games - o.analysed;
    el.innerHTML = `${o.games.toLocaleString()} synced game${o.games === 1 ? "" : "s"} in your Library fall outside (${o.analysed} analysed).
      ${un ? `<button class="sm" data-trim="0">Remove ${un.toLocaleString()} unanalysed</button>` : ""}
      ${o.analysed ? `<button class="sm ghost danger" data-trim="1">Remove all ${o.games.toLocaleString()}</button>` : ""}
      <div class="hint muted small">Removed games aren't remembered as deleted: widen the filters and Sync brings them back.</div>`;
    $$("[data-trim]", el).forEach(b => b.onclick = async () => {
      if (!b.dataset.armed) { b.dataset.armed = "1"; b.textContent = "Click again to remove"; return; }
      b.disabled = true;
      const r = await api("POST", "/api/sync/trim", { include_analysed: b.dataset.trim === "1" });
      toast(`Removed ${r.deleted.toLocaleString()} game${r.deleted === 1 ? "" : "s"}`);
      loadGames().catch(() => {}); syncOut();
    });
  };
  const saveSync = async patch => { await save(patch); syncOut(); };
  $("#sy-win").onchange = e => { $("#sy-since").hidden = e.target.value !== "since"; saveSync({ sync_window: e.target.value }); };
  $("#sy-since").onchange = e => saveSync({ sync_since: e.target.value });
  $$("[data-tc]", m).forEach(c => c.onchange = () => {
    const on = $$("[data-tc]", m).filter(x => x.checked).map(x => x.dataset.tc);
    if (!on.length) { c.checked = true; toast("Keep at least one time control", true); return; }
    saveSync({ sync_tcs: on.length === 5 ? [] : on });
  });
  const rate = v => (v === "" ? null : Math.max(0, Math.round(+v)));
  $("#sy-min").onchange = e => saveSync({ sync_opp_min: rate(e.target.value) });
  $("#sy-max").onchange = e => saveSync({ sync_opp_max: rate(e.target.value) });
  syncOut();
  api("GET", "/api/storage").then(st => {
    const mb = b => (b / 1e6).toFixed(b < 1e7 ? 1 : 0) + " MB";
    const el = $("#storage");
    if (el) el.innerHTML = `${mb(st.bytes)} for ${st.games.toLocaleString()} games (${st.analysed} analysed)${st.deleted ? ` · ${st.deleted.toLocaleString()} deleted games remembered, so Sync skips them` : ""}`;
  }).catch(() => {});
  if (S.settingsJump) { const el = document.getElementById(S.settingsJump); S.settingsJump = null; if (el) setTimeout(() => el.scrollIntoView({ block: "start" }), 0); }
  $$("[data-jump]", m).forEach(a => a.onclick = e => { e.preventDefault(); const el = document.getElementById(a.dataset.jump); if (el) el.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" }); });
};

// V11: Follow Palette - a switch and a setup check (Palette is a separate theme-switcher app)
async function paletteSettings() {
  const box = $("#pal-box"); if (!box) return;
  const on = !!S.settings.follow_palette;
  let st = PAL.s;
  if (!st) { try { st = await api("GET", "/api/palette"); } catch (e) { st = null; } }
  if (!$("#pal-box")) return;
  const rows = st ? [
    [st.installed, "Palette is installed", "Found its folder (~/.config/palette).", "Install Palette (a theme switcher for the whole desktop) and pick a theme once."],
    [st.active, "A theme is active", st.theme ? `Current theme: ${esc(st.theme)}.` : "Palette has picked a theme.", "Pick a theme in Palette."],
    [st.file, "Palette writes Chess Review's colours", "current/chess-review.json is there.", "This Palette doesn't know Chess Review yet: update it, then switch theme once."],
    [st.valid, "Its colours are valid", `${st.mode === "light" ? "Light" : "Dark"} theme with every colour the app needs.`, "The file isn't plain #rrggbb colours. Switch theme in Palette to rewrite it."],
  ] : [];
  box.innerHTML = `<label class="check" style="margin:0 0 4px"><input type="checkbox" id="pal-on" ${on ? "checked" : ""}> Follow Palette's theme</label>
    <div class="muted small" style="margin-bottom:8px">The app takes its colours from the theme you pick in Palette and changes with it. Move labels and the board keep their own colours. Picking one of the themes below stops following.</div>
    ${on && st?.valid ? `<div class="pal-now"><span class="pal-sw">${st.swatches.map(c => `<b style="background:${c}"></b>`).join("")}</span> Now: <b>${esc(st.theme)}</b>${st.accent_swapped ? ` <span class="muted small">(its red/orange/yellow accent is swapped so it doesn't look like a mistake label)</span>` : ""}</div>` : ""}
    ${on ? `<ul class="pal-checks">${rows.map(([ok, t, good, fix]) => `<li class="${ok ? "ok" : "bad"}"><span class="${ok ? "status-ok" : "status-no"}">${ok ? "✓" : "✕"}</span><div><b>${t}</b><div class="muted small">${ok ? good : fix}</div></div></li>`).join("")}</ul>` : ""}
    <div style="height:10px"></div>`;
  $("#pal-on").onchange = async e => {
    try { S.settings = await api("POST", "/api/settings", { follow_palette: e.target.checked }); } catch (err) { toast(err.message, true); return; }
    PAL.s = null; await paletteSync(); paletteSettings();
    toast(e.target.checked ? (PAL.s?.valid ? "Following Palette: " + PAL.s.theme : "Palette isn't ready yet: see the checks") : "Stopped following Palette");
  };
}
