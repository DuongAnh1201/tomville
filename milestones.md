# Tomville milestones

The build checklist. Every agent working on Tomville reads this before starting and updates it when it reaches a milestone. Design: [README.md](README.md). Decisions and reasons: [idea.md](idea.md).

The project has two parts:

| Part | What | Team shapes |
| --- | --- | --- |
| **1. Fundamentals** | Everything needed for a real, usable office: live herdr data, movement, sprites, messages, CLI, install | Lead + workers, pipeline |
| **2. More shapes and polish** | The other team shapes, custom pets, themes, publishing, web UI | Pair/reviewer, fan-out, peer group, across machines |

Part 2 starts only after Part 1 is done.

## Rules for agents

1. **Pick the first milestone that isn't done.** Work on its tasks in order unless the lead says otherwise.
2. **Tick a task (`[ ]` → `[x]`) only when it works**, not when the code is written. Run what the task says, or the milestone's **Check**.
3. **A milestone is done only when its Check passes.** Then write the date and PR after it: `Done 2026-10-17 · PR #12`.
4. **If stuck, don't tick it.** Add a line under the task starting with `Blocked:`, saying what is wrong, and tell the lead.
5. **Update this file in the same PR as the work it describes.** Nobody works on `main`: every change is a branch and a PR linked to an issue, followed by a detailed comment on the issue (see [AGENTS.md](AGENTS.md)).
6. **Don't rewrite or reorder milestones.** If the plan needs to change, add a note under **Changes** at the bottom and tell the lead.
7. Tests (`uv run pytest`) must pass before any tick.
8. **Work items live in GitHub Issues.** Take a task with `tmv task take N` (or `gh issue edit N --add-label status:doing,agent:<you>` before `tmv task` exists). Close it with `Fixes #N` in the commit.
9. **Found a bug or idea outside the current milestone?** Open an issue (`gh issue create --label bug` or `--label idea`) instead of fixing it now.

---

# Part 1 · Fundamentals

Goal: a real office you use every day, with lead + workers and pipeline teams. Target: the two-day weekend build.

## M0 · Setup

- [x] Install `uv` (`curl -LsSf https://astral.sh/uv/install.sh | sh`); `uv --version` works
- [x] Python 3.11+ available to `uv` (tablet has 3.14.4)
- [x] Add `workflow` scope to `gh` (`gh auth refresh -s workflow`), needed before CI
- [x] Add Claude Code permission allow rules for `git`, `gh`, `uv`, `herdr`
- [x] Create board labels on the repo: `status:todo`, `status:doing`, `status:review`, `agent:claude`, `agent:codex1`, `bug`, `idea`
- [x] Note in [idea.md](idea.md) what `herdr agent list` shows for a named agent (`herdr agent start codex1 --kind codex --pane …`)

**Check:** `uv --version`, `gh auth status` lists `workflow`, and `herdr agent list` shows this agent.

Done 2026-10-17 · PR #13

## M1 · Skeleton and empty office

- [x] `pyproject.toml` with `tomville` and `tmv` entry points; package in `src/tomville/`
- [x] `uv tool install --editable .` puts both commands on `PATH`
- [x] `tomville --version` and `tmv --help` work
- [x] Textual layout: office floor, Team, Board, Events panels, key bar
- [x] Lead + workers office map: boss desk at the top with the board on the wall beside it, named worker desks facing the boss, lounge, review zone, door
- [x] Landscape and portrait layouts
- [x] `pytest` set up with one passing test

**Check:** `tmv` opens the empty office in a herdr tab at ~140 × 40, and `q` quits cleanly.

Done 2026-10-17 · PR #11

## M2 · Event reader (real data)

- [x] Read `herdr agent list` once at start into a typed model
- [x] Subscribe to herdr's event stream (`pane.agent_status_changed`, `pane.agent_detected`, `pane.closed`)
- [x] Fall back to polling every `poll_seconds` when the stream drops
- [x] Board plug-in interface (`board/`), chosen by `[board] source`
- [x] GitHub Issues source (default): `gh api` with `ETag`, every `check_seconds`; labels → columns and agents
- [x] `check_seconds` setting, `--board-check SEC`, `G` key to cycle 15/30/60/120 s
- [x] Offline: keep last cards, show `offline since …`
- [x] `TASKS.md` source: re-read on modified time
- [x] Turn all of it into app events ("codex1 became blocked", "T1 moved to review")
- [x] Team list and Board show live data; Events panel logs changes
- [x] Tests use recorded herdr and GitHub JSON, with no herdr or network

**Check:** start Codex in another herdr pane: it appears in the Team list within 2 s, and its status changes show up live. Add `status:doing` to an issue on GitHub: the card moves within `check_seconds`. Switch to `source = "tasks-md"`: the board reads the file instead.

Validation 2026-10-17: 18 tests pass. Live headless app loaded the running Codex, observed a GitHub label move within 10 s, and loaded the Markdown source. No live status transition occurred during the observation window; socket lifecycle/status/disconnect paths are covered offline. Lead must finish the visual start/status Check before marking M2 done.

Lead Check 2026-10-17: ran this branch in its own herdr tab. The Team panel showed claude, codex1 and claude2 at start; the Events panel logged live changes ("claude became idle", "claude2 became done").

Done 2026-10-17 · PR #15

## M3 · World model and lead + workers

- [x] Zones and the status-to-behaviour table from the README
- [x] Cell-by-cell movement around walls; speed in cells per second, independent of fps
- [x] Frame rate option and `F` key (5/10/15/30)
  `--fps` and `F` work; saving the choice waits for `settings.toml` (M6).
- [x] Team-shape interface in the world model, so Part 2 shapes plug in without changing the core
- [x] Lead + workers shape: lead at the front desk; `[team] lead` setting
  `--lead` for now; `settings.toml` arrives in M6.
- [x] Handover as in [idea.md](idea.md#lead--workers-layout): boss walks to the worker's desk, bubble "#12 is yours", worker "checking issues…", then "on it: #12" when it takes the issue (or a `doing` row in `TASKS.md`)
- [x] Conversation bubbles: show for a few seconds, never cover another pet's name
- [x] Done: worker walks to the boss desk, bubble "#12 ready for review"
- [x] Unit tests for the world model with fake events

**Check:** start Claude or Codex: its pet walks to its named desk; a `blocked` agent jumps with `❗`; an agent that exits walks out the door. Label an issue `agent:codex1`: the boss walks to codex1's desk and the bubbles appear in order.

Checked with fake events (`tests/test_world.py`, `tests/test_app.py`) and live in a herdr tab: claude, codex1 and claude2 sit at their desks and the board shows real cards. The live `blocked`, exit and `agent:` label steps are not run yet, so no `Done` line.

## M4 · Sprites

- [ ] Sprite file format (frames separated by `---`)
- [ ] Built-in cat, dog, sheep in emoji and ASCII
- [ ] Default pet for every herdr agent kind
- [ ] `S` key switches style; `--style`, `--pet AGENT=PET`

**Check:** `tmv --demo` shows three animated pets; `S` switches emoji ↔ ASCII without the map shifting; all tests pass.

## M5 · Messages and pipeline

- [ ] `tmv send AGENT TEXT`: sender from `HERDR_PANE_ID`, calls `herdr agent prompt`, appends to `.tomville/messages.jsonl`
- [ ] Claude Code `PreToolUse` hook that logs direct `herdr agent prompt` calls
- [ ] Envelope walk, speech bubble, `claude → codex1: …` in Events (both shapes)
- [ ] Conveyor-belt office map; `[team] shape = "pipeline"`, `stages = [...]`; `--team`
- [ ] Pipeline handoff from the log; timing guess as fallback, shown with `?`
- [ ] Check whether Codex has an equivalent hook; note the answer in [idea.md](idea.md)

**Check:** in lead + workers, `tmv send codex1 "…"` walks an envelope from lead to worker. With planner, coder and tester running in herdr, `tmv send` moves a card along the belt, and an unlogged handoff shows `?`.

## M6 · CLI essentials

- [ ] All office options from the README, with settings order: options > env vars > `settings.toml` > defaults
  - CLI parsing and validated settings are implemented; animation/style/pet/team rendering integration remains with the visual milestones. Project ville settings override user TOML; env and options override both.
- [x] `status` (`--json`, `--watch`, `--agent`), `doctor` (checks `gh` login and board labels), `config` (`path`, `show`, `get`, `set`)
- [x] `task new`, `task take`, `task move`, `task list`, calling `gh` underneath
- [ ] `new [NAME]`: create-a-ville wizard (name, shape, agents, pets, board, check interval, emoji test) → `.tomville/ville.toml`; creates board labels, adds the `tmv send` and `tmv task` rules to `CLAUDE.md`/`AGENTS.md`, installs the Claude hook
- [ ] Bare `tomville` in a project with no ville offers `tmv new`
- [ ] `setup`: redo calibration, labels, rules or hook for an existing ville
- [x] Exit codes as in the README; `--no-color` / `NO_COLOR`

**Check:** `tmv status --json` and `tmv doctor` give correct output; `tmv task take 12` moves card #12 to Doing on the next check; `--help` lists every option.

## M7 · Interaction and install

- [ ] `Tab` and tap to select a pet; `Enter` focuses that agent's herdr pane
- [ ] `?` help screen; `B` full-screen board
- [ ] `uv tool install git+https://github.com/DuongAnh1201/tomville` works on a fresh setup

**Check:** fresh install → `tmv new` → `tmv` shows the real team in both shapes, end to end.

**Part 1 done:** ______

---

# Part 2 · More shapes and polish

Goal: every team shape herdr can run, your own pets and looks, and an app anyone can install.

## M8 · Pair / reviewer shape

- [ ] Two facing desks; `[team] shape = "pair"`, `coder`, `reviewer`
- [ ] Draft goes coder → reviewer on handoff; feedback goes back as a speech bubble
- [ ] Review rounds counted on the card

**Check:** coder and reviewer running in herdr: each `tmv send` between them shows on screen, and the round count goes up.

## M9 · Parallel fan-out with worktrees

- [ ] `[team] shape = "fanout"`: lead splits work to N workers
- [ ] Each worker's desk labelled with its git worktree (from the agent's `cwd`, or `herdr worktree`)
- [ ] Merge zone: finished workers bring cards back to the lead

**Check:** three workers in separate worktrees show their own branch names; cards return to the lead as each finishes.

## M10 · Peer group

- [ ] `[team] shape = "peers"`: round table, no lead
- [ ] Any-to-any messages from the log drawn as pets visiting each other
- [ ] Message count per pair in the Team panel

**Check:** three peers sending to each other with `tmv send`: every message is drawn with the right sender and target.

## M11 · Across machines

- [ ] One event stream per saved machine (`herdr --machine LABEL`)
- [ ] One room per machine in the office; agent names shown with their machine
- [ ] Messages across machines walk through a door between rooms

**Check:** agents on this tablet and on one SSH machine show in their own rooms, live.

## M12 · Custom pets and block pixels

- [ ] Block-pixel sprite format with palettes
- [ ] Custom pets in `~/.config/tomville/sprites/` override built-ins
- [ ] `pets list`, `pets show`, `pets new`, `pets check`

**Check:** a fox made with `tmv pets new fox --from cat` walks around in its own colours.

## M13 · Themes and screen fit

- [ ] Themes night, game-boy, green-screen; `T` key; per-agent colours; `theme list`
- [ ] Emoji width check and calibration screen

**Check:** on the 11-inch tablet the map stays aligned in every style and theme.

## M14 · Power saving

- [ ] Stop animating when the tab is hidden; keep listening to events
- [ ] 2 fps when nobody is moving; 5 fps saver option

**Check:** with all agents idle for 5 minutes, CPU use stays low and the office wakes up on the next status change.

## M15 · Publish

- [ ] Licence chosen and `LICENSE` added
- [ ] `install.sh` one-line installer (Ubuntu x86_64/aarch64, macOS, Termux PRoot)
- [ ] `tmv update` and `tmv uninstall`
- [ ] GitHub Actions: tests on push; tag `v*` → PyPI (trusted publishing) + GitHub Release
- [ ] Repo made public

**Check:** `uv tool install tomville` and the `curl … | sh` line both work on a clean machine.

## M16 · Web UI

- [ ] `tmv web` via `textual serve`
- [ ] Later: real web UI with pixel canvas over a WebSocket

**Check:** the office works in a browser on the tablet.

**Part 2 done:** ______

---

## Changes

Notes about changes to the plan, newest first.

- 2026-10-17: No work on `main` for anyone; every change is a PR linked to an issue, with a detailed issue comment; the lead checks conflicts and squash-merges (#7).
- 2026-10-17: Issues #1–#6 opened, one per milestone M1–M6, as the board for this build. `AGENTS.md` and `CLAUDE.md` added with the team rules.
- 2026-10-17: First run is "create a new ville" (`tmv new`, saved in `.tomville/ville.toml`). Lead + workers layout designed: boss on top with the board, named worker desks facing it, handover with bubbles (M1, M3, M6).
- 2026-10-17: Pixel-art pets from online sets (`pets import`, big mode, pet gallery) saved as a later update in [idea.md](idea.md#later-updates); not in any milestone. Pets stay built-in for now.
- 2026-10-17: GitHub Issues is the main board (plug-in, `TASKS.md` as the alternative); user-chosen `check_seconds`; `tmv task` commands; agent rules 8 and 9.

- 2026-10-17: Split into Part 1 (fundamentals, lead + workers and pipeline) and Part 2 (other shapes and polish). Custom pets, block pixels, themes and power saving moved to Part 2.
- 2026-10-17: Milestones created from the README two-day plan and [idea.md](idea.md).
