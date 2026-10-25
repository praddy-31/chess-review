// Board drawing and moving. Positions come from Python as FENs; legal moves
// come from the engine process (/api/position), never from JS rules.
//
//   board.draw({fen, lastUci, arrows, flipped, selected, dots, marks, animate})
//   board.setMoves(legalMoves, onMove)  - make the board playable: click a piece
//       then a square, or drag it. Legal targets show as dots. onMove(uci) gets
//       the move (a promotion asks which piece). setMoves(null) turns it off.
//   board.onSquare = fn(square)          - raw square clicks (kept for callers that want them)
(function () {
  const FILES = "abcdefgh";
  const KIND = { p: "P", n: "N", b: "B", r: "R", q: "Q", k: "K" };
  const reduced = () => window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const SLIDE_MS = 120;

  class Board {
    constructor(svg) {
      this.svg = svg;
      this.flipped = false;
      this.pieces = "cburnett";
      this.onSquare = null;
      this.moves = null;          // legal moves when playable
      this.onMove = null;
      this.sel = null;
      this.state = null;          // last draw() arguments
      this.drag = null;
      this.promo = null;
      svg.setAttribute("viewBox", "0 0 8 8");
      svg.innerHTML = `<g class="sq"></g><g class="hl"></g><g class="mk"></g><g class="pc"></g><g class="dots"></g><g class="ar"></g><g class="dg"></g><g class="pr"></g>`;
      this.g = Object.fromEntries(["sq", "hl", "mk", "pc", "dots", "ar", "dg", "pr"].map(k => [k, svg.querySelector("." + k)]));
      svg.addEventListener("pointerdown", e => this._down(e));
      svg.addEventListener("pointermove", e => this._move(e));
      svg.addEventListener("pointerup", e => this._up(e));
      svg.addEventListener("pointercancel", () => this._cancelDrag());
      svg.addEventListener("contextmenu", e => { if (this.moves) e.preventDefault(); });
    }

    // ---- geometry
    xy(sq) {
      const f = FILES.indexOf(sq[0]), r = parseInt(sq[1], 10) - 1;
      return this.flipped ? [7 - f, r] : [f, 7 - r];
    }
    _pt(e) {
      const r = this.svg.getBoundingClientRect();
      return [(e.clientX - r.left) / r.width * 8, (e.clientY - r.top) / r.height * 8];
    }
    _sqAt(x, y) {
      x = Math.floor(x); y = Math.floor(y);
      if (x < 0 || x > 7 || y < 0 || y > 7) return null;
      const f = this.flipped ? 7 - x : x, rank = this.flipped ? y : 7 - y;
      return FILES[f] + (rank + 1);
    }
    pieceAt(sq) {
      if (!this.state) return null;
      const rows = this.state.fen.split(" ")[0].split("/");
      const ri = 8 - parseInt(sq[1], 10), fi = FILES.indexOf(sq[0]);
      let f = 0;
      for (const ch of rows[ri]) {
        if (/\d/.test(ch)) { f += +ch; continue; }
        if (f === fi) return ch;
        f++;
      }
      return null;
    }

    // ---- playing
    setMoves(moves, onMove) {
      this.moves = moves && moves.length ? moves : null;
      this.onMove = onMove || null;
      if (!this.moves) this.sel = null;
      this.svg.classList.toggle("playable", !!this.moves);
      this._overlay();
    }
    _from(sq) { return this.moves ? this.moves.filter(m => m.from === sq) : []; }
    _try(from, to) {
      const ms = this.moves ? this.moves.filter(m => m.from === from && m.to === to) : [];
      if (!ms.length) return false;
      this.sel = null;
      if (ms.length > 1 || ms[0].promotion) { this._askPromo(from, to, ms); return true; }
      this._overlay();
      if (this.onMove) this.onMove(ms[0].uci, ms[0]);
      return true;
    }
    _askPromo(from, to, ms) {
      const white = to[1] === "8";
      const [x, y0] = this.xy(to);
      const down = (y0 === 0);
      const kinds = ["q", "n", "r", "b"];
      let s = `<rect x="0" y="0" width="8" height="8" fill="rgba(0,0,0,.35)" data-cancel="1"/>`;
      kinds.forEach((k, i) => {
        const y = down ? y0 + i : y0 - i;
        s += `<rect x="${x}" y="${y}" width="1" height="1" fill="var(--surface, #fff)" stroke="var(--border,#888)" stroke-width="0.02" data-k="${k}"/>
              <image href="pieces/${this.pieces}/${white ? "w" : "b"}${KIND[k]}.svg" x="${x + .05}" y="${y + .05}" width=".9" height=".9" data-k="${k}"/>`;
      });
      this.g.pr.innerHTML = s;
      this.promo = { from, to, ms };
    }
    _pickPromo(k) {
      const p = this.promo; this.promo = null; this.g.pr.innerHTML = "";
      if (!k) { this._overlay(); return; }
      const m = p.ms.find(x => x.uci.endsWith(k)) || p.ms[0];
      if (this.onMove) this.onMove(m.uci, m);
    }

    _down(e) {
      if (e.button !== undefined && e.button !== 0) return;
      const [x, y] = this._pt(e);
      if (this.promo) {
        const k = e.target.getAttribute && e.target.getAttribute("data-k");
        this._pickPromo(k || null);
        return;
      }
      const sq = this._sqAt(x, y);
      if (!sq) return;
      if (this.onSquare && !this.moves) { this.onSquare(sq); return; }
      if (!this.moves) return;
      if (this.sel && this.sel !== sq && this._try(this.sel, sq)) return;
      if (this._from(sq).length) {
        this.sel = sq;
        this.drag = { from: sq, x0: x, y0: y, moved: false, id: e.pointerId };
        try { this.svg.setPointerCapture(e.pointerId); } catch (_) {}
      } else this.sel = null;
      this._overlay();
    }
    _move(e) {
      const d = this.drag;
      if (!d) return;
      const [x, y] = this._pt(e);
      if (!d.moved && Math.hypot(x - d.x0, y - d.y0) < 0.12) return;
      if (!d.moved) {
        d.moved = true;
        const img = this._img(d.from);
        if (img) img.style.opacity = "0.25";
        const ch = this.pieceAt(d.from);
        this.g.dg.innerHTML = ch ? `<image href="pieces/${this.pieces}/${ch === ch.toUpperCase() ? "w" : "b"}${KIND[ch.toLowerCase()]}.svg" width="1.08" height="1.08"/>` : "";
        this.svg.classList.add("dragging");
      }
      const im = this.g.dg.firstElementChild;
      if (im) { im.setAttribute("x", x - .54); im.setAttribute("y", y - .54); }
      const over = this._sqAt(x, y);
      this._hover(over && this._from(d.from).some(m => m.to === over) ? over : null);
    }
    _up(e) {
      const d = this.drag;
      if (!d) return;
      this.drag = null;
      try { this.svg.releasePointerCapture(d.id); } catch (_) {}
      this.svg.classList.remove("dragging");
      this.g.dg.innerHTML = "";
      this._hover(null);
      const img = this._img(d.from);
      if (img) img.style.opacity = "";
      if (!d.moved) return;          // a click: keep the selection
      const [x, y] = this._pt(e);
      const to = this._sqAt(x, y);
      if (to && to !== d.from && this._try(d.from, to, true)) return;
      this._overlay();
    }
    _cancelDrag() {
      if (!this.drag) return;
      const img = this._img(this.drag.from);
      if (img) img.style.opacity = "";
      this.drag = null; this.g.dg.innerHTML = ""; this.svg.classList.remove("dragging"); this._hover(null);
    }
    _img(sq) { return this.g.pc.querySelector(`image[data-sq="${sq}"]`); }
    _hover(sq) {
      let h = this.g.hl.querySelector(".hover");
      if (!sq) { if (h) h.remove(); return; }
      const [x, y] = this.xy(sq);
      if (!h) { h = document.createElementNS("http://www.w3.org/2000/svg", "rect"); h.setAttribute("class", "hover"); this.g.hl.appendChild(h); }
      h.setAttribute("x", x); h.setAttribute("y", y); h.setAttribute("width", 1); h.setAttribute("height", 1);
      h.setAttribute("fill", "none"); h.setAttribute("stroke", "rgba(255,255,255,.75)"); h.setAttribute("stroke-width", ".06");
    }

    // ---- drawing
    squares() {
      let s = "";
      for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {
        const dark = (x + y) % 2 === 1;
        s += `<rect x="${x}" y="${y}" width="1" height="1" fill="var(${dark ? "--sq-dark" : "--sq-light"})"/>`;
      }
      for (let i = 0; i < 8; i++) {
        const f = this.flipped ? FILES[7 - i] : FILES[i];
        const r = this.flipped ? i + 1 : 8 - i;
        const fileCol = (i % 2 === 0) ? "--sq-light" : "--sq-dark";
        const rankCol = (i % 2 === 0) ? "--sq-dark" : "--sq-light";
        s += `<text x="${i + 0.95}" y="7.96" font-size="0.2" font-weight="700" text-anchor="end" fill="var(${fileCol})" style="font-family:var(--font)">${f}</text>`;
        s += `<text x="0.05" y="${i + 0.24}" font-size="0.2" font-weight="700" fill="var(${rankCol})" style="font-family:var(--font)">${r}</text>`;
      }
      this.g.sq.innerHTML = s;
    }
    draw({ fen, lastUci = null, arrows = [], flipped, selected = null, dots = [], marks = [], animate = false }) {
      const prev = this.state;
      if (flipped !== undefined) this.flipped = flipped;
      const sameFen = prev && prev.fen === fen && prev.flipped === this.flipped;
      if (!sameFen) { this.sel = null; this.promo = null; this.g.pr.innerHTML = ""; }
      this.state = { fen, lastUci, arrows, selected, dots, marks, flipped: this.flipped };
      this.squares();
      // update the pieces in place (re-creating every image makes the board flicker)
      const want = new Map();
      fen.split(" ")[0].split("/").forEach((row, ri) => {
        let f = 0;
        for (const ch of row) {
          if (/\d/.test(ch)) { f += parseInt(ch, 10); continue; }
          want.set(FILES[f] + (8 - ri), (ch === ch.toUpperCase() ? "w" : "b") + KIND[ch.toLowerCase()]);
          f++;
        }
      });
      const setName = this.pieces;
      for (const img of [...this.g.pc.children]) {
        const sq = img.dataset.sq, nm = want.get(sq);
        if (nm && img.dataset.nm === nm && img.dataset.set === setName) {
          const [x, y] = this.xy(sq);
          img.setAttribute("x", x); img.setAttribute("y", y);
          img.style.transition = ""; img.style.transform = ""; img.style.opacity = "";
          want.delete(sq);
        } else img.remove();
      }
      for (const [sq, nm] of want) {
        const [x, y] = this.xy(sq);
        const img = document.createElementNS("http://www.w3.org/2000/svg", "image");
        img.setAttribute("href", `pieces/${setName}/${nm}.svg`);
        img.setAttribute("x", x); img.setAttribute("y", y); img.setAttribute("width", 1); img.setAttribute("height", 1);
        img.dataset.sq = sq; img.dataset.nm = nm; img.dataset.set = setName;
        this.g.pc.appendChild(img);
      }
      // slide the piece that just moved (from where it was), unless motion is reduced
      if (animate && lastUci && prev && prev.fen !== fen && !reduced()) {
        const from = lastUci.slice(0, 2), to = lastUci.slice(2, 4);
        const img = this._img(to);
        if (img) {
          const [x1, y1] = this.xy(from), [x2, y2] = this.xy(to);
          img.style.transition = "none";
          img.style.transform = `translate(${x1 - x2}px, ${y1 - y2}px)`;
          img.getBoundingClientRect();
          requestAnimationFrame(() => { img.style.transition = `transform ${SLIDE_MS}ms ease-out`; img.style.transform = "translate(0px, 0px)"; });
        }
      }
      this._overlay();
    }
    _overlay() {
      if (!this.state) return;
      const { lastUci, arrows, selected, dots, marks } = this.state;
      let h = "";
      if (lastUci) for (const sq of [lastUci.slice(0, 2), lastUci.slice(2, 4)]) { const [x, y] = this.xy(sq); h += `<rect x="${x}" y="${y}" width="1" height="1" fill="var(--sq-hi)"/>`; }
      const sel = this.sel || selected;
      if (sel) { const [x, y] = this.xy(sel); h += `<rect x="${x}" y="${y}" width="1" height="1" fill="var(--sq-sel)"/>`; }
      this.g.hl.innerHTML = h;
      let mk = "";
      for (const { sq, color } of marks || []) {
        const [x, y] = this.xy(sq);
        mk += `<rect x="${x + .04}" y="${y + .04}" width=".92" height=".92" rx=".08" fill="none" stroke="${color}" stroke-width=".08"/>`;
      }
      this.g.mk.innerHTML = mk;
      let d = "";
      const all = [...(dots || [])];
      if (this.sel && this.moves) {
        const seen = new Set();
        for (const m of this._from(this.sel)) {
          if (seen.has(m.to)) continue; seen.add(m.to);
          all.push({ sq: m.to, capture: m.san.includes("x") });
        }
      }
      for (const { sq, capture } of all) {
        const [x, y] = this.xy(sq);
        d += capture
          ? `<circle cx="${x + .5}" cy="${y + .5}" r="0.44" fill="none" stroke="rgba(20,20,20,.35)" stroke-width="0.08"/>`
          : `<circle cx="${x + .5}" cy="${y + .5}" r="0.15" fill="rgba(20,20,20,.32)"/>`;
      }
      this.g.dots.innerHTML = d;
      let a = "";
      for (const [uci, color, opt = {}] of arrows || []) {
        const [x1, y1] = this.xy(uci.slice(0, 2)), [x2, y2] = this.xy(uci.slice(2, 4));
        const cx1 = x1 + .5, cy1 = y1 + .5, cx2 = x2 + .5, cy2 = y2 + .5;
        const dx = cx2 - cx1, dy = cy2 - cy1, L = Math.hypot(dx, dy);
        if (L < 0.1) continue;
        const ux = dx / L, uy = dy / L, ex = cx2 - ux * .36, ey = cy2 - uy * .36, sx = cx1 + ux * .28, sy = cy1 + uy * .28;
        const px = -uy, py = ux;
        a += `<line x1="${sx}" y1="${sy}" x2="${ex}" y2="${ey}" stroke="${color}" stroke-width="0.17" stroke-linecap="${opt.dash ? "butt" : "round"}" opacity="0.85"${opt.dash ? ' stroke-dasharray="0.22 0.14"' : ""}/>`;
        a += `<polygon points="${cx2 - ux * .06},${cy2 - uy * .06} ${ex - px * .24},${ey - py * .24} ${ex + px * .24},${ey + py * .24}" fill="${color}" opacity="0.88"/>`;
        if (opt.label) {   // a numbered dot near the start of the arrow
          const lx = cx1 + ux * .42, ly = cy1 + uy * .42;
          a += `<circle cx="${lx}" cy="${ly}" r="0.17" fill="${color}" stroke="rgba(0,0,0,.35)" stroke-width="0.02"/><text x="${lx}" y="${ly + .065}" font-size="0.19" font-weight="800" text-anchor="middle" fill="#fff" style="font-family:var(--font)">${opt.label}</text>`;
        }
      }
      this.g.ar.innerHTML = a;
      this.svg.classList.toggle("clickable", !!this.onSquare || !!this.moves);
    }
  }

  // Lichess's mapping from eval (pawns, White's view) to White's win %.
  function winPct(pawns) { return 50 + 50 * (2 / (1 + Math.exp(-0.00368208 * pawns * 100)) - 1); }

  window.ChessBoard = Board;
  window.winPct = winPct;
})();
