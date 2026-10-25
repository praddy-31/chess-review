# Grading and training rules

What every label, puzzle, drill and schedule in the app means. Changing any of
these is a heuristic change: propose it with its effect on the owner's games and
agree it first. Defaults live in `Thresholds` (`engine/chess_analysis.py`) and
`DEFAULT_SETTINGS` (`engine/store.py`); Settings > Labels edits the thresholds,
and labels recompute without re-analysis.

## Win chance and accuracy

- Win chance from centipawns, Lichess's curve: `50 + 50 * (2 / (1 + e^(-0.00368208 * cp)) - 1)`,
  cp clamped to ±1000; a forced mate is 100% or 0% (`win_percent`).
  +100 cp is about 59%, +300 about 75%, +800 about 95%.
- Move accuracy from points lost, Lichess's formula (`move_accuracy`); game accuracy averages it.
- Win chance tops out near mate, so rules that compare two win chances must treat
  mates separately (see Puzzles).

## Move labels

Checked in this order; one label per move (Missed chance is an extra flag).

| Label | Rule |
|---|---|
| Book | the position after the move is in the Polyglot book or the named-opening list; never flagged |
| Brilliant | the engine's best move, and after a capture-only search (both sides may capture anywhere, or stop) you are 2+ points of material down; some other legal move would have kept that material (so check escapes and pieces lost anyway don't count); you were below 90%, are 45%+ after it, and it isn't a recapture. Grading v4, 2026-10-04 |
| Great | the only good move (second best loses 20+ points, you're below 95%, not a capture or a check escape), or the best move right after the opponent's mistake that turns the game: losing (<35%) to equal (45%+), or equal (<65%) to winning (80%+), when the next best keeps under half of that swing |
| Best | the engine's move |
| Good | under 5 points lost |
| Inaccuracy / Mistake / Blunder | 5-10 / 10-20 / 20+ points of win chance lost (chess.com's bands) |
| Missed chance | a flag, independent of the label: the best move was 1.5+ pawns better while yours still kept about equal (-0.5 or better), evals capped at ±10, or you didn't play a forced mate |

Also per move: **Position** (Winning / Balanced / Losing at ±1 pawn), **Initiative**
(Attacking / Defending / Neutral; stored as `phase` Attack / Defense / Neutral, from threat probes: a free move gaining 1.5+ pawns,
material or mate), **Type** (opening / tactical / positional / endgame: opening and
endgame are the game's phase by Lichess's divider, below; in the middlegame a bad
move's type comes from its refutation, a good one's from the best line).

**Game phases** (grading 5, `engine/divider.py`, ported from Lichess): the middlegame
starts at the first position with 10 or fewer queens, rooks, bishops and knights, or
fewer than 4 of a side's pieces on its home rank, or mixedness over 150 (both sides'
pieces side by side, scored over 2x2 squares); the endgame at 6 or fewer of those
pieces; a middlegame that would start at or after the endgame is dropped. One split
for the whole app: the Review's bands, phase accuracy and clock split, the move types,
the Endgame skill and Insights by phase. (Before grading 5: opening = the first 10
moves or the book, endgame = 14 or less non-pawn material, which found an endgame
about five times less often.) Book moves still count up to move 20 (`opening_ply`).

Rating never changes the thresholds. It enters through Maia (does a player at your
level find the move?) and the repertoire depth cap.

## Explanations

A rule-based motif detector reads the engine lines: mate, back-rank mate, fork,
discovered check, undefended piece, pin, promotion, material won. A material
claim is only made when the eval backs it up. Each flagged move gets one short
verdict line plus tags. The coach (Board) adds position features, threats both
ways, a plan from the best line and Maia; Ollama, when on, only rewords those facts.

## Clock

A per-move budget = starting clock / typical game length + increment (40 moves
until you have 30+ games of that time control, then your own median). A snap move
is under a third of the budget, a long think over 3x, low clock under 4x the budget left.

## Puzzles

- From your analysed games: your mistakes and blunders, missed chances, unsolved
  retries, and (on by default) the position after your opponent's mistake.
- **Tactic** (one answer): the best move is 10+ points better than the second best.
  **Better move** (several answers): your own error where several moves were fine;
  any move within 3 points of the best counts. Opponent-mistake puzzles are tactics only.
- **Forced mates** (up to mate in 4) are always one-answer puzzles unless the second
  best mates just as fast; only an equally fast mate is another answer; a slower
  mate is taken back with a hint, not a miss. (2026-10-05: win chance saturates at
  mate, so the gap rule had called every mate "several moves are fine".)
- The solution follows the engine line while it stays forcing (up to 3 of your
  moves); mates are played out.
- Hints go piece, square, answer. A miss shows their answer as a red arrow until Retry.
- "One move or several?" before each puzzle (on by default, scored). Optional clock:
  your per-move budget for that game's time control times your moves; over time =
  "slow" (back sooner), not a miss.
- Schedule (small SM-2): solved without hints 1, 3, then x ease days; with hints a
  short gap; failed back tomorrow. 10 a day by default.

## Convert the win

- Source: analysed games you drew or lost where, after move 8 and on your move, you
  were +3 or better (or had a forced mate). One drill per game.
- Defender: Maia at the opponent's rating, sampling its moves with 5%+ probability;
  without Maia, Stockfish with `UCI_LimitStrength` at that rating (1320 minimum).
- Stockfish only judges. Won: mate, or 95%+ after 6+ of your moves. Lost: under 60%,
  a draw, or 60 of your moves without finishing.
- Scheduled like puzzles; 3 a day by default.

## Practical move (needs Maia)

Maia's likely moves (4%+, up to 6) at your rating (your main time control's, from your games), checked by Stockfish; the
practical move is the most likely one within 5 points of the best. Shown only when
it differs from the best (Review move card for your non-best moves, Board panel).

## Openings

- **Repertoire from your games** follows a line while 3+ games and 1%+ of your
  games reach it, capped by rating: 6 / 8 / 10 / 12 of your moves below 1000 /
  1400 / 1800 / higher.
- **Learning a named opening**: your moves along it, the main line (most theory
  below it, among moves within half a pawn of the best), named replies as
  branches; length 1-5 (3 = recommended for your rating; 5 = to the end of theory
  plus 4 Stockfish moves).
- **Study**: lines start where the repertoire starts. New → learning (same-day
  steps at about 10 minutes and at the end of the session) → reviews at 1, 3, 7,
  16, 35, 80, 180 days. A miss sends a line back to the same-day steps. Learned = a
  clean review 7+ days after learning. 3 new lines a day plus every due review;
  practice rounds don't move the schedule. A real game that leaves a reviewed line
  at your move moves it one step back (7 days becomes 3).

## Insights

- Six skill scores (0-100): Opening, Tactics, Converting, Defending, Endgame, Time,
  each with its game count; they fade under 5 games.
- Performance rating = average opponent + 400 x (wins - losses) / games.
- Weekly focus: three suggested leaks with how each is measured; the chosen one
  compares the 30 days before with the days since.
- Mistakes you repeat: errors grouped by motif, lately vs before.
- Opponents: players you've met 2+ times.
- Weekly study plan: puzzles 30%, opening study 25%, convert drills 20%, reviewing
  games 25%, tilted +15% toward the weekly focus's area and +5% to puzzles for the
  top repeated mistake. Cost per item: puzzle 1.5 min, line 1.5, drill 6, game 8.
  Weeks run Monday to Sunday. Not asked = no plan; 0 = off.
- By phase (V10, `engine/phases.py`), with the game phases above. Per phase: your
  accuracy and points lost per move (book moves left out), by month and this period
  vs the one before.
- Endgame skill: accuracy of your moves in the endgame phase (games with 4+ of them);
  the endgame table sorts games by the heaviest piece left when the endgame starts.
- Games against Maia (source `maia`) are training: left out of Insights, opponents, the
  weekly note and mistakes you repeat unless Settings counts them; never in the opening
  tree, repertoire or study deviations; always used for puzzles and convert drills.
- Heatmap: the square each of your mistakes and blunders moved to, and the square of
  the piece the opponent captured on the very next move; Black's games mirrored so
  your side is always at the bottom.

## Remote engine batches

A deep batch result replaces a stored analysis only when it is deeper; it must
have the known result format and the same analysis core version
(`ANALYSIS_VERSION`), else it is skipped and reported. Batches use one thread and
256 MB hash per engine; grades match in-app analysis at the same depth.

## Play against Maia

- Maia plays from its policy: moves with 5%+ probability, picked at random weighted by
  it (the convert drills' rule). No search, no Stockfish.
- Ends: mate, stalemate, threefold repetition, 50 moves, insufficient material, your
  resignation, your flag; a flag against a lone king (or too little to mate) is a draw.
- Clock: you spend real time; Maia's think is booked as (time left / 80 before move 10,
  / 40 after) x a random 0.4-1.6, at least 0.5 s and at most half its time. It answers
  at once; the booked time is only for the PGN's [%clk] and the clock you see.
