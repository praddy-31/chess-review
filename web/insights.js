// Chess Review V6 - Insights: where your points go. Replaces the V2 Insights page
// (its tables live on under "More detail"). Uses helpers from app.js.
"use strict";

const IN = { tc: "all", days: 90, data: null, old: null };
const pctS = v => v == null ? "—" : `${v}%`;
const signed = v => v == null ? "" : `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.abs(v)}`;

VIEWS.insights = async function () {
  setTimeout(() => { const b = $("#in-week"); if (b) b.onclick = weeklyNote; }, 0);
  const m = $("#main");
  m.innerHTML = `<div class="page page-wide in-page"><div class="page-head"><h1>Where your points go</h1><span class="muted" id="in-sub"></span><span class="spacer"></span><button id="in-week">Weekly note</button></div>
    <div class="filters" id="in-filters"></div><div id="in-body"><div class="card muted">Working it out…</div></div></div>`;
  await inLoad();
};

async function inLoad() {
  try {
    [IN.data, IN.old] = await Promise.all([
      api("GET", `/api/profile?tc=${IN.tc}&days=${IN.days}`),
      api("GET", `/api/insights?tc=${IN.tc}`).catch(() => null)]);
  } catch (e) { $("#in-body").innerHTML = `<div class="card status-no">${esc(e.message)}</div>`; return; }
  inRender();
}

async function inRender() {
  const d = IN.data;
  if (S.view !== "insights" || !$("#in-body")) return;
  const tcs = d.tcs.filter(t => t && t !== "unknown");
  $("#in-filters").innerHTML = `<span class="muted small">Time control</span>${["all", ...tcs].map(t => `<span class="chip ${IN.tc === t ? "on" : ""}" data-itc="${t}">${t === "all" ? "All" : cap(t)}</span>`).join("")}
    <span class="sep"></span><span class="muted small">Period</span>${[[30, "Last 30 days"], [90, "Last 3 months"], [365, "Last year"]].map(([v, l]) => `<span class="chip ${IN.days === v ? "on" : ""}" data-idays="${v}">${l}</span>`).join("")}`;
  $$("[data-itc]").forEach(c => c.onclick = () => { IN.tc = c.dataset.itc; inLoad(); });
  $$("[data-idays]").forEach(c => c.onclick = () => { IN.days = +c.dataset.idays; inLoad(); });
  const cur = d.periods.current, prev = d.periods.previous;
  if (!cur.games && !prev.games && !(S.games || []).length && !(await api("GET", "/api/games").then(x => x.games.length).catch(() => 0))) {
    $("#in-sub").textContent = "";
    $("#in-filters").innerHTML = "";
    $("#in-body").innerHTML = `<div class="card empty"><h2>Nothing to measure yet</h2><p class="muted">Insights is built from your games: where your points go, your skills, tilt, clock and endgames. Sync your chess.com or Lichess games, or paste some, and analyse a few.</p><a class="btn" href="#/library">Open the Library</a></div>`;
    return;
  }
  $("#in-sub").textContent = `${cur.games.toLocaleString()} games in the last ${d.days} days, compared with the ${d.days} days before`;
  $("#in-body").innerHTML = `
    <div id="in-plan"></div>
    ${focusHtml(d)}
    ${d.analysed.needed ? `<div class="card in-cover row"><span><b>${d.analysed.period}</b> analysed game${d.analysed.period === 1 ? "" : "s"} in this period. The skill scores and endgames need about 30 to be steady; the rest of this page uses all your games.</span><span style="flex:1"></span>
      <button class="sm" data-ar="50">Analyse my last 50</button><button class="sm" data-ar="100">Last 100</button></div>` : ""}
    <div class="in-grid2">
      <div class="card">${skillsHtml(d)}</div>
      <div class="card">${periodHtml(d)}</div>
    </div>
    <div class="card">${ratingHtml(d)}</div>
    <div class="in-grid2">
      <div class="card">${tiltHtml(d)}</div>
      <div class="card">${sessionsHtml(d)}</div>
    </div>
    <div class="in-grid2">
      <div class="card">${endgameHtml(d)}</div>
      <div class="card">${clockHtml(d)}</div>
    </div>
    <div class="card" id="in-phase"><span class="muted small">Splitting your games into phases…</span></div>
    <div class="card" id="in-pat"><span class="muted small">Looking for mistakes you repeat…</span></div>
    <div class="card" id="in-study"></div>
    <div class="card" id="in-opp"></div>
    <details class="card in-more"><summary>More detail: by time control, accuracy per game, where errors cluster</summary><div id="in-old">${oldHtml(IN.old)}</div></details>`;
  api("GET", `/api/phases?tc=${IN.tc}&days=${IN.days}`).then(phaseCard).catch(e => { const el = $("#in-phase"); if (el) el.innerHTML = `<div class="ll-head"><span class="ll-title">By phase</span></div><span class="status-no small">${esc(e.message)}</span>`; });
  api("GET", "/api/patterns").then(patternsCard).catch(e => { const el = $("#in-pat"); if (el) el.innerHTML = `<div class="ll-head"><span class="ll-title">Mistakes you repeat</span></div><span class="status-no small">${esc(e.message)}</span>`; });
  api("GET", "/api/plan").then(p => { const el = $("#in-plan"); if (el) el.innerHTML = planCardHtml(p); bindJumpTo(el); }).catch(() => {});
  api("GET", "/api/opponents").then(x => { const el = $("#in-opp"); if (el) el.innerHTML = oppCardHtml(x.opponents); $$("#in-opp tr[data-opp]").forEach(tr => tr.onclick = () => (location.hash = `#/opponent/${encodeURIComponent(tr.dataset.opp)}`)); }).catch(() => {});
  api("GET", "/api/study/insights").then(x => {
    const el = $("#in-study"); if (!el) return;
    const rows = x.openings;
    el.innerHTML = `<div class="ll-head"><span class="ll-title">Openings you study</span><span class="muted small">recall = clean passes in the last 7 days</span></div>
      ${rows.length ? `<table class="moves"><thead><tr><th>Opening</th><th class="num">Lines</th><th class="num">Learned</th><th class="num">Recall, 7 days</th></tr></thead><tbody>
        ${rows.map(r => `<tr><td><span class="side ${r.color}"></span> ${esc(r.opening.replace(/^[A-E]\d\d\s/, ""))}</td><td class="num">${r.lines}</td><td class="num">${r.learned}</td>
          <td class="num">${r.recall_7d == null ? "—" : `${r.recall_7d}% <span class="muted small">of ${r.attempts_7d}</span>`}</td></tr>`).join("")}</tbody></table>`
        : `<span class="muted small">Study an opening under Openings and its progress shows here.</span>`}`;
  }).catch(() => {});
  $$("[data-ar]").forEach(b => b.onclick = async () => {
    b.disabled = true;
    const r = await api("POST", "/api/analyse-recent", { n: +b.dataset.ar, tc: IN.tc === "all" ? "" : IN.tc });
    toast(r.queued ? `${r.queued} games queued (about ${estMin(r.plies)} min at depth ${S.settings.depth}); the Library shows progress` : "Nothing left to analyse");
    pollJobs();
  });
  $$("[data-focus]").forEach(b => b.onclick = async () => {
    const s = d.suggestions[+b.dataset.focus];
    await api("POST", "/api/focus", { key: s.key, tc: IN.tc === "all" ? "" : IN.tc, color: s.color, line: s.line, line_name: s.line_name });
    toast("Focus set for this week"); inLoad();
  });
  if ($("#fo-clear")) $("#fo-clear").onclick = async () => { await api("POST", "/api/focus/clear"); inLoad(); };
  if ($("#fo-new")) $("#fo-new").onclick = async () => { await api("POST", "/api/focus/clear"); inLoad(); };
  $$("[data-opline]").forEach(a => a.onclick = () => { OP.color = a.dataset.color; OP.path = a.dataset.opline.split(",").map(uci => ({ uci })); location.hash = "#/openings"; });
  $$("rect[data-id]").forEach(r => r.onclick = () => (location.hash = `#/review/${encodeURIComponent(r.dataset.id)}`));
}

// ---------------------------------------------------------------- V10: by phase, and where errors land
const PH = { heat: "land", sq: null };
const PH_STYLE = { Opening: { v: "--accent", dash: "" }, Middlegame: { v: "--sev-great", dash: "7 5" }, Endgame: { v: "--ink-2", dash: "2 4" } };
function phaseCard(d) {
  const el = $("#in-phase"); if (!el) return;
  PH.d = d;
  const phases = ["Opening", "Middlegame", "Endgame"];
  const row = k => {
    const c = d.current[k], p = d.previous[k];
    const ch = c.accuracy != null && p.accuracy != null && p.moves >= 30 ? Math.round(c.accuracy - p.accuracy) : null;
    return `<tr><td><svg width="26" height="8" aria-hidden="true"><line x1="0" x2="26" y1="4" y2="4" stroke="${cssv(PH_STYLE[k].v)}" stroke-width="2.5" stroke-dasharray="${PH_STYLE[k].dash}"/></svg> ${k}</td>
      <td class="num">${c.accuracy != null ? `<b>${c.accuracy.toFixed(0)}%</b>` : "—"}${ch ? ` <span class="small ${ch < 0 ? "bad" : "ink2"}">${signed(ch)}</span>` : ""}</td>
      <td class="num">${c.lost_per_move != null ? c.lost_per_move.toFixed(1) : "—"}</td>
      <td class="num muted">${c.games}</td></tr>`;
  };
  const worst = phases.filter(k => d.current[k].moves >= 30).sort((a, b) => d.current[b].lost_per_move - d.current[a].lost_per_move)[0];
  el.innerHTML = `<div class="ll-head"><span class="ll-title">By phase</span><span class="muted small">your analysed games · the middlegame starts once pieces are developed or traded, the endgame at 6 or fewer pieces (not counting kings and pawns), as on Lichess</span></div>
    ${!d.games ? `<p class="muted small">No analysed games in this period.</p>` : `
    ${worst ? `<p class="ph-say">You lose the most per move in the <b>${worst.toLowerCase()}</b>: ${d.current[worst].lost_per_move.toFixed(1)} points of win chance a move, at ${d.current[worst].accuracy.toFixed(0)}% accuracy. ${d.reached_endgame} of ${d.games} games reached an endgame.</p>` : ""}
    <div class="in-grid2">
      <div>
        <table class="moves"><thead><tr><th>Phase</th><th class="num">Accuracy</th><th class="num" title="Average win-chance points your moves gave away">Points lost a move</th><th class="num">Games</th></tr></thead><tbody>${phases.map(row).join("")}</tbody></table>
        <div class="muted small" style="margin:4px 0 10px">Last ${d.days} days; the small number is the change from the ${d.days} days before. Book moves don't count.</div>
        ${phaseChart(d)}
      </div>
      <div id="ph-heat">${heatHtml(d.heat)}</div>
    </div>`}`;
  bindHeat(el);
}
function phaseChart(d) {
  let ser = d.series;
  const first = ser.findIndex(m => m.games);
  if (first < 0) return "";
  ser = ser.slice(first);
  const W = 520, H = 190, L = 40, R = 10, T = 10, B = 34, y0 = 50, y1 = 100;
  const step = (W - L - R) / ser.length, X = i => L + step * (i + 0.5), Y = v => T + (H - T - B) * (1 - (Math.max(y0, v) - y0) / (y1 - y0));
  let svg = "";
  for (let v = y0; v <= y1; v += 10) svg += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="${cssv("--grid")}"/><text x="${L - 6}" y="${Y(v) + 4}" font-size="11" text-anchor="end" fill="${cssv("--muted")}">${v}%</text>`;
  ser.forEach((m, i) => { svg += `<text x="${X(i)}" y="${H - 18}" font-size="11" text-anchor="middle" fill="${cssv("--muted")}">${new Date(m.month + "-15").toLocaleString("en", { month: "short" })}</text>
    <text x="${X(i)}" y="${H - 4}" font-size="9.5" text-anchor="middle" fill="${cssv("--muted")}">${m.games ? `${m.games} game${m.games === 1 ? "" : "s"}` : ""}</text>`; });
  for (const k of ["Opening", "Middlegame", "Endgame"]) {
    const st = PH_STYLE[k], col = cssv(st.v);
    const pts = ser.map((m, i) => [i, m[k]]).filter(([, x]) => x.accuracy != null && x.moves >= 8);
    if (pts.length > 1) svg += `<polyline fill="none" stroke="${col}" stroke-width="2.2" stroke-dasharray="${st.dash}" points="${pts.map(([i, x]) => `${X(i).toFixed(1)},${Y(x.accuracy).toFixed(1)}`).join(" ")}"/>`;
    svg += pts.map(([i, x]) => `<circle cx="${X(i)}" cy="${Y(x.accuracy)}" r="3.5" fill="${col}"><title>${new Date(ser[i].month + "-15").toLocaleString("en", { month: "long", year: "numeric" })} · ${k}: ${x.accuracy.toFixed(0)}% accuracy, ${x.lost_per_move.toFixed(1)} points lost a move, ${x.games} games</title></circle>`).join("");
  }
  return `<div class="muted small">Accuracy (up the side) by month (along the bottom, with how many games were analysed): higher is better; hover a dot for the numbers. A phase with fewer than 8 moves in a month is left out.</div>
    <svg viewBox="0 0 ${W} ${H}" class="ph-chart" role="img" aria-label="Accuracy per phase by month">${svg}</svg>`;
}
function heatHtml(h) {
  const counts = PH.heat === "land" ? h.land : h.lost, max = Math.max(1, ...counts);
  const S8 = 36, files = "abcdefgh";
  let svg = "";
  for (let r = 7; r >= 0; r--) for (let f = 0; f < 8; f++) {
    const sq = r * 8 + f, n = counts[sq], x = 16 + f * S8, y = (7 - r) * S8;
    const light = (r + f) % 2 === 1, a = n ? 0.18 + 0.82 * n / max : 0;
    svg += `<g data-sq="${sq}" style="cursor:${n ? "pointer" : "default"}"><rect x="${x}" y="${y}" width="${S8}" height="${S8}" style="fill:${light ? "var(--surface-2)" : "color-mix(in srgb, var(--surface-2) 55%, var(--surface))"}"/>
      ${n ? `<rect x="${x}" y="${y}" width="${S8}" height="${S8}" fill="${cssv("--sev-blunder")}" fill-opacity="${a.toFixed(2)}"/><text x="${x + S8 / 2}" y="${y + S8 / 2 + 4}" font-size="11.5" text-anchor="middle" fill="${a > 0.55 ? "#fff" : cssv("--ink")}">${n}</text>` : ""}
      ${PH.sq === sq ? `<rect x="${x + 1}" y="${y + 1}" width="${S8 - 2}" height="${S8 - 2}" fill="none" stroke="${cssv("--accent")}" stroke-width="2"/>` : ""}
      <title>${files[f]}${r + 1}: ${n} ${PH.heat === "land" ? `mistake${n === 1 ? "" : "s"} or blunder${n === 1 ? "" : "s"} played here` : `piece${n === 1 ? "" : "s"} lost here right after an error`}</title></g>`;
  }
  for (let i = 0; i < 8; i++) svg += `<text x="${16 + i * S8 + S8 / 2}" y="${8 * S8 + 13}" font-size="10.5" text-anchor="middle" fill="${cssv("--muted")}">${files[i]}</text><text x="7" y="${(7 - i) * S8 + S8 / 2 + 4}" font-size="10.5" text-anchor="middle" fill="${cssv("--muted")}">${i + 1}</text>`;
  const ex = PH.sq != null ? ((PH.heat === "land" ? h.examples_land : h.examples_lost)[PH.sq] || []) : [];
  return `<div class="row" role="radiogroup" aria-label="Heatmap" style="gap:6px;margin-bottom:6px">${[["land", "Where your errors land"], ["lost", "Where you lose pieces"]].map(([k, l]) => `<span class="chip ${PH.heat === k ? "on" : ""}" role="radio" tabindex="0" aria-checked="${PH.heat === k}" data-heat="${k}">${l}</span>`).join("")}</div>
    <div class="muted small">${PH.heat === "land" ? `The square each of your ${h.errors} mistakes and blunders moved to` : "The square of the piece your opponent took on the move right after your error"}, from your side of the board (your pieces start at the bottom), all your analysed games. The number on a square is how many; click it for the games.</div>
    <svg viewBox="0 0 ${16 + 8 * S8} ${8 * S8 + 18}" class="ph-heat" role="img" aria-label="Heatmap of your errors by square">${svg}</svg>
    ${ex.length ? `<div class="pat-ex">${ex.map(e => `<a data-hex="${esc(e.game_id)}|${e.ply}"><span class="b-${e.severity} ph-sev">${e.severity === "Blunder" ? "??" : "?"}</span> <b>${esc(e.move)}</b>${e.taken ? ` <span class="muted small">lost a ${esc(e.taken)}</span>` : ""} vs ${esc(e.opponent)} <span class="muted small">${esc(e.date)} · ${esc(e.phase.toLowerCase())}</span></a>`).join("")}</div>` : ""}`;
}
function bindHeat(root) {
  const box = $("#ph-heat", root); if (!box) return;
  $$("[data-heat]", box).forEach(c => c.onclick = () => { PH.heat = c.dataset.heat; PH.sq = null; box.innerHTML = heatHtml(PH.d.heat); bindHeat(root); });
  $$("g[data-sq]", box).forEach(g => g.onclick = () => { const sq = +g.dataset.sq; PH.sq = PH.sq === sq ? null : sq; box.innerHTML = heatHtml(PH.d.heat); bindHeat(root); });
  $$("[data-hex]", box).forEach(a => a.onclick = () => { const [id, ply] = a.dataset.hex.split("|"); S.reviewJump = { id, ply: +ply }; location.hash = `#/review/${encodeURIComponent(id)}`; });
}

// ---------------------------------------------------------------- focus
function focusHtml(d) {
  const f = d.focus.active;
  if (f) {
    const b = f.baseline?.value, n = f.now?.value;
    const better = n != null && b != null && (f.better === "lower" ? n < b : n > b);
    const unit = f.key === "tilt" ? " a week" : (f.key === "blunders" ? "" : "%");
    return `<div class="in-focus card">
      <div class="in-focus-head"><span class="ll-title">Focus this week</span><span class="muted small">day ${Math.min(f.days + 1, 7)} of 7${f.week_done ? " · done" : ""}</span><span style="flex:1"></span>
        ${f.week_done ? `<button class="sm primary" id="fo-new">Pick next week's focus</button>` : `<button class="sm ghost" id="fo-clear">Stop</button>`}</div>
      <b class="in-focus-title">${esc(f.title)}</b>
      <div class="in-focus-nums"><span><span class="muted small">Before (30 days)</span><b>${b ?? "—"}${b != null ? unit : ""}</b></span><span class="arrow">→</span>
        <span><span class="muted small">Since you started (${f.now?.games ?? 0} games)</span><b class="${n == null ? "" : better ? "good" : "bad"}">${n ?? "—"}${n != null ? unit : ""}</b></span>
        <span class="muted small">Measured: ${esc(f.how)}; ${f.better} is better.</span></div></div>`;
  }
  const sug = d.suggestions;
  const hist = d.focus.history || [];
  return `<div class="in-focus card">
    <div class="in-focus-head"><span class="ll-title">Pick a focus for this week</span><span class="muted small">your biggest leaks, from your games</span></div>
    ${sug.length ? `<div class="in-sugs">${sug.map((s, i) => `<div class="in-sug"><b>${esc(s.title)}</b><span class="ink2 small">${esc(s.why)}</span>
        <span class="muted small">Measured by ${esc(s.how)}.</span>
        <div class="row" style="gap:8px">${s.line ? `<a class="small" data-opline="${s.line.join(",")}" data-color="${s.color}">Open the line</a>` : ""}<span style="flex:1"></span><button class="sm primary" data-focus="${i}">Pick this</button></div></div>`).join("")}</div>`
      : `<p class="muted small">No clear leak stands out yet. Analyse more games or widen the period.</p>`}
    ${hist.length ? `<div class="muted small">Last focus: ${esc(FOCUS_TITLE(hist[hist.length - 1]))}: ${hist[hist.length - 1].baseline?.value ?? "—"} → ${hist[hist.length - 1].result?.value ?? "—"}</div>` : ""}
  </div>`;
}
const FOCUS_TITLE = h => ({ tilt: "Stop after two losses", sessions: "At most two games per session", time: "Keep a minute on the clock",
  converting: "Convert winning positions", blunders: "Blunder check", opening: "Fix an opening line" }[h.key] || h.key);

// ---------------------------------------------------------------- skills and periods
function skillsHtml(d) {
  const rows = Object.entries(d.skills).map(([k, v]) => {
    const thin = v.n < 5;
    const ch = v.change;
    return `<div class="in-skill ${thin ? "thin" : ""}">
      <b>${k}</b>
      <span class="in-sk-bar"><span class="in-track"><i style="width:${v.score ?? 0}%"></i></span><span class="muted small">${esc(v.why)} · ${v.n} game${v.n === 1 ? "" : "s"}</span></span>
      <b class="num">${v.score ?? "—"}</b>
      <span class="num small ${ch == null ? "muted" : ch > 0 ? "good" : ch < 0 ? "bad" : "muted"}">${ch == null ? (thin ? "few games" : "") : `${ch > 0 ? "▲" : ch < 0 ? "▼" : "="} ${Math.abs(ch)}`}</span></div>`;
  }).join("");
  return `<div class="ll-head"><span class="ll-title">Skill profile</span><span class="muted small">0 to 100 · change vs the ${d.days} days before</span></div>${rows}
    <div class="muted small" style="margin-top:6px">Opening, Tactics, Converting, Defending and Endgame come from analysed games; Time from every game with a clock. Faded rows rest on fewer than 5 games.</div>`;
}
function periodHtml(d) {
  const c = d.periods.current, p = d.periods.previous;
  const row = (label, a, b, fmt = x => x ?? "—", higher = true) => {
    const diff = a != null && b != null ? a - b : null;
    const cls = diff == null || diff === 0 || higher === null ? "muted" : (diff > 0) === higher ? "good" : "bad";
    return `<tr><td>${label}</td><td class="num"><b>${fmt(a)}</b></td><td class="num muted">${fmt(b)}</td><td class="num small ${cls}">${diff == null ? "" : signed(Math.round(diff * 100) / 100)}</td></tr>`;
  };
  const tcs = [...new Set([...Object.keys(c.ratings || {}), ...Object.keys(p.ratings || {})])];
  return `<div class="ll-head"><span class="ll-title">This period vs the one before</span><span class="muted small">last ${d.days} days · the ${d.days} before</span></div>
    <table class="moves in-cmp"><thead><tr><th></th><th class="num">Now</th><th class="num">Before</th><th class="num">Change</th></tr></thead><tbody>
    ${row("Games", c.games, p.games, x => x ?? "—", null)}
    ${row("Score", c.score, p.score, pctS)}
    ${row("Performance rating", c.perf, p.perf)}
    ${tcs.map(t => row(`${cap(t)} rating at the end`, c.ratings?.[t]?.end, p.ratings?.[t]?.end)).join("")}
    ${row("Average opponent", c.opp_avg, p.opp_avg)}
    ${row("Accuracy (analysed)", c.accuracy, p.accuracy)}
    ${row("Blunders per game (analysed)", c.blunders_pg, p.blunders_pg, x => x ?? "—", false)}
    ${row("Lost on time", c.lost_on_time, p.lost_on_time, pctS, false)}
    </tbody></table>
    <div class="muted small" style="margin-top:6px">Performance rating = average opponent + 400 × (wins − losses) ÷ games. ${c.analysed} and ${p.analysed} analysed games behind the accuracy rows.</div>`;
}

// ---------------------------------------------------------------- rating chart
function ratingHtml(d) {
  const ser = d.rating.series;
  const tcs = Object.keys(ser).filter(t => t !== "daily" && (IN.tc === "all" || t === IN.tc));
  if (!tcs.length) return `<div class="ll-head"><span class="ll-title">Rating</span></div><p class="muted small">No ratings in your games' headers.</p>`;
  const since = new Date(Date.now() - Math.max(IN.days, 180) * 864e5).toISOString().slice(0, 10);
  const pts = Object.fromEntries(tcs.map(t => [t, ser[t].filter(p => p.day >= since)]));
  const all = tcs.flatMap(t => pts[t]);
  if (!all.length) return `<div class="ll-head"><span class="ll-title">Rating</span></div><p class="muted small">No rated games in this period.</p>`;
  const days = all.map(p => +new Date(p.day));
  const x0 = Math.min(...days), x1 = Math.max(...days, x0 + 864e5);
  const ys = all.map(p => p.elo);
  const y0 = Math.floor((Math.min(...ys) - 30) / 50) * 50, y1 = Math.ceil((Math.max(...ys) + 30) / 50) * 50;
  const W = 1000, H = 200, L = 44, R = 10, T = 10, B = 24;
  const X = t => L + (W - L - R) * (t - x0) / (x1 - x0), Y = v => T + (H - T - B) * (1 - (v - y0) / (y1 - y0));
  const COLS = { blitz: cssv("--accent"), rapid: cssv("--sev-best"), bullet: cssv("--sev-mistake"), classical: cssv("--sev-great") };
  let svg = "";
  for (let v = y0; v <= y1; v += 50) svg += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="${cssv("--grid")}" stroke-width="1"/><text x="${L - 6}" y="${Y(v) + 4}" font-size="11" text-anchor="end" fill="${cssv("--muted")}">${v}</text>`;
  const months = [];
  for (let t = new Date(x0); t <= x1; t = new Date(t.getFullYear(), t.getMonth() + 1, 1)) months.push(new Date(t.getFullYear(), t.getMonth(), 1));
  months.slice(1).forEach(mo => { const x = X(+mo); svg += `<text x="${x}" y="${H - 6}" font-size="11" text-anchor="middle" fill="${cssv("--muted")}">${mo.toLocaleString("en", { month: "short" })}</text>`; });
  for (const t of tcs) {
    const p = pts[t];
    if (!p.length) continue;
    svg += `<polyline fill="none" stroke="${COLS[t] || cssv("--ink-2")}" stroke-width="2" points="${p.map(q => `${X(+new Date(q.day)).toFixed(1)},${Y(q.elo).toFixed(1)}`).join(" ")}"/>`;
    const last = p[p.length - 1];
    svg += `<circle cx="${X(+new Date(last.day))}" cy="${Y(last.elo)}" r="3.5" fill="${COLS[t] || cssv("--ink-2")}"/>`;
  }
  const perf = d.rating.perf.filter(q => tcs.includes(q.tc) && q.month + "-15" >= since && q.games >= 10);
  for (const q of perf) {
    const x = X(+new Date(q.month + "-15")), y = Y(Math.max(y0, Math.min(y1, q.perf)));
    svg += `<rect x="${x - 4}" y="${y - 4}" width="8" height="8" fill="none" stroke="${COLS[q.tc] || cssv("--ink-2")}" stroke-width="1.6"><title>${cap(q.tc)} performance ${q.month}: ${q.perf} over ${q.games} games</title></rect>`;
  }
  const legend = tcs.map(t => `<span class="in-leg"><i style="background:${COLS[t] || cssv("--ink-2")}"></i>${cap(t)} ${pts[t].length ? pts[t][pts[t].length - 1].elo : ""}</span>`).join("");
  return `<div class="ll-head"><span class="ll-title">Rating</span><span class="muted small">from your games · squares = monthly performance rating</span><span style="flex:1"></span>${legend}</div>
    <svg viewBox="0 0 ${W} ${H}" class="in-chart" role="img" aria-label="Rating over time">${svg}</svg>`;
}

// ---------------------------------------------------------------- habits
function barRows(rows, overall) {
  const max = 80;
  return rows.map(r => `<div class="in-bar ${r.hi ? "hi" : ""}"><span>${r.label}</span>
      <span class="in-btrack">${r.score != null ? `<i style="width:${100 * r.score / max}%"></i>` : ""}${overall != null ? `<em style="left:${100 * overall / max}%"></em>` : ""}</span>
      <span class="num"><b>${pctS(r.score)}</b> <span class="muted small">${r.n}</span></span></div>`).join("");
}
function tiltHtml(d) {
  const t = d.tilt;
  const rows = [{ label: "After a win", ...t.after_win }, { label: "After a loss", ...t.after_loss },
    { label: "After two losses", ...t.after_2loss, hi: t.after_2loss.score != null && t.overall != null && t.after_2loss.score <= t.overall - 5 }];
  return `<div class="ll-head"><span class="ll-title">Tilt</span><span class="muted small">your score in the next game, started within 15 minutes</span></div>
    ${barRows(rows, t.overall)}
    <div class="muted small" style="margin-top:6px">Score: wins count 1 and draws ½, as a share of the games (50% = as many wins as losses). The line marks your ${t.overall}% overall; small numbers are how many games. ${d.tilt_scope === "all" ? "All your games (the period has too few streaks)." : `Last ${d.days} days.`}</div>`;
}
function sessionsHtml(d) {
  const s = d.sessions, ov = d.tilt.overall;
  const rows = s.rows.map(r => ({ label: `Game ${r.game}${r.game === 5 ? "+" : ""} of a session`, score: r.score, n: r.n, hi: r.score != null && ov != null && r.n >= 20 && r.score <= ov - 4 }));
  return `<div class="ll-head"><span class="ll-title">Long sessions</span><span class="muted small">games less than 20 minutes apart</span></div>
    ${barRows(rows, ov)}<div class="muted small" style="margin-top:6px">Your score in that game (wins 1, draws ½); the line is your overall score. ${s.share_3plus}% of your games are the 3rd or later in a session.</div>`;
}
function endgameHtml(d) {
  const e = d.endgames;
  return `<div class="ll-head"><span class="ll-title">Endgames</span><span class="muted small">from analysed games</span></div>
    ${e.length ? `<table class="moves"><thead><tr><th>Type</th><th class="num">Games</th><th class="num">Converted</th><th class="num">Saved</th></tr></thead><tbody>
      ${e.map(r => `<tr><td>${r.type}</td><td class="num">${r.games}</td><td class="num">${r.ahead ? `<b class="${r.converted_pct < 65 ? "bad" : ""}">${r.converted_pct}%</b> <span class="muted small">of ${r.ahead}</span>` : "—"}</td><td class="num">${r.behind ? `<b>${r.saved_pct}%</b> <span class="muted small">of ${r.behind}</span>` : "—"}</td></tr>`).join("")}
      </tbody></table>` : `<p class="muted small">None of your analysed games in this period reached an endgame.</p>`}
    <div class="muted small" style="margin-top:6px">Converted: +2 or better entering the endgame and won. Saved: −2 or worse and drew or won.</div>`;
}
function clockHtml(d) {
  const c = d.clock;
  if (!c) return `<div class="ll-head"><span class="ll-title">Clock</span></div><p class="muted small">Too few games with clock times.</p>`;
  const mmss = s => s == null ? "—" : `${s < 0 ? "−" : "+"}${Math.floor(Math.abs(s) / 60)}:${String(Math.round(Math.abs(s) % 60)).padStart(2, "0")}`;
  return `<div class="ll-head"><span class="ll-title">Clock</span><span class="muted small">${d.clock_scope === "all" ? "all your games" : `last ${d.days} days`} · ${c.games} with clock times</span></div>
    <div class="in-stats">
      <div><span class="muted small">At move 30</span><b>${mmss(c.at_move30)}</b><span class="small ink2">vs your opponent (median)</span></div>
      <div><span class="muted small">Lost on time</span><b>${pctS(c.lost_on_time)}</b><span class="small ink2">of games · you flag them in ${pctS(c.won_on_time)}</span></div>
      <div><span class="muted small">Time trouble</span><b>${pctS(c.trouble_share)}</b><span class="small ink2">of games under 10% of your clock · score ${pctS(c.score_trouble)} vs ${pctS(c.score_calm)} calm</span></div>
    </div>`;
}

// ---------------------------------------------------------------- the V2 detail, kept
function oldHtml(d) {
  if (!d || !d.n_games) return `<p class="muted small">Analyse a few games for these.</p>`;
  const bars = (title, rows) => {
    const max = Math.max(1, ...rows.map(r => r.rate || 0));
    return `<div><h3>${title}</h3><div class="bars">${rows.filter(r => r.moves).map(r => `<div class="r"><span>${r.key}</span><span class="t"><i style="width:${100 * (r.rate || 0) / max}%"></i></span><span class="n">${r.rate}% <span class="muted">of ${r.moves}</span></span></div>`).join("")}</div></div>`;
  };
  const gs = d.games, W = Math.max(gs.length * 26 + 8, 1000), H = 140;
  const trend = `<svg viewBox="0 0 ${W} ${H + 18}" style="width:100%;height:150px" preserveAspectRatio="none">
    ${gs.map((g, i) => `<rect x="${i * 26 + 4}" y="${H - g.accuracy / 100 * H}" width="18" height="${g.accuracy / 100 * H}" rx="3" fill="${g.outcome === "win" ? cssv("--good") : g.outcome === "loss" ? cssv("--critical") : cssv("--muted")}" style="cursor:pointer" data-id="${esc(g.id)}"><title>${esc(g.played_at.slice(0, 10))} vs ${esc(g.opponent || "?")}: ${g.accuracy}%</title></rect>`).join("")}</svg>`;
  return `${d.by_tc.length > 1 ? `<h3>By time control (analysed games)</h3><table class="moves wraph"><thead><tr><th>Time control</th><th class="num">Games</th><th class="num">Score</th><th class="num">Accuracy</th><th class="num">Blunders / game</th><th class="num">Mistakes / game</th><th class="num">Moves flagged</th></tr></thead><tbody>
      ${d.by_tc.map(r => `<tr><td><b>${cap(r.tc)}</b></td><td class="num">${r.games}</td><td class="num">${r.score}%</td><td class="num">${r.accuracy ?? "—"}</td><td class="num">${r.blunders_pg}</td><td class="num">${r.mistakes_pg}</td><td class="num">${r.flag_rate}%</td></tr>`).join("")}</tbody></table>` : ""}
    <h3>Accuracy per analysed game</h3><div class="muted small">Oldest to newest; green won, red lost. Click a bar to open the game.</div>${trend}
    <div class="in-grid3">${bars("By position", d.by_standing)}${bars("By initiative", d.by_phase.map(r => ({ ...r, key: INITIATIVE[r.key] || r.key })))}${bars("By type", d.by_type)}</div>`;
}


// ------------------------------------------------------------------ V7: mistakes you repeat
function patternsCard(d) {
  const el = $("#in-pat"); if (!el) return;
  const ps = d.patterns || [];
  const trend = p => p.trend === "better" ? `<span class="good small">fewer lately</span>` : p.trend === "worse" ? `<span class="bad small">more lately</span>` : p.trend === "same" ? `<span class="muted small">no change lately</span>` : "";
  el.innerHTML = `<div class="ll-head"><span class="ll-title">Mistakes you repeat</span><span class="muted small">from ${d.analysed} analysed game${d.analysed === 1 ? "" : "s"}; lately = last 30 days</span></div>
    ${ps.length ? `<div class="pat-grid">${ps.map((p, i) => `<div class="pat">
        <div class="pat-head"><b>${esc(p.title)}</b>${trend(p)}</div>
        <div class="small muted">${p.n} time${p.n === 1 ? "" : "s"} in ${p.games} game${p.games === 1 ? "" : "s"} · ${p.per10} per 10 games${p.recent_per10 != null && p.before_per10 != null ? ` (lately ${p.recent_per10}, before ${p.before_per10})` : ""} · about ${p.cost} points each${p.detail ? ` · most often: ${esc(p.detail)}` : ""}</div>
        <div class="pat-ex">${p.examples.slice(0, 3).map(e => `<a data-pex="${esc(e.game_id)}|${e.ply}" title="${esc(e.verdict || "")}"><b>${esc(e.move)}</b> vs ${esc(e.opponent || "?")} <span class="muted small">${esc(e.date)}</span></a>`).join("")}</div>
        <div class="row" style="gap:8px">${p.puzzles.length ? `<button class="sm primary" data-pat="${i}">Practise these · ${p.puzzles.length}</button>` : `<span class="muted small">No puzzles from these yet</span>`}</div>
      </div>`).join("")}</div>` : `<span class="muted small">${d.analysed < 10 ? "Analyse a few more games (about 10) and the patterns show up here." : "Nothing repeats three times or more. Nice."}</span>`}`;
  $$("[data-pex]", el).forEach(a => a.onclick = () => { const [id, ply] = a.dataset.pex.split("|"); S.reviewJump = { id, ply: +ply }; location.hash = `#/review/${encodeURIComponent(id)}`; });
  $$("[data-pat]", el).forEach(b => b.onclick = () => { const p = ps[+b.dataset.pat]; S.pzSet = { ids: p.puzzles, title: p.title }; location.hash = "#/puzzles"; });
}

// ------------------------------------------------------------------ V7: the weekly note (copy into Obsidian)
async function weeklyNote() {
  const bg = document.createElement("div");
  bg.className = "modal-bg";
  bg.innerHTML = `<div class="modal" role="dialog" aria-label="Weekly note" style="max-width:720px">
    <div class="row" style="gap:10px"><h2 style="margin:0">Weekly note</h2><span class="seg" role="group" aria-label="Week"><button class="seg-b on" data-wk="0">This week</button><button class="seg-b" data-wk="-1">Last week</button><button class="seg-b" data-wk="-2">2 weeks ago</button></span><span style="flex:1"></span><button class="ghost sm" id="wk-close" aria-label="Close">✕</button></div>
    <p class="muted small">Markdown for your Obsidian vault. Copy it and paste it into a note; the app never writes into your vault.</p>
    <textarea id="wk-md" class="mono small" rows="16" style="width:100%;box-sizing:border-box" readonly>Loading…</textarea>
    <div class="row" style="gap:8px;margin-top:8px"><button class="primary" id="wk-copy">Copy</button><span class="muted small" id="wk-info"></span></div></div>`;
  document.body.appendChild(bg);
  const close = () => { bg.remove(); document.removeEventListener("keydown", onKey, true); };
  const onKey = e => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey, true);
  bg.addEventListener("mousedown", e => { if (e.target === bg) close(); });
  $("#wk-close", bg).onclick = close;
  const load = async off => {
    $$("[data-wk]", bg).forEach(b => b.classList.toggle("on", +b.dataset.wk === off));
    try { const w = await api("GET", "/api/weekly?offset=" + off); $("#wk-md", bg).value = w.markdown; $("#wk-info", bg).textContent = `${w.span} · ${w.games} game${w.games === 1 ? "" : "s"}`; }
    catch (e) { $("#wk-md", bg).value = e.message; }
  };
  $$("[data-wk]", bg).forEach(b => b.onclick = () => load(+b.dataset.wk));
  $("#wk-copy", bg).onclick = () => copyText($("#wk-md", bg).value);
  load(0);
}

// ================================================================== V8: weekly study plan
function planPartsHtml(p) {
  return p.parts.map(x => {
    const pct = Math.min(100, Math.round(100 * x.done / Math.max(1, x.count)));
    return `<a class="pl-part ${x.left ? "" : "done"}" href="${x.link}" title="About ${x.minutes} min this week">
      <span class="pl-lab">${esc(x.label)}</span><span class="pl-bar"><i style="width:${pct}%"></i></span>
      <span class="small"><b>${Math.min(x.done, x.count)}</b> of ${x.count} ${x.unit}${x.count === 1 ? "" : "s"}${x.left ? "" : " ✓"}</span></a>`;
  }).join("");
}
function planCardHtml(p) {
  if (!p || !p.enabled) return "";
  const h = m => m >= 60 ? `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ""}` : `${m} min`;
  return `<div class="card pl-card">
    <div class="ll-head"><span class="ll-title">This week's plan</span><span class="muted small">${h(p.done)} of ${h(p.minutes)}${p.reasons.length ? ` · ${esc(p.reasons.join("; "))}` : ""}</span><span style="flex:1"></span><a class="small" href="#/settings" data-jumpto="set-plan">Change</a></div>
    <div class="pl-parts">${planPartsHtml(p)}</div>
    ${p.next ? `<div class="row" style="gap:8px;margin-top:8px"><span class="small">Next: <b>${esc(p.next.label)}, ${p.next.count} ${esc(UNIT_PL(p.next, p.parts))}</b> today keeps you on track.</span><a class="btn sm primary" href="${p.next.link}">Start</a></div>`
      : `<div class="small status-ok" style="margin-top:8px">Done for the week. Anything more is a bonus.</div>`}
  </div>`;
}
// the compact strip above the Library
async function planStrip(el) {
  if (!el) return;
  const p = await api("GET", "/api/plan").catch(() => null);
  if (!p || !p.enabled || S.view !== "library") { el.innerHTML = ""; return; }
  const left = p.parts.filter(x => x.left);
  el.innerHTML = `<div class="card pl-strip row"><span class="small"><b>This week</b> ${p.parts.map(x => `<a href="${x.link}" class="pl-chip ${x.left ? "" : "done"}">${esc(x.label)} ${Math.min(x.done, x.count)}/${x.count}</a>`).join("")}</span>
    <span style="flex:1"></span>${p.next ? `<a class="btn sm" href="${p.next.link}">Next: ${esc(p.next.label.toLowerCase())}, ${p.next.count} ${esc(UNIT_PL(p.next, left))}</a>` : `<span class="small status-ok">Plan done ✓</span>`}</div>`;
}
const UNIT_PL = (n, parts) => { const x = parts.find(q => q.key === n.key); return x ? `${x.unit}${n.count === 1 ? "" : "s"}` : n.label.toLowerCase(); };

// asked once: on the first start after the update, or when the welcome was skipped
function planPrompt() {
  if ($(".modal-bg.pl-ask")) return;
  const bg = document.createElement("div");
  bg.className = "modal-bg pl-ask";
  bg.innerHTML = `<div class="modal" role="dialog" aria-label="Weekly study plan" style="max-width:520px">
    <h2 style="margin-top:0">A weekly study plan?</h2>
    <p class="muted small">Tell the app how much time you want to train each week. It splits that across puzzles, opening study, convert drills and reviewing your games, leans toward your weekly focus, and shows what to do next. You can change it or switch it off in Settings.</p>
    <div class="pl-pick">${[[60, "1 hour"], [120, "2 hours"], [240, "4 hours"]].map(([v, l]) => `<button data-plv="${v}">${l}</button>`).join("")}
      <span class="row" style="gap:6px"><input type="number" id="pl-ask-n" min="15" max="3000" step="15" placeholder="minutes" style="width:90px"><button id="pl-ask-c">Set</button></span></div>
    <div class="row" style="margin-top:12px"><button class="ghost" id="pl-no">No plan</button><span style="flex:1"></span><a class="small" id="pl-later">Ask me later</a></div></div>`;
  document.body.appendChild(bg);
  const close = () => bg.remove();
  const set = async v => {
    try { S.settings = await api("POST", "/api/settings", { plan_minutes: v }); } catch (e) { toast(e.message, true); return; }
    close();
    toast(v ? "Plan set. It's on Insights and above the Library." : "No plan. You can turn it on in Settings.");
    if (S.view === "library") planStrip($("#lib-plan"));
    if (S.view === "insights") VIEWS.insights();
  };
  $$("[data-plv]", bg).forEach(b => b.onclick = () => set(+b.dataset.plv));
  $("#pl-ask-c", bg).onclick = () => { const v = Math.round(+$("#pl-ask-n", bg).value || 0); if (v >= 15) set(v); else toast("At least 15 minutes", true); };
  $("#pl-no", bg).onclick = () => set(0);
  $("#pl-later", bg).onclick = close;
  bg.addEventListener("keydown", e => { if (e.key === "Escape") close(); });
}

// ================================================================== V8: opponents you meet again
function oppCardHtml(list) {
  return `<div class="ll-head"><span class="ll-title">Opponents you meet again</span><span class="muted small">2+ games</span></div>
    ${list.length ? `<table class="moves"><thead><tr><th>Opponent</th><th class="num">Games</th><th class="num">W / D / L</th><th class="num">Score</th><th>Last</th></tr></thead><tbody>
      ${list.slice(0, 8).map(o => `<tr class="click" data-opp="${esc(o.name)}"><td><a href="#/opponent/${encodeURIComponent(o.name)}"><b>${esc(o.name)}</b></a>${o.elo ? ` <span class="muted">(${o.elo})</span>` : ""}</td><td class="num">${o.games}</td><td class="num">${o.w} / ${o.d} / ${o.l}</td><td class="num">${o.score}%</td><td class="muted small">${esc(o.last)}</td></tr>`).join("")}</tbody></table>`
      : `<span class="muted small">Nobody yet: players you meet twice or more show up here, with what they play against you.</span>`}`;
}

VIEWS.opponent = async function (name) {
  const m = $("#main");
  if (!name) { location.hash = "#/insights"; return; }
  m.innerHTML = `<div class="page page-wide"><div class="card muted">Loading…</div></div>`;
  let o;
  try { o = await api("GET", `/api/opponents/${encodeURIComponent(name)}`); }
  catch (e) { m.innerHTML = `<div class="page"><div class="crumb"><a href="#/insights">Insights</a> / opponent</div><div class="card status-no">${esc(e.message)}</div></div>`; return; }
  const rec = r => r.games ? `${r.w} won · ${r.d} drawn · ${r.l} lost <span class="muted">(${r.score}%)</span>` : `<span class="muted">no games</span>`;
  const firstRows = (rows, side) => rows.length ? rows.map(r => `<div class="op-first"><div class="row" style="gap:8px"><b class="mono">${side === "White" ? "1." : "1…"}${esc(r.move)}</b><span class="small">${r.games} game${r.games === 1 ? "" : "s"}, you scored ${r.score}%</span></div>
      ${r.openings.filter(x => x.opening !== "?").map(x => `<div class="small ink2 op-sub">${esc(x.opening)} <span class="muted">· ${x.games} · ${x.score}%</span></div>`).join("")}</div>`).join("")
    : `<span class="muted small">No games where they had ${side}.</span>`;
  const elo = o.ratings.length ? o.ratings[o.ratings.length - 1].elo : null;
  m.innerHTML = `<div class="page page-wide op-page">
    <div class="page-head"><div><div class="crumb"><a href="#/insights">Insights</a> / opponent</div><h1>${esc(o.name)}${elo ? ` <span class="muted" style="font-weight:400">${elo}</span>` : ""}</h1>
      <div class="small ink2">${o.total.games} games since ${esc(o.first || "?")} · ${rec(o.total)}</div></div></div>
    ${o.tips.length ? `<div class="card op-tips"><div class="ll-head"><span class="ll-title">Before you play them</span></div><ul>${o.tips.map(t => `<li>${esc(t)}</li>`).join("")}</ul></div>` : ""}
    <div class="in-grid2">
      <div class="card"><div class="ll-head"><span class="ll-title"><span class="side White"></span> You with White</span></div><div class="small">${rec(o.as_white)}</div>
        <div class="muted small" style="margin:8px 0 4px">Their reply</div>${firstRows(o.their_black, "Black")}</div>
      <div class="card"><div class="ll-head"><span class="ll-title"><span class="side Black"></span> You with Black</span></div><div class="small">${rec(o.as_black)}</div>
        <div class="muted small" style="margin:8px 0 4px">Their first move</div>${firstRows(o.their_white, "White")}</div>
    </div>
    <div class="in-grid2">
      <div class="card"><div class="ll-head"><span class="ll-title">Your openings against them</span></div>
        ${o.worked.length ? `<table class="moves"><thead><tr><th>Opening</th><th class="num">Games</th><th class="num">Score</th></tr></thead><tbody>${o.worked.map(w => `<tr><td><span class="side ${w.color}"></span> ${esc(w.opening)}</td><td class="num">${w.games}</td><td class="num">${w.score}%</td></tr>`).join("")}</tbody></table>`
          : `<span class="muted small">No opening repeated yet.</span>`}</div>
      <div class="card"><div class="ll-head"><span class="ll-title">Accuracy</span><span class="muted small">${o.accuracy.games} analysed game${o.accuracy.games === 1 ? "" : "s"}</span></div>
        ${o.accuracy.games ? `<div class="op-acc"><div><span class="muted small">You</span><b>${o.accuracy.you ?? "—"}</b></div><div><span class="muted small">Them</span><b class="ink2">${o.accuracy.them ?? "—"}</b></div><div><span class="muted small">Your blunders a game</span><b>${o.accuracy.your_blunders ?? "—"}</b></div></div>`
          : `<span class="muted small">Analyse games against them to compare accuracy.</span>`}</div>
    </div>
    <div class="card fitwrap"><div class="ll-head"><span class="ll-title">Games</span></div>
      <table class="list fit"><thead><tr><th class="c-date">Date</th><th class="c-res">Side</th><th class="c-res">Result</th><th class="c-tc">Time</th><th class="c-op">Opening</th><th class="num c-acc">Accuracy</th></tr></thead><tbody>
      ${o.games.map(g => `<tr class="click" data-id="${esc(g.id)}"><td class="muted">${esc(g.date)}</td><td><span class="side ${g.me}"></span></td><td><span class="res ${g.outcome}">${cap(g.outcome)}</span></td><td class="muted c-tc">${esc(cap(g.tc || ""))}</td><td class="muted c-op" title="${esc(g.opening || "")}">${esc(g.opening || "")}</td><td class="num">${g.accuracy != null ? `<b>${g.accuracy.toFixed(1)}</b>` : `<span class="muted">—</span>`}</td></tr>`).join("")}</tbody></table></div>
  </div>`;
  $$("tr[data-id]", m).forEach(tr => tr.onclick = () => (location.hash = `#/review/${encodeURIComponent(tr.dataset.id)}`));
};

// "Change" links that open Settings at a section
function bindJumpTo(el) {
  $$("[data-jumpto]", el).forEach(a => a.onclick = e => { e.preventDefault(); S.settingsJump = a.dataset.jumpto; location.hash = "#/settings"; });
}
