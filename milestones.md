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

Lead Check 2026-10-17 (#25): live in a herdr tab. Labelling a new issue `agent:codex1` sent the boss to codex1's desk with "#26 is yours", then codex1 said "checking issues…". A temporary agent (`tmpbot`) got its own named desk when it started, and walked out through the door when it stopped. The `blocked` ❗ jump was seen in the rendered office with demo data (no real agent was blocked during the check).

Done 2026-10-17 · PR #14

## M4 · Sprites

- [x] Sprite file format (frames separated by `---`)
- [x] Built-in cat, dog, sheep in emoji and ASCII
- [x] Default pet for every herdr agent kind
- [x] `S` key switches style; `--style`, `--pet AGENT=PET`

**Check:** `tmv --demo` shows three animated pets; `S` switches emoji ↔ ASCII without the map shifting; all tests pass.

## M5 · Messages and pipeline

- [x] `tmv send AGENT TEXT`: sender from `HERDR_PANE_ID`, calls `herdr agent prompt`, appends to `.tomville/messages.jsonl`
- [x] Claude Code `PreToolUse` hook that logs direct `herdr agent prompt` calls
- [x] Envelope walk, speech bubble, `claude → codex1: …` in Events (both shapes)
- [x] Conveyor-belt office map; `[team] shape = "pipeline"`, `stages = [...]`; `--team`
- [x] Pipeline handoff from the log; timing guess as fallback, shown with `?`
- [x] Check whether Codex has an equivalent hook; note the answer in [idea.md](idea.md)

**Check:** in lead + workers, `tmv send codex1 "…"` walks an envelope from lead to worker. With planner, coder and tester running in herdr, `tmv send` moves a card along the belt, and an unlogged handoff shows `?`.

Lead Check 2026-10-17: live, `tmv send claude2 …` walked the boss with ✉ to claude2's desk (#18). In a pipeline of two real agents (`claude` → `claude2`), a `tmv send` moved card `[#5]` along the belt (#22). The unlogged `?` handoff and the drop into DONE are covered by tests (they need real status changes between two stages).

Done 2026-10-17 · PR #18, PR #22

## M6 · CLI essentials

- [x] All office options from the README, with settings order: options > env vars > `settings.toml` > defaults
  - CLI parsing and validated settings are implemented; animation/style/pet/team rendering integration remains with the visual milestones. Project ville settings override user TOML; env and options override both.
  - Lead 2026-10-17 (#25): now all wired up: `--fps` (M3), `--style` / `--pet` (M4), `--team` (M5), `--still` (added in #25). `--theme` maps to Textual themes until M13; `--style blocks` falls back to ASCII until M12.
- [x] `status` (`--json`, `--watch`, `--agent`), `doctor` (checks `gh` login and board labels), `config` (`path`, `show`, `get`, `set`)
- [x] `task new`, `task take`, `task move`, `task list`, calling `gh` underneath
- [x] `new [NAME]`: create-a-ville wizard (name, shape, agents, pets, board, check interval, emoji test) → `.tomville/ville.toml`; creates board labels, adds the `tmv send` and `tmv task` rules to `CLAUDE.md`/`AGENTS.md`, installs the Claude hook
- [x] Bare `tomville` in a project with no ville offers `tmv new`
- [x] `setup`: redo calibration, labels, rules or hook for an existing ville
- [x] Exit codes as in the README; `--no-color` / `NO_COLOR`

**Check:** `tmv status --json` and `tmv doctor` give correct output; `tmv task take 12` moves card #12 to Doing on the next check; `--help` lists every option.

Lead Check 2026-10-17 (#25): `tmv status --json` → 3 agents, 13 cards, no errors; `tmv doctor` → 0 problems, 0 warnings; `--help` lists every option and command; `tmv task take 20` (by codex1) moved #20 to Doing on the board. `tmv new --yes` in a throwaway repo saved the ville, wrote the rules and added the hook (#21).

Done 2026-10-17 · PR #16, PR #21

## M7 · Interaction and install

- [ ] `Tab` and tap to select a pet; `Enter` focuses that agent's herdr pane
- [ ] `?` help screen; `B` full-screen board
- [ ] `uv tool install git+https://github.com/DuongAnh1201/tomville` works on a fresh setup

**Auto team setup (lead shape).** The user answers questions once; Tomville builds the team, nobody types `herdr` commands. Plan: [idea.md](idea.md#auto-team-setup).

- [x] `[agents.NAME]` table in the ville (`kind`, `model`, `place`, `branch`, `role`, `email`) and `start_timeout`, read by `settings.py` (lead)
- [x] `tmv new` asks per agent: name, kind, model (free text, empty = CLI default), place (`worktree` default, `tab`, `pane`; the lead `here`); offers a secretary (Claude Haiku) and its email; writes `[agents.*]`; ends with "Start the team now?"
- [x] `tmv up`: no ville → runs the `tmv new` questions first; with a ville → builds the team with no questions. Per agent: skip if running, make its place, wait for the shell, `herdr agent start … -- --model …`, one at a time; then the first prompt with `tmv send`; then an `office` tab running `tmv`. Safe to run again
- [x] Who is the lead: `tmv up` inside an agent's pane → that agent; in a plain shell → Tomville starts the lead in a new tab. Written clearly in the README
- [x] Any agent that herdr can't detect is announced: pane, running process, last lines, known fix (script launcher, CLI missing, startup prompt such as folder trust, remembered path) or `herdr agent explain`. `tmv doctor` runs the same checks
- [ ] `tmv setup launcher KIND`: wrapper in `~/.local/bin` that runs the real binary (asks first)
  - Lead 2026-10-18: offline tests pass; not run live yet (the tablet already has a hand-made wrapper).
- [x] `tmv down` / `--office`: office only; `--agents`: confirmed stop of every configured ville agent, including pre-existing agents, then office; `NAME`: one owned agent. Keep worktrees, pre-existing panes and the caller (Tom approved #49).
- [x] README "Start your team" section; tests with recorded herdr JSON, no herdr (README and wizard tests done in #40; `up`/`down` tests with #39)

**Check:** fresh install → `tmv new` → `tmv` shows the real team in both shapes, end to end. Auto setup: in a fresh herdr session with no ville, `tmv up` and answers only → every agent in `tmv status`, workers in their own worktrees, office tab open; `tmv up` again starts nothing; npm Codex without the launcher → `tmv up` names the pane, process and fix; `tmv down` → office gone, agents working; `tmv down --agents --yes` → ville agents stopped, owned panes gone, pre-existing panes and worktrees kept.

Lead Check 2026-10-18 (#39, #49), live on the tablet:
- `tmv up` in a plain shell with a fresh 4-agent ville (Claude lead, Claude and Codex workers in worktrees, Haiku secretary in a tab): lead started in a new tab, workers in their own worktrees, secretary, office tab open. Codex stopped at its folder-trust question: reported with pane, process and "answer it yourself", left unanswered. After answering, `tmv up` again finished it and created no duplicates.
- `tmv up` from the lead's pane with the running team in the ville: adopted the caller as lead, "already running" for the 3 workers, started nothing, opened the office.
- `tmv down` (no flag): only the office closed, all agents kept working. `--office --agents` refused; `--agents` without a terminal and without `--yes` refused.
- `tmv down --agents --yes` from the lead's pane: preview listed each agent; claude2, codex1 and secretary quit with their pre-existing panes kept at the shell; lead kept as caller; office closed. Worktrees untouched. `tmv up` then started all three again in new tabs, with first prompts and the office.
- Not run live: npm Codex without the launcher (covered by offline tests) and `tmv setup launcher`.

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

- [x] Licence chosen and `LICENSE` added (MIT)
- [ ] `install.sh` one-line installer (Ubuntu x86_64/aarch64, macOS, Termux PRoot)
- [ ] `tmv update` and `tmv uninstall`
- [ ] GitHub Actions: tests on push; tag `v*` → PyPI (trusted publishing) + GitHub Release
  - Lead 2026-10-17: `release.yml` builds, tests, installs the wheel and uploads to PyPI on a `v*` tag (TestPyPI when run by hand). Still to do: tests on every push, GitHub Release. Setup steps in [RELEASING.md](RELEASING.md).
- [x] Repo made public

**Check:** `uv tool install tomville` and the `curl … | sh` line both work on a clean machine.

## M16 · Web UI

- [ ] `tmv web` via `textual serve`
- [ ] Later: real web UI with pixel canvas over a WebSocket

**Check:** the office works in a browser on the tablet.

## M17 · Phone (Telegram)

Optional, one bot per ville, lead + workers only for now. Design: `tomville-telegram-proposal.md` (approved by Tom 2026-10-20).

- [ ] Per-ville bot: setup with pairing code, routing (plain text → lead, `/<agent>` → agent), command menu, pings, `from` list, `tmv reply`, `tmv telegram setup/run/status/pause/resume/off`, `telegram` tab in `tmv up` / `down` (#58)
- [ ] Approval buttons with the same-question check, off by default, 10-minute expiry (#58)
- [ ] `tmv reply --diff PR`: diffs per file in code blocks (#72)
- [x] `tmv new` last question "Connect a Telegram chat to this ville? (no)"; other team shapes get "Sorry, we haven't done Telegram for the <shape> team yet" (#59)
- [x] Office: 📱 envelope from the door to the target's desk, `📱 → tom:` reply bubble, ✅ / ❌ approval bubble, `📱 tom → codex1: …` in the Events panel (#59)
- [x] Rules for agents when Telegram is on (`ville.rules_text`, AGENTS.md "For the lead") and the secretary sending its summaries to the chat, diffs with `tmv reply --diff` (#59)
- [x] README "Phone (Telegram)" and the Commands table rows (#59)

**Check:** pair a real bot; text → the lead; `/codex1 …` → codex1; `/status` answers; another account is ignored; `tmv reply` arrives; the secretary's summary (with `--diff`) arrives; a blocked agent pings; with approvals on, ✅ approves the exact question and a changed question is refused; the office shows the 📱 walking in.

**Part 2 done:** ______

---

## M18 · Shared Markdown docs

Agents and Tom read and write Markdown together. Project docs (README, `docs/`, any `.md` in the repo) change through branch and PR; team notes in `notes/` of the main checkout are edited live, with no PR. Issues #94–#97 (#98 is a proposal only).

- [x] `tmv doc list`, `read` (whole file or `--section "A > B"`, with a version tag) and `new`; safety rules (only `.md`, only under `[docs] roots`, nothing outside the project); parser in `core/docs.py` (#94)
- [x] `tmv doc edit`: atomic write, 3-way merge, git-style conflicts and resolve (#95)
- [x] Doc change log: who changed what, diff and revert (#96)
- [x] Team sees doc changes: watch, office, secretary, Telegram (#97)

**Check:** two agents edit different sections of one note at the same time and both edits survive; the same section gives a conflict that `tmv doc resolve` settles; the change log shows both.

**Done:** ______

---

## Changes

Notes about changes to the plan, newest first.

- 2026-10-28: Doc changes reach the team (#97): `tmv watch` exits on them, office Events line and 📄 to the shelf, secretary "Doc changes" part, Telegram `/doc read|watch`. New shared event type `DocChanged` in `models.py`.
- 2026-10-28: Doc change log added (#96): `.tomville/doc-log.jsonl`, `tmv doc log/diff/revert`, outside edits logged as `tom (editor)`, version cap `[docs] keep_versions`.
- 2026-10-28: `tmv doc edit` / `resolve` added (#95): lock + atomic write, 3-way merge, conflict markers.
- 2026-10-28: M18 Shared Markdown docs added at Tom's approval (#94–#98). `tmv doc list/read/new` and `core/docs.py` done in #94.
- 2026-10-20: Release 0.2.1 to PyPI: Telegram fixes (bot no longer stalls, taps never lost, heartbeat in status and doctor, end-of-turn questions found anywhere in the message). See CHANGELOG.md.
- 2026-10-20: Release 0.2.0 to PyPI, highlighting Telegram (M17): optional phone chat per ville, lead permission buttons, diffs, wall board cards, `tmv watch`, fixes (see CHANGELOG.md). M17 live check still pending.
- 2026-10-20: M17 Phone (Telegram) added at the end of Part 2, at Tom's request: optional, one bot per ville, lead + workers only; approvals off by default; MFA later (#60).
- 2026-10-18: Release 0.1.0 to PyPI (`uv tool install tomville`): the office, `tmv new` / `up` / `down`, status, doctor, task, setup. Tested on Ubuntu and macOS in CI; live use so far on Ubuntu in Termux PRoot.
- 2026-10-17: PyPI packaging pulled forward from M15 at Tom's request: MIT licence, package page `docs/pypi.md`, metadata, release workflow. First release 0.1.0 waits for M7 auto setup (#39).
- 2026-10-17: Auto team setup (`tmv up`, `tmv down`, agent kinds and models, secretary, detection messages) added to M7, since M7's Check already asks for `tmv new` → real team end to end. Lead shape only; pipeline later.
- 2026-10-17: M0–M6 done. M7 (interaction and install) is next in Part 1.
- 2026-10-17: No work on `main` for anyone; every change is a PR linked to an issue, with a detailed issue comment; the lead checks conflicts and squash-merges (#7).
- 2026-10-17: Issues #1–#6 opened, one per milestone M1–M6, as the board for this build. `AGENTS.md` and `CLAUDE.md` added with the team rules.
- 2026-10-17: First run is "create a new ville" (`tmv new`, saved in `.tomville/ville.toml`). Lead + workers layout designed: boss on top with the board, named worker desks facing it, handover with bubbles (M1, M3, M6).
- 2026-10-17: Pixel-art pets from online sets (`pets import`, big mode, pet gallery) saved as a later update in [idea.md](idea.md#later-updates); not in any milestone. Pets stay built-in for now.
- 2026-10-17: GitHub Issues is the main board (plug-in, `TASKS.md` as the alternative); user-chosen `check_seconds`; `tmv task` commands; agent rules 8 and 9.

- 2026-10-17: Split into Part 1 (fundamentals, lead + workers and pipeline) and Part 2 (other shapes and polish). Custom pets, block pixels, themes and power saving moved to Part 2.
- 2026-10-17: Milestones created from the README two-day plan and [idea.md](idea.md).
