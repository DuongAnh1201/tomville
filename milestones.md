# Tomville milestones

The build checklist. Every agent working on Tomville reads this before starting and updates it when it reaches a milestone. Design: [README.md](README.md). Decisions and reasons: [idea.md](idea.md).

## Rules for agents

1. **Pick the first milestone that isn't done.** Work on its tasks in order unless the lead says otherwise.
2. **Tick a task (`[ ]` → `[x]`) only when it works**, not when the code is written. Run what the task says, or the milestone's **Check**.
3. **A milestone is done only when its Check passes.** Then write the date and commit after it: `Done 2026-10-17 · a1b2c3d`.
4. **If stuck, don't tick it.** Add a line under the task starting with `Blocked:`, saying what is wrong, and tell the lead.
5. **Commit this file with the work it describes**, in the same commit.
6. **Don't rewrite or reorder milestones.** If the plan needs to change, add a note under **Changes** at the bottom and tell the lead.
7. Tests (`uv run pytest`) must pass before any tick.

---

## M0 · Setup

- [ ] Install `uv` (`curl -LsSf https://astral.sh/uv/install.sh | sh`); `uv --version` works
- [ ] Python 3.11+ available to `uv` (tablet has 3.14.4)
- [ ] Add `workflow` scope to `gh` (`gh auth refresh -s workflow`), needed before CI
- [ ] Add Claude Code permission allow rules for `git`, `gh`, `uv`, `herdr`
- [ ] Note in [idea.md](idea.md) what `herdr agent list` shows for a named agent (`herdr agent start codex1 --kind codex --pane …`)

**Check:** `uv --version`, `gh auth status` lists `workflow`, and `herdr agent list` shows this agent.

## Day 1: a live, moving office

### M1 · Skeleton and empty office

- [ ] `pyproject.toml` with `tomville` and `tmv` entry points; package in `src/tomville/`
- [ ] `uv tool install --editable .` puts both commands on `PATH`
- [ ] `tomville --version` and `tmv --help` work
- [ ] Textual layout: office floor, Team, Board, Events panels, key bar
- [ ] Office map drawn (desks, review zone, done zone, lounge, door)
- [ ] Landscape and portrait layouts
- [ ] `pytest` set up with one passing test

**Check:** `tmv` opens the empty office in a herdr tab at ~140 × 40, and `q` quits cleanly.

### M2 · Event reader (real data)

- [ ] Read `herdr agent list` once at start into a typed model
- [ ] Subscribe to herdr's event stream (`pane.agent_status_changed`, `pane.agent_detected`, `pane.closed`)
- [ ] Fall back to polling every `poll_seconds` when the stream drops
- [ ] Read `TASKS.md` when it changes (mtime) into board cards
- [ ] Turn all of it into app events ("codex1 became blocked", "T1 moved to review")
- [ ] Team list and Board show live data; Events panel logs changes
- [ ] Tests use recorded herdr JSON, with no herdr running

**Check:** start Codex in another herdr pane: it appears in the Team list within 2 s, and its status changes show up live.

### M3 · World model and movement (lead + workers)

- [ ] Zones and the status-to-behaviour table from the README
- [ ] Cell-by-cell movement around walls; speed in cells per second, independent of fps
- [ ] Frame rate option and `F` key (5/10/15/30)
- [ ] Lead + workers shape: lead at the front desk; `[team] lead` setting
- [ ] Task handover from a new `doing` row in `TASKS.md`
- [ ] Unit tests for the world model with fake events

**Check:** start Claude or Codex: its pet walks to a desk; a `blocked` agent jumps with `❗`; an agent that exits walks out the door.

### M4 · Sprites

- [ ] Sprite file format (frames separated by `---`)
- [ ] Built-in cat, dog, sheep in emoji and ASCII
- [ ] Default pet for every herdr agent kind
- [ ] `S` key switches style; `--style`, `--pet AGENT=PET`

**Check:** `tmv --demo` shows three animated pets; `S` switches emoji ↔ ASCII without the map shifting; all tests pass.

Day 1 done: ______

## Day 2: team shapes, messages, your own pets, install

### M5 · Pipeline shape and messages

- [ ] Conveyor-belt office map; `[team] shape = "pipeline"`, `stages = [...]`; `--team`
- [ ] `tmv send AGENT TEXT`: sender from `HERDR_PANE_ID`, calls `herdr agent prompt`, appends to `.tomville/messages.jsonl`
- [ ] Claude Code `PreToolUse` hook that logs direct `herdr agent prompt` calls
- [ ] Envelope walk, speech bubble, `claude → codex1: …` in Events
- [ ] Pipeline handoff from the log; timing guess as fallback, shown with `?`
- [ ] Check whether Codex has an equivalent hook; note the answer in [idea.md](idea.md)

**Check:** with planner, coder and tester running in herdr, `tmv send` moves an envelope and a card along the belt, and an unlogged handoff shows `?`.

### M6 · Custom pets and block pixels

- [ ] Block-pixel sprite format with palettes
- [ ] Custom pets in `~/.config/tomville/sprites/` override built-ins
- [ ] `pets list`, `pets show`, `pets new`, `pets check`

**Check:** a fox made with `tmv pets new fox --from cat` walks around in its own colours. (First to drop if short on time.)

### M7 · Themes and screen fit

- [ ] Themes night, game-boy, green-screen; `T` key; per-agent colours
- [ ] Emoji width check and calibration screen

**Check:** on the 11-inch tablet the map stays aligned in every style and theme. (Second to drop.)

### M8 · CLI commands

- [ ] All office options from the README, with settings order: options > env vars > `settings.toml` > defaults
- [ ] `status` (`--json`, `--watch`, `--agent`), `doctor`, `setup` (also writes the `tmv send` rule to `CLAUDE.md`/`AGENTS.md` and installs the hook), `config`, `theme list`
- [ ] Exit codes as in the README; `--no-color` / `NO_COLOR`

**Check:** `tmv status --json` and `tmv doctor` give correct output; `--help` lists every option.

### M9 · Touch, power, install

- [ ] Tap to select a pet; `Enter` focuses that agent's herdr pane
- [ ] Stop animating when the tab is hidden; 2 fps when idle
- [ ] `uv tool install git+https://github.com/DuongAnh1201/tomville` works on a fresh setup

**Check:** fresh install → `tmv setup` → `tmv` shows the real team, end to end.

Day 2 done: ______

## After the weekend

### M10 · Publish (phase 2)

- [ ] Licence chosen and `LICENSE` added
- [ ] `install.sh` one-line installer (Ubuntu x86_64/aarch64, macOS, Termux PRoot)
- [ ] `tmv update` and `tmv uninstall`
- [ ] GitHub Actions: tests on push; tag `v*` → PyPI (trusted publishing) + GitHub Release
- [ ] Repo made public

**Check:** `uv tool install tomville` and the `curl … | sh` line both work on a clean machine.

### M11 · Web UI (phase 3)

- [ ] `tmv web` via `textual serve`
- [ ] Later: real web UI with pixel canvas over a WebSocket

**Check:** the office works in a browser on the tablet.

---

## Changes

Notes about changes to the plan, newest first.

- 2026-10-17: Milestones created from the README two-day plan and [idea.md](idea.md).
