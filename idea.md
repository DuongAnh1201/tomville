# Tomville: the idea

2026-10-17 · Tom Nguyen

This file collects what we decided while planning, and why. [README.md](README.md) is the full design (screens, options, file layout); [milestones.md](milestones.md) is the build checklist. When the three disagree, update them together.

## What Tomville is

A retro game view of an agent team, in the terminal. Each agent (Claude, Codex, …) is a pixel pet walking around an office, and its movement shows what the agent is doing. You can see the whole team at a glance: who is working, who is stuck waiting for you, who is done.

**Tomville builds on top of herdr; it is not a new herdr.** herdr is the terminal manager: it runs the tabs and panes, starts the agents, keeps sessions alive and works out each agent's status. Tomville is one more app in its own herdr tab. It reads herdr's status and draws it, and a few keys send you back into herdr (for example `Enter` on a pet opens that agent's pane).

Why not build a new herdr: real terminals inside panes, persistent sessions, agent detection and the Claude/Codex integrations are months of work, harder still under Termux PRoot. Building on top, all of that is free and the two days go to the part that is ours: the office, pets, board and animations.

## Name and command

| | Value |
| --- | --- |
| Name | **Tomville** (Tom + ville) |
| Command | `tomville`, short alias `tmv` |
| Package (PyPI) | `tomville`: free on PyPI and GitHub (checked 2026-10-16) |
| Repo | https://github.com/DuongAnh1201/tomville (private; old `pixel-office` links redirect) |
| Local folder | `~/tomville` |
| Settings | `~/.config/tomville/settings.toml`, env vars `TOMVILLE_*` |

Names we dropped: *Pixel Office* (didn't like it), *paddock* (`paddock` and `pdk` taken on PyPI), `tv` as the alias (clashes with the "television" fuzzy finder).

### How it becomes a command

1. `pyproject.toml` lists the commands and the function each runs:
   ```toml
   [project]
   name = "tomville"

   [project.scripts]
   tomville = "tomville.cli:main"
   tmv      = "tomville.cli:main"
   ```
2. `uv tool install --editable .` gives the app its own Python environment and writes `tomville` and `tmv` launchers into `~/.local/bin`, which is already on `PATH`.
3. `--editable` points the launchers at the code folder, so edits work on the next run without reinstalling.
4. Later, publishing to PyPI makes it `uv tool install tomville` for anyone, plus a one-line `install.sh`.

## What herdr gives us

Checked on this tablet with herdr 0.9.5.

### Agent status: 5 values

| Status | Meaning | Pet |
| --- | --- | --- |
| `working` | Busy on a turn | At its desk, typing |
| `blocked` | herdr saw an approval or question on screen: it needs **you** | Jumps with `❗`; the most important one to see |
| `done` | Finished, and the result has not been looked at | Walks to the review zone |
| `idle` | Ready, and the result has been seen | Lounge, then sleeps |
| `unknown` | An agent is there, but herdr can't classify it | Stands still with `?` |

- `done` → `idle` happens when someone focuses the agent. `Enter` on a pet should do the same.
- No agent in a pane is not a status: the agent just leaves `herdr agent list` (pet walks out the door).
- herdr can be wrong: it may miss an unfamiliar approval screen, and some agents (Antigravity, Grok) show `idle` while background jobs run. Show `unknown` honestly; never guess.
- herdr knows 24 agent kinds (claude, codex, gemini, cursor, copilot, opencode, amp, qwen, kimi, …), so every kind needs a default pet.

### Real `herdr agent list` output

From inside herdr, with only this Claude session running:

```json
{"id":"cli:agent:list","result":{"type":"agent_list","agents":[{
  "agent":"claude","agent_status":"working",
  "agent_session":{"agent":"claude","kind":"id","source":"herdr:claude","value":"2810c32f-…"},
  "pane_id":"w1:p1","tab_id":"w1:t1","workspace_id":"w1","terminal_id":"term_65e02e…",
  "cwd":"/root","foreground_cwd":"/root","focused":true,
  "revision":1,"state_change_seq":6,
  "terminal_title":"◑ Permission and GitHub config","terminal_title_stripped":"Permission and GitHub config"}]}}
```

**Named agents** (checked 2026-10-17 after `herdr agent start codex1 --kind codex …`): `agent` is always the **kind** and the given name is in a separate **`name`** field. An agent started by hand (like the lead) has no `name`:

```json
{"name":"codex1","agent":"codex","agent_status":"idle","pane_id":"w4:p1","cwd":"/root/.herdr/worktrees/tomville/m2-events", …}
{"agent":"claude","agent_status":"working","pane_id":"w1:p1","cwd":"/root", …}
```

So Tomville uses `name` when present, else the kind (`Agent.from_herdr` does this). Two unnamed agents of the same kind would clash, so every worker should be started with a name. Right after start, an agent can show `blocked` for a moment before it settles to `idle`.

### Live event stream

`events.subscribe` in the herdr API pushes events such as `pane.agent_status_changed` (pane, agent, new status), `pane.agent_detected`, `pane.created`, `pane.closed` and `pane.focused`. Tomville listens to it instead of polling, which is faster and easier on the battery. Polling `herdr agent list` every `poll_seconds` is the fallback.

### How agents work together in herdr

herdr has no chat channel, shared memory or task list. Agents use each other's terminals through the same commands:

| Command | Use |
| --- | --- |
| `herdr agent prompt NAME "…" --wait` | Type a prompt into another agent and wait until it settles |
| `herdr agent read NAME` | Read its screen; long answers go through a file |
| `herdr agent wait NAME --until blocked` | Wait for a status |
| `herdr agent send-keys NAME esc` | Press keys in its UI |
| `herdr worktree …` | Give each worker its own git worktree |
| `herdr --machine LABEL …` | The same, on another machine over SSH |

herdr sets `HERDR_WORKSPACE_ID`, `HERDR_TAB_ID` and `HERDR_PANE_ID` in every pane, so a command knows which pane it runs in.

## User journey

1. **Install**: `uv tool install git+https://github.com/DuongAnh1201/tomville` (later the one-line `install.sh`).
2. **Create a new ville**: like starting a new game. Inside herdr, in the project folder, run `tmv new` (or just `tomville`, which offers it when the project has no ville). It asks:
   - the ville's name (e.g. "Tom's ville"), shown in the title bar
   - team shape: lead + workers, or pipeline
   - the agents: boss `claude`; workers `codex1`, `codex2` (or pipeline stages)
   - a pet for each (built-in cat, dog, sheep, …)
   - the board: GitHub repo (from `git remote`) or `TASKS.md`, and how often to check it
   - the emoji test row (falls back to ASCII if it doesn't line up)

   Then it saves `.tomville/ville.toml` in the project, creates the GitHub labels, adds the `tmv send` / `tmv task` rules to `CLAUDE.md` / `AGENTS.md`, and installs the Claude hook.
3. **Start the agents** in herdr panes; `tmv doctor` lists who is missing and the command to start them.
4. **Open the ville**: `tmv` in its own herdr tab.
5. **Give prompts**: select the boss (`Tab`), `Enter` to jump to its pane, and give it the goal. The boss creates issues and hands them out; you only talk to the boss. For a pipeline, prompt the first stage.
6. **Watch**: `❗` = needs approval (`Enter` to go there), pets at the boss desk = ready for review, closed issues drop into Done.

## Lead + workers layout

Designed by Tom, 2026-10-17. (Pipeline layout: the conveyor belt in the README, not designed in detail yet.)

```
 ┌ BOARD ───────────────┐           🐱
 │ Todo   Doing  Review │      ┌──────────┐
 │ #14    #12    #9     │      │   BOSS   │
 └──────────────────────┘      └──────────┘

      ┌────────┐       ┌────────┐       ┌────────┐
      │ codex1 │       │ codex2 │       │        │
      └────────┘       └────────┘       └────────┘
          🐶               🐑
```

- **Boss on top**, behind the boss desk, facing the workers. The **board** hangs on the wall next to the boss.
- **One desk per worker**, with the worker's name on it, opposite the boss. Empty desks wait for new workers.
- **The handover**: the boss pushes a task to GitHub (an issue for that worker) → the boss pet walks to that worker's desk → a conversation bubble pops up ("#12 is yours") → the boss walks back and the worker checks the GitHub issues (or `TASKS.md`), bubble "checking issues…" → it takes the task, the card moves to Doing, bubble "on it: #12", and it types.
- **Done**: the worker walks to the boss desk ("#12 ready for review"); when the issue closes, the card drops into Done.
- Changes made through `tmv task` / `tmv send` move pets at once (logged locally); changes on the GitHub website or app show up on the next board check.

## Team shapes

Any agent can prompt any other, so the team shape is up to us. v1 draws two:

1. **Lead + workers** (default): the lead at the front desk hands tasks to workers at the desks around it.
2. **Pipeline**: stations in a row joined by a conveyor belt (planner → coder → tester). A card rides the belt on each handoff; a `blocked` stage stops the belt.

Picked with `[team]` in `settings.toml` (`shape`, `lead`, `stages`) or `--team lead|pipeline`. Later: pair/reviewer, parallel fan-out with worktrees, peer group, across machines.

## Task board: GitHub Issues

Decided 2026-10-17: **GitHub Issues is the main board from the start.** We compared it with `TASKS.md`: Issues are slower (Tomville has to ask GitHub) and need a network, but give history, comments, `Fixes #12` links to commits and PRs, and a good view on the phone. The slowness is the user's choice to make, so the check interval is a setting.

- **Card** = open issue. **Column** = label `status:todo` / `status:doing` / `status:review`; closed = done. **Who has it** = label `agent:codex1` (agents aren't GitHub users, so no assignees).
- **Check interval**: `[board] check_seconds` (default 60, minimum 10), `--board-check SEC`, or the `G` key in the app. Lower moves cards sooner; higher saves battery and network.
- Each check is one API call with `ETag`: an unchanged board returns `304` and doesn't use rate limit. Offline, the board keeps its last cards and shows `offline since …`.
- Agents use `tmv task new/take/move/list`, which call `gh` underneath, instead of long `gh issue edit … --add-label …` commands. Fewer tokens and fewer mistakes.
- `tmv new` (and `tmv setup` later) creates the labels and adds the board rules to `CLAUDE.md` / `AGENTS.md`.
- **Plug-in**: the board source is swappable like team shapes. `source = "github"` (default) or `"tasks-md"` for offline or quick projects. The office looks the same either way.
- Bugs and ideas outside the current milestone also go to Issues (label `bug` or `idea`), so agents stay on task.

```toml
[board]
source = "github"        # github | tasks-md
check_seconds = 60
repo = ""                # empty = the project's git remote
```

## Who talks to whom

herdr shows *what* each agent is doing, but not *who sent a prompt to whom*: the reply goes only to the sender, and the event stream has no "prompt sent" event or sender field (checked in the API schema). So Tomville keeps its own message log, `.tomville/messages.jsonl`:

| Way | How | Reliable? |
| --- | --- | --- |
| `tmv send NAME "…"` | Agents send work through Tomville; the sender comes from `HERDR_PANE_ID`; Tomville calls `herdr agent prompt` and logs it | Exact, when agents use it. `tmv setup` adds the rule to `CLAUDE.md` / `AGENTS.md` |
| Claude Code hook | A `PreToolUse` hook logs any `herdr agent prompt` Claude runs directly | Exact for Claude as sender. Codex equivalent not checked yet |
| Timing guess | Sender `working`, then target `working` within seconds | Fallback only, shown as `? → codex1` |

In the office: the sender's pet carries `✉` to the target's desk with a speech bubble, the Events panel shows `10:42 claude → codex1: Fix the login test`, and an unknown sender shows `?`.


**Codex hooks** (checked 2026-10-17, Codex CLI 0.163.0): Codex has a hook system too. It is the `hooks` feature (stable, on in `~/.codex/config.toml`), with hooks in `~/.codex/hooks.json` in the same JSON shape as Claude's. herdr's Codex integration already uses a `SessionStart` hook there. Each hook has to be trusted once (a hash in `[hooks.state]`). Not checked yet: whether Codex offers a before-tool event like Claude's `PreToolUse`, and what its payload looks like. Until then, Codex messages are logged when Codex uses `tmv send`, and otherwise the pipeline's timing guess covers them.
## Look and feel

- Retro game in a character grid, movement one cell at a time.
- Built for an 11-inch tablet in Termux, landscape first (~140 × 40 cells); portrait stacks the sidebar under the office.
- Options: frame rate (5/10/15/30, default 10), sprite style (emoji, ASCII, block pixels), a pet and colour per agent, themes (night, game-boy, green-screen).
- Built-in pets: cat, dog, sheep; your own in `~/.config/tomville/sprites/`.
- v1 only watches; a prompt box comes later.

## Scope: two parts

The build is split in two (details in [milestones.md](milestones.md)):

1. **Part 1 · Fundamentals** (target: the two-day weekend): live herdr data, movement, emoji and ASCII sprites, `tmv send` and the message log, CLI essentials, install from GitHub, with the **lead + workers** and **pipeline** shapes only.
2. **Part 2 · More shapes and polish**: pair/reviewer, parallel fan-out with worktrees, peer group, across machines; then custom pets and block pixels, themes, power saving, publishing (PyPI + `install.sh`) and the web UI (`tmv web`).

Part 1 builds the team shape as a plug-in, so Part 2 shapes don't change the core.

## Later updates

Ideas saved for after the current plan. Not in any milestone yet.

- **Pets from online pixel-art sets.** For now pets are chosen normally (built-in cat, dog, sheep in emoji or ASCII). Later:
  - `tmv pets import cat.png --frames 4 --size 8x8 --name ginger`: cut a sprite sheet into frames, shrink it, save it as a block-pixel pet. Uses Pillow and the half-block trick (`▄`, top pixel as background colour, bottom as text colour: 2 pixels per cell), as in the Rich Pixels library.
  - Size is the catch: 16×16 pixels = 16 × 8 cells, too big for the ~128 × 24 office. So shrink to 8×8, or add a "big mode" office, or show full sprites in the web UI.
  - A community pet gallery (a GitHub repo of CC0 pets): `tmv pets install fox`.
  - Licence: ship only CC0 art inside the package. Candidates: OpenGameArt "Cat & Dog Free Sprites" (opengameart.org/node/48447), itch.io CC0 sets (zeenaz "Free Pixel Animation – Cat", rmazanek "Dog"). Avoid vscode-pets art: some came from paid packs.
- From the walkthrough, not yet decided: `tmv up` (start the whole team in herdr panes from settings), `tmv task assign 12 codex1`, a `P` key to prompt the selected pet from the office.

## Development setup

- Ubuntu 26.04 in Termux PRoot, aarch64; Python 3.14.4; herdr 0.9.5; Claude Code and Codex logged in; `gh` logged in as DuongAnh1201 over HTTPS.
- Work inside herdr, so agents show up in `herdr agent list` and can control each other. Outside herdr, `HERDR_ENV` is unset and the herdr integration can't report status.
- `uv` is not installed yet: `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- Before CI work: the `gh` token lacks the `workflow` scope (`gh auth refresh -s workflow`), needed to push `.github/workflows/*`.

## Open questions

- Which pet and colour for each agent?
- Licence: MIT, or another?
- Which default for `check_seconds` feels right on the tablet: 30 or 60?
- Does Codex have a before-tool hook event (like Claude's `PreToolUse`) to log its direct `herdr agent prompt` calls?
