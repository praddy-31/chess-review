# Contributing

Thanks for looking. Chess Review is a small, personal project: one person
builds it for his own games and shares it. Bug reports, fixes and ideas are
welcome; for anything bigger than a fix, open an issue first so we can agree on
it before you spend time on code.

## What the app will stay

These are settled; a change that goes against them won't be merged.

- **Local and private.** The network is used only for what the README's
  Privacy section lists. No telemetry, no accounts, no cloud services, no
  update checks.
- **Nothing happens on its own.** Games arrive when you press Sync or paste
  them; only games you pick are analysed. No background polling.
- **Engines aren't bundled.** Stockfish (and optionally lc0, Maia, an opening
  book) come from the user's package manager or a download; Setup shows how.
- **A language model only words facts.** The optional Ollama coach puts facts the
  Python code worked out into sentences. It never evaluates a position or invents numbers.
- **Optional features are off by default.**

## Getting started

Follow "Build from source" in the README. Running the engine in a browser
(`engine/server.py --port 8520 --token dev`) is the quickest loop: the UI has no
build step, so reload the page after editing `web/`.

`docs/ARCHITECTURE.md` explains the layers, the modules and how a game flows
through them. `docs/GRADING.md` has the rules behind every label, puzzle and drill.

## Checks

Both must pass before a pull request:

```bash
cd engine && .venv/bin/python3 selftest.py              # ~280 checks, a few minutes, needs Stockfish
engine/.venv/bin/python3 tools/ui_test.py               # every screen in headless Chromium; screenshots in shots/
node --check web/*.js                                    # quick syntax check after JS edits
```

The UI test needs Playwright once:
`engine/.venv/bin/pip install playwright && engine/.venv/bin/python3 -m playwright install chromium`.

- Add a self-test for every engine change and a UI check for every screen change.
  A bug fix comes with a test that fails without it.
- Tests run Stockfish on one thread: with more it isn't deterministic.
- Tests never touch your real data: they use a temporary folder through
  `CHESS_REVIEW_DATA`, and no test may reach the network.

## Rules for code

- **Engine:** Python standard library plus python-chess, nothing else. A new
  dependency needs a strong reason in the pull request.
- **UI:** plain HTML, CSS and JavaScript, no framework, no build step, nothing
  loaded from the network (fonts and piece images are in `web/`).
- **The engine owns the logic;** the UI renders what `/api/...` returns.
- **Never break an existing database.** New tables go in their module's `SCHEMA`
  with `CREATE TABLE IF NOT EXISTS`; new columns through the `ALTER TABLE` list in
  `store.connect()`. New settings go in `DEFAULT_SETTINGS` (`engine/store.py`) with a comment.
- **Paths may contain spaces.** Quote them.
- **Every platform difference goes in `engine/system.py`** (and `tauri/src-tauri/src/main.rs`
  for the shell), not scattered through the code.

## Changing how moves are graded

Labels, thresholds, puzzle selection, drills and schedules change what people
see about their own games, so they need evidence, not just a reason:

1. Describe the rule now and the rule you propose (`docs/GRADING.md` has them all).
2. Show the effect on real games: how many moves or puzzles change, with a few
   examples before and after.
3. Bump `GRADING_VERSION` in `engine/store.py`. Labels are recomputed from the
   stored engine data when a review is read, so nobody has to re-analyse.

## The UI

1. The board is the page: clicking a sentence, a bar or a key moment moves the board there.
2. Say it in words, then show the number.
3. A label is never colour alone: it has a glyph or an icon.
4. Charts explain themselves: named axes, one line on how to read them, hovers that name the move.
5. Quiet chrome, loud chess: strong colour only for move labels and the accent.

Plain words: "win chance", not "win%"; "points" for win-chance points. British
spelling in the UI and the docs.

## Reporting a bug

Use the bug template. Most useful: your system and the app's version, what you
did, what you expected, and the end of `engine.log` from the data folder (the
README lists where it is). Please check the log for anything you'd rather not
share before pasting it.

## Licence

Chess Review is GPL-3.0-or-later. By contributing you agree that your work is
released under the same licence.
