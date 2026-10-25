# Chess Review

A desktop app that reviews your chess games on your own computer: a private,
local stand-in for chess.com's Game Review, with training built from your own
mistakes. Released for Macs with Apple silicon; Windows, Linux and Intel Macs
can build it from source.

It syncs your chess.com and Lichess games, analyses them with Stockfish, and
then helps you learn from them: move-by-move reviews, puzzles from your
errors, opening study from your repertoire, drills that replay wins you let
slip, and a weekly plan. Optionally, Maia (a neural net trained on human games)
shows how players at your rating move.

**Everything stays on your computer.** No account, no telemetry, no cloud: see
[Privacy](#privacy) for the few times it touches the network.

## Features

- **Library:** your games from chess.com and Lichess, plus pasted PGNs and links. Selective sync by period, time control and opponent rating keeps it small. Tags, notes and search.
- **Review:** every move graded (Brilliant, Great, Best, Good, Inaccuracy, Mistake, Blunder, Missed chance) with a plain-words verdict, the better line, what happened, key moments, an eval graph, a clock analysis and "retry this move". With Maia: what players at your level play, and a *practical move* when the engine's best is hard to find.
- **Board:** an analysis board with live engine lines, a move tree, saved lines and *Ask the coach*, which explains a move from the position itself (material, king safety, pawns, loose pieces, threats, a plan from the best line). A local Ollama model can put that into sentences and answer follow-ups.
- **Play:** a game against Maia at the rating you pick (1100-1900), with or without a clock (bullet to classical, or your own), with pause and resume. It plays like people at that rating and never the same game twice. Finished games land in your Library, ready to analyse; they stay out of Insights unless you count them in Settings.
- **Puzzles:** built from your analysed games and scheduled with spaced repetition, with an optional clock and a "one move or several?" question. **Convert the win** replays positions you were winning but didn't win, against Maia at your opponent's rating.
- **Openings:** your repertoire, starred from your games or learned from 3,600 named lines, studied line by line with spaced repetition. Games where you or they leave your lines move those lines back.
- **Export:** a reviewed game as an Obsidian note, or as annotated PGN (labels as ?! ? ?? ! !!, the verdict lines, the eval after every move, the better lines, clocks, your notes and tags) for a Lichess study or any PGN reader. Tick games in the Library to export many at once.
- **Insights:** where your points go, a skill profile, a weekly focus, tilt and session patterns, accuracy by phase (opening, middlegame, endgame) month by month, a heatmap of the squares where your errors land and where you lose pieces, endgames, the clock, mistakes you repeat, opponents you meet again, and a weekly Markdown note for Obsidian.
- **Weekly study plan** (optional): your training time split across puzzles, openings, convert drills and reviews, leaning toward what you most need. Switch it off in Settings.
- **Backups:** weekly on their own, plus backup and restore buttons.
- **Follow Palette** (optional, off by default): the app's colours follow the theme you pick in [Palette](https://github.com/praddy-31/Palette), a theme switcher for the whole desktop. Move labels and the board keep their own colours.

The changes milestone by milestone are in [CHANGELOG.md](CHANGELOG.md).

## Install

### macOS (Apple silicon)

Download the `.dmg` from the latest release, open it and drag **Chess Review** to
Applications. The app is ad-hoc signed, not notarised (there's no paid Apple
developer account behind it), so macOS refuses the first open. Run this once:

```bash
xattr -dr com.apple.quarantine "/Applications/Chess Review.app"
```

or right-click the app, choose Open, and confirm.

The engines aren't bundled, which keeps the app small. Install Stockfish with
[Homebrew](https://brew.sh); lc0 is only needed for Maia:

```bash
brew install stockfish          # required
brew install lc0                # optional, for Maia
```

### Windows, Linux and Intel Macs

There is no release build yet: build it from source (below). These builds are
community-supported: the app is developed and tested on a Mac.
Stockfish comes from your system's package manager:

| System | Stockfish | lc0 (optional, for Maia) |
|---|---|---|
| Windows | `winget install --id Stockfish.Stockfish -e`, or unzip it from stockfishchess.org into the data folder's `engines` | from github.com/LeelaChessZero/lc0/releases into `engines` |
| Debian, Ubuntu | `sudo apt install stockfish` | build it, or put the binary in `engines` |
| Fedora / Arch | `sudo dnf install stockfish` / `sudo pacman -S stockfish` | as above |

### First start

A short welcome asks for your chess.com and/or Lichess username, checks for
Stockfish (with the command for your system if it's missing), which games to
sync, and an optional weekly study plan. **Setup** in the sidebar shows the
commands for everything optional: Maia's weights and the opening book. Each
screen shows a short note the first time you open it; Settings > Appearance
brings them back.

## Privacy

Your games, reviews and settings stay in one folder on your computer (see
[Your data](#your-data)). The app has no account and sends no telemetry. It uses
the network only when you ask it to:

- **Sync**: fetches your games from the public chess.com and Lichess APIs, by your username.
- **Add games**: fetches a chess.com or Lichess game link you paste.
- **Opening explorer** (optional, off by default): asks Lichess what's played at
  your level, with your own Lichess token.
- **Coach in sentences** (optional, off by default): talks to an Ollama model
  running on your own computer (`localhost`).
- Links you click open in your browser.

**Follow Palette** (optional) only reads a local file Palette writes
(`~/.config/palette/current/chess-review.json`); it uses no network.

It never syncs, analyses or checks for updates on its own; the only thing it does unasked is a weekly backup, into the same folder.

## Build from source

All systems need [Python 3.10+](https://www.python.org), [Node 18+](https://nodejs.org)
and [Rust](https://rustup.rs), plus Tauri's system packages: on Windows the
Microsoft C++ Build Tools and WebView2, on Linux WebKitGTK, a C compiler and a few libraries (on Debian and Ubuntu:
`sudo apt install libwebkit2gtk-4.1-dev build-essential curl wget file libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev`). Tauri's
[prerequisites page](https://v2.tauri.app/start/prerequisites/) lists them per system.

```bash
git clone <this repo> chess-review
cd chess-review
python3 -m venv engine/.venv                                   # Windows: py -3 -m venv engine\.venv
engine/.venv/bin/pip install -r engine/requirements.txt       # Windows: engine\.venv\Scripts\pip ...

# run in a browser (no Rust needed)
engine/.venv/bin/python3 engine/server.py --port 8520 --token dev    # then open http://127.0.0.1:8520/#dev

# or in the native window
cd tauri && npm install && npm run dev

# build the app
cd tauri && npm install && npm run build
```

`npm run build` freezes the engine with PyInstaller (`tools/build_engine.py`, which
makes `engine/.venv` if needed) and then runs `tauri build`. The result lands in
`tauri/src-tauri/target/release/bundle/`: `.app` and `.dmg` on macOS, `.msi` and
`.exe` on Windows, `.deb`, `.rpm` and `.AppImage` on Linux.

## Tests

```bash
cd engine && .venv/bin/python3 selftest.py    # analysis, store, sync, study, coach, V8 features, HTTP API
engine/.venv/bin/pip install playwright && engine/.venv/bin/python3 -m playwright install chromium   # once
engine/.venv/bin/python3 tools/ui_test.py              # every screen in headless Chromium, no JS errors; screenshots in shots/
```

Both need Stockfish on the `PATH`. GitHub Actions runs them on every push, and builds the app on macOS, Linux and Windows. Checks that need Maia are skipped when it
isn't installed. Neither touches your real data or the network: they run on a
temporary data folder, and the UI test also starts the app as a clean computer
(no engines, no games) to check the first-run screens.

## How it's put together

| Folder | What it is |
|---|---|
| `engine/` | The local engine process: Python (standard library + python-chess). `server.py` is a small JSON API on 127.0.0.1 with a per-launch token, and it serves the UI; `routes/` holds the API by area and `system.py` everything that differs between macOS, Windows and Linux. `chess_analysis.py` grades moves; `puzzles.py`, `convert.py`, `study.py`, `repertoire.py`, `theory.py` train; `coach.py` and `features.py` explain; `skillprofile.py`, `patterns.py`, `opponents.py`, `plan.py` and `weekly.py` build Insights. |
| `web/` | The UI: plain HTML, CSS and JavaScript with no build step and nothing loaded from the network. |
| `tauri/` | The native shell (Tauri v2). It starts the engine, reads its `LISTENING <port> <token>` line and opens the window; the engine exits with the app. |
| `tools/` | `build_engine.py` (PyInstaller) and `build_app.mjs` (what `npm run build` runs), `ui_test.py`, `make_pieces.py`, and `make_theory.py`, which builds the opening theory tree. |
| `assets/` | The app icon. |

### Your data

| System | Folder |
|---|---|
| macOS | `~/Library/Application Support/Chess Review/` |
| Windows | `%APPDATA%\Chess Review\` |
| Linux | `~/.local/share/chess-review/` (or `$XDG_DATA_HOME/chess-review/`) |

It holds `chess.sqlite` (games, reviews, settings, puzzles, study schedules,
notes), `backups/`, `engine.log`, and the optional `maia/`, `book/` and `engines/`
folders. Set `CHESS_REVIEW_DATA` to use another folder. To remove everything,
delete the app and this folder.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

Chess Review is free software under the [GNU General Public License v3.0](LICENSE).

Bundled assets keep their own licences:

| Asset | Licence |
|---|---|
| Atkinson Hyperlegible Next font (`web/fonts`) | SIL OFL 1.1 |
| Classic pieces (cburnett, via python-chess) | GPLv2+ |
| Merida pieces | GPLv2+ |
| Chessnut pieces | Apache 2.0 |
| Fantasy pieces | MIT |
| Opening list (Lichess chess-openings) | CC0 |
| python-chess | GPLv3+ |

Stockfish (GPLv3), lc0 (GPLv3) and the Maia weights (GPLv3) are not bundled;
you install them yourself.
