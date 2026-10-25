// Chess Review - start-up, loaded last so every screen's script is in place first.

(async function start() {
  try {
    [S.settings, S.status] = await Promise.all([api("GET", "/api/settings"), api("GET", "/api/status")]);
  } catch (e) {
    $("#main").innerHTML = `<div class="page"><div class="card"><h2>Can't reach the engine</h2><p class="muted">${esc(e.message)}. Quit and reopen the app.</p></div></div>`;
    return;
  }
  applyLook();
  if (S.settings.follow_palette) paletteSync();
  applyCollapsed();
  $("#nav-toggle").onclick = toggleSidebar;
  updateBadge();
  if (typeof refreshPuzzleBadge === "function") refreshPuzzleBadge();
  const fresh = !location.hash || location.hash === "#/library" || /^#[A-Za-z0-9_\-]{8,}$/.test(location.hash);   // the token the shell opens with
  if (fresh) {
    const w = await api("GET", "/api/welcome").catch(() => null);
    if (w && !w.done && !w.users && !w.games) location.hash = "#/welcome";
    else if (!S.status.setup_done && !S.status.engines.stockfish) location.hash = "#/setup";
  }
  await route();
  // V8: ask once for a weekly study plan (people who skipped the welcome, or upgraded from V7)
  if (S.settings.plan_minutes == null && S.view !== "welcome" && typeof planPrompt === "function") setTimeout(planPrompt, 600);
})();
