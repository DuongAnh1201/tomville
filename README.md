# Proposal: Tomville, a retro game view of the agent team

2026-10-16 · Tom Nguyen

## Summary

Build a terminal app where each agent (Claude, Codex) is a pixel pet walking around a retro office. Its movement shows what the agent is doing. The app reads live status from herdr, which is already installed, and the task board from `TASKS.md`, so v1 needs no change to the agent setup.

- **Look:** a retro game in a character grid, with movement one cell at a time.
- **Screen:** designed for an 11-inch tablet in Termux, landscape first.
- **Options:** frame rate, sprite style (emoji, ASCII, block pixels), and a pet for each agent.
- **Built with:** Python + [Textual](https://textual.textualize.io/), running in its own herdr tab.

Two ways to use it, built in this order:

| Phase | What | When |
| --- | --- | --- |
| 1. CLI | `tomville` / `tmv`: the office in the terminal, plus one-shot commands | The two-day weekend build |
| 2. Publish | One-line install, like herdr: `curl -fsSL …/install.sh \| sh`, plus PyPI | Right after the weekend |
| 3. Web UI | The same office in a browser: `tmv web` | Later |

Both the CLI and the web UI use one shared core (event reader, world model, sprites, settings), so the web UI adds a new front end, not a second app. See [Roadmap](#roadmap).

## Prerequisites

All in place on the development tablet (Ubuntu 26.04 in Termux PRoot, aarch64):

- [x] herdr 0.9.5 in `~/.local/bin`, on `PATH`
- [x] herdr integrations for Claude and Codex (`herdr integration install claude|codex`)
- [x] herdr agent skill in `~/.claude/skills/herdr/SKILL.md`
- [x] Claude Code and Codex CLI, both logged in
- [x] `gh` logged in, with access to this repo

Still needed at build time: Python 3.11+ and `uv` (install steps in [Install](#install)).

## What it looks like

Landscape on an 11-inch tablet, about 140 × 40 cells:

```
┌ Tomville · myproject ─────────────────────────────────────────┬ Team ──────────────────────────┐
│ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ │ 🐱 claude  lead    working     │
│ ▓  DESKS              ▓  REVIEW         ▓  DONE              ▓ │ 🐶 codex1  worker  BLOCKED !   │
│ ▓  ┌──┐  ┌──┐  ┌──┐   ▓  ┌────────┐     ▓  ┌────────┐        ▓ │ 🐑 codex2  worker  idle        │
│ ▓  └──┘  └──┘  └──┘   ▓  │  T1    │     ▓  │        │        ▓ ├ Board ─────────────────────────┤
│ ▓  🐱⌨                ▓  └────────┘     ▓  └────────┘        ▓ │ Todo   Doing  Review  Done     │
│ ▓                     ▓      🐶❗        ▓                    ▓ │ T3     T2     T1              │
│ ▓        LOUNGE  🛋    ▓                 ▓                    ▓ │               PR #4           │
│ ▓          🐑 z z      ▓                 ▓                    ▓ ├ Events ────────────────────────┤
│ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ │ 10:42 codex1 needs approval    │
│                                                                │ 10:40 claude assigned T2       │
└────────────────────────────────────────────────────────────────┴────────────────────────────────┘
 [F]ps 10  [S]prites emoji  [T]heme night  [Tab] next agent  [Enter] open pane  [?] help
```

In portrait, the sidebar moves under the office floor.

## How agent status becomes pet behaviour

| herdr status | Pet goes to | Animation | Extra |
| --- | --- | --- | --- |
| `working` | Its desk | Typing: 2 frames, keys flicker | Task ID in a speech bubble |
| `blocked` | Stays where it is | Jumps, `❗` blinks | Name turns red in the Team list; event logged |
| `done` | Review zone | Walks over, drops its card | Card appears on the board's Review column |
| `idle` | Lounge | Wanders slowly, then sleeps (`z z`) | Sleeps after 60 s idle |
| `unknown` | Stays where it is | Stands still, `?` bubble | |
| Agent gone | Leaves through the door | Walks off-screen | Removed from the Team list |

When the lead assigns a task (a new `doing` row in `TASKS.md`), the lead pet walks to the worker's desk and hands over a card.

## Team shapes

herdr has no idea of a "team": any agent can prompt any other. Tomville supports two common shapes in v1 and draws a different office for each. You pick the shape in `settings.toml` or with `--team`.

### 1. Lead + workers (default)

One lead hands tasks to workers. The office in [What it looks like](#what-it-looks-like) is this shape: the lead sits at the front desk, workers at the desks around it.

| What happens | How Tomville knows | What you see |
| --- | --- | --- |
| Lead gives a worker a task | A new `doing` row in `TASKS.md` with that worker's name | Lead pet walks to the worker's desk and hands over a card |
| Worker finishes | Worker goes `working` → `done` | Worker carries the card to the review zone |
| Lead reviews | Card moves to `review`/`done` in `TASKS.md` | Card moves on the board; lead pet visits the review zone |

### 2. Pipeline

Each agent does one step and passes the work on, for example planner → coder → tester. The office is a row of stations joined by a conveyor belt:

```
 ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
 ▓   PLAN            CODE             TEST             DONE  ▓
 ▓   ┌──┐            ┌──┐             ┌──┐             ┌──┐  ▓
 ▓   └──┘            └──┘             └──┘             └──┘  ▓
 ▓   🐱 z z          🐶⌨               🐑❗                     ▓
 ▓  ═════▶══════════[T1]▶═════════════▶════════════════▶═══  ▓
 ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
```

| What happens | How Tomville knows | What you see |
| --- | --- | --- |
| A step finishes and the next starts | Stage N goes `done` and stage N+1 goes `working` within 30 s | The card rides the belt to the next station |
| A step is stuck | That stage is `blocked` | Its pet jumps with `❗`; the belt stops behind it |
| The last step finishes | Last stage goes `done` | Card drops into DONE |

The status table above still applies to each pet; the shape only changes where desks are and how cards move.

### Settings

```toml
[team]
shape = "lead"                          # lead | pipeline
lead = "claude"                         # lead shape: who sits at the front desk

# pipeline shape: stage order, left to right
# shape = "pipeline"
# stages = ["planner", "coder", "tester"]
```

If `[team]` is missing, Tomville uses the lead shape with the first agent it sees as the lead. Agents not listed in `stages` wait in the lounge.

Other shapes (pair/reviewer, parallel fan-out with worktrees, peer group, across machines) are in [Later](#later-any-phase).

## Who talks to whom

herdr shows what each agent is doing, but not who sent a prompt to whom: when the lead runs `herdr agent prompt codex1 "..."`, only the lead gets a reply, and herdr's event stream has no "prompt sent" event or sender field (checked against the herdr 0.9.5 API schema). Tomville records messages itself, in a log both shapes use:

| Way | How it works | Reliability |
| --- | --- | --- |
| `tmv send` | Agents send work with `tmv send codex1 "Fix the login test"`. Tomville finds the sender from `HERDR_PANE_ID` (herdr sets it in every pane), calls `herdr agent prompt` itself and appends the message to the log | Exact, when agents use it. `tmv setup` adds a short rule to the project's `CLAUDE.md` and `AGENTS.md` telling agents to use it |
| Claude Code hook | A `PreToolUse` hook on Bash catches any `herdr agent prompt …` Claude runs directly and logs it with the sender's pane | Exact for Claude as sender, even if it forgets `tmv send`. `tmv setup` installs it. Codex: check whether it has an equivalent hook |
| Timing guess | Sender was `working`, then the target became `working` within a few seconds | Fallback only; shown as `? → codex1` |

The log is one JSON line per message in `.tomville/messages.jsonl` in the project:

```json
{"time": "2026-10-17T10:42:03Z", "from": "claude", "to": "codex1", "text": "Fix the login test", "via": "send"}
```

What you see:

- The sender's pet walks to the target's desk carrying `✉`; a speech bubble shows the start of the prompt.
- The Events panel shows `10:42 claude → codex1: Fix the login test`.
- In the pipeline shape, a logged handoff moves the card at once; the timing guess is used only when there is no log line.
- An unknown sender shows as `?`, so the office never claims more than it knows.

## Architecture

```
 herdr events (status changes) ─┐
 messages.jsonl (tmv send, hook)├─▶  Event reader  ─▶  World model  ─▶  Renderer (Textual)  ─▶  screen
 TASKS.md (mtime check)         ─┘                      pets, zones,       sprite frames,
                                                        targets, paths     frame timer
                                                              ▲
                                          settings.toml ──────┘  (fps, sprite style, pets)
```

| Part | Job |
| --- | --- |
| Event reader | Runs `herdr agent list` once at start, then listens to herdr's live event stream (`pane.agent_status_changed`, `pane.agent_detected`, `pane.closed`) instead of polling. Also follows the message log and reads `TASKS.md` when it changes. Turns them into events: "codex1 became blocked", "claude → codex1: Fix the login test", "T1 moved to review". Falls back to polling `herdr agent list` every `poll_seconds` if the stream drops |
| World model | Holds each pet's position, target zone and current animation. Events change targets; it does not draw anything |
| Movement | Each tick, a pet steps one cell toward its target: first along x, then along y, around walls |
| Renderer | A Textual widget that draws the office map, then each pet's current frame at its position. Textual only redraws changed cells |
| Settings | `settings.toml`, changed in the app with hotkeys or from the shell with `tmv config set` |

The renderer never calls herdr directly, and the event reader never draws. That keeps the game part testable with fake events and no agents running.

## Frame rate option

Movement speed is set in cells per second and does not depend on fps. Changing fps only changes how smooth it looks, not how fast pets move.

| Option | Feel | Use when |
| --- | --- | --- |
| 5 fps | Choppy, very retro | Battery saver |
| 10 fps (default) | Classic handheld game | Normal use |
| 15 fps | Smooth walking | Tablet plugged in |
| 30 fps | Smoothest | Testing; heavy on battery under PRoot |

Two automatic savings:

- When every agent is idle and every pet is asleep, the app drops to 2 fps.
- When the app's tab is not visible, it stops animating and only keeps polling.

Press `F` to cycle through the options; the choice is saved.

## Emoji width on an 11-inch screen

The core rule: **every map tile is 2 cells wide.** Emoji are 2 cells wide in most terminals, so one emoji fills one tile. ASCII and block sprites also use 2-cell tiles. All three styles share the same map and stay aligned.

How it stays aligned:

1. **Fixed pet list.** Pets come only from a tested list of 2-cell emoji (🐱 🐶 🐑 🐸 🦊 🐼 🤖 👾). Skip emoji built from several parts (skin tones, `🧑‍💻`), because they render at different widths on different fonts.
2. **Width check at start.** The app measures each sprite with Rich's `cell_len`. Anything that is not exactly 2 cells is replaced by its ASCII version, with a note in the Events panel.
3. **First-run calibration screen.** It shows a ruler and a row of every pet:
   ```
   |..|..|..|..|..|..|..|..|
   |🐱|🐶|🐑|🐸|🦊|🐼|🤖|👾|
   ```
   If the bars line up, press Enter. If not, the app switches to ASCII sprites. This catches fonts that measure differently from what Python expects.
4. **Screen size.** The map is 64 tiles × 24 rows (128 × 24 cells) on an 11-inch landscape screen at a normal Termux font size. Smaller windows get a 40 × 20 tile map, and the sidebar moves below it. Pinch-zoom in Termux changes the cell count, and the app re-lays out on resize.

## Sprite styles

Press `S` to cycle through styles. Each pet has the same frames in each style.

| Style | Idle | Walk frames | Typing | Notes |
| --- | --- | --- | --- | --- |
| Emoji | `🐱` | `🐱` / `🐱` with a dust `·` behind it | `🐱⌨` | Default on the tablet |
| ASCII | `^^` | `^^` / `^-` | `^^#` | Works on every font |
| Block pixel | `▟▙` | `▟▙` / `▙▟` | `▟▙▒` | Most "retro game" |

Sprites are plain text files, one folder per pet. Built-in pets ship inside the package; your own go in `~/.config/tomville/sprites/` (see [Custom pets and colours](#custom-pets-and-colours)):

```
src/tomville/data/sprites/
  cat/
    emoji.txt     # frames separated by a line with ---
    ascii.txt
    blocks.txt
  dog/ ...
```

`~/.config/tomville/settings.toml`:

```toml
fps = 10
style = "emoji"          # emoji | ascii | blocks
idle_sleep_seconds = 60
poll_seconds = 1

[pets.claude]
sprite = "cat"

[pets.codex1]
sprite = "dog"

[pets.codex2]
sprite = "sheep"
```

Colours and your own pet designs are covered in [Custom pets and colours](#custom-pets-and-colours).

## Interaction

| Key or touch | Action |
| --- | --- |
| Tap a pet, or `Tab` | Select it; the Team list highlights it |
| `Enter` on a selected pet | Switch herdr to that agent's pane (to approve, read output) |
| `F` | Cycle frame rate |
| `S` | Cycle sprite style |
| `B` | Show the board full-screen |
| `T` | Cycle colour themes |
| `?` | Help |

v1 only watches. Approvals still happen in the agent's own pane: the blocked pet tells you where to go, and `Enter` takes you there. Sending prompts from the app comes later (see [Later](#later-any-phase)).

## Custom pets and colours

You can design both the pet and its colours. How much depends on the sprite style:

| Style | Shape | Colour |
| --- | --- | --- |
| Emoji 🐱 | Pick from the tested emoji list | Fixed by the font. Only the name label takes a colour |
| ASCII `^^` | Any characters | One colour per pet |
| Block pixel `▟▙` | Draw pixel by pixel | Any colour, per pixel. Best for your own designs |

Termux supports 24-bit colour, so any hex colour works.

### Sprite file format

Each frame has two grids side by side: the shape on the left, colour letters on the right. A `[palette]` maps each letter to a hex colour. Frames are separated by `---`.

`~/.config/tomville/sprites/fox/blocks.txt`:

```
# shape        # colours
 ▄▀▀▄           OOOO
 █▄▄█           OWWO
 ▀  ▀           B  B
---
 ▄▀▀▄           OOOO
 █▄▄█           OWWO
  ▀▀             BB

[palette]
O = "#ff8800"   # orange fur
W = "#ffffff"   # white face
B = "#5a3a1a"   # brown feet
```

Rules:

- A pet is a whole number of 2-cell tiles wide; this fox is 2 tiles (4 cells).
- Every frame of one pet has the same size.
- A space in the colour grid means "no colour".
- The first frame is used when standing still; all frames play in a loop when moving or working.

Your own pets go in `~/.config/tomville/sprites/<name>/` and override a built-in pet with the same name. Run `tomville pets list` to preview them all, and `tomville pets check <name>` to find mistakes in a pet file.

### Colours and themes

In `~/.config/tomville/settings.toml`:

```toml
theme = "night"          # night | game-boy | green-screen

[pets.claude]
sprite = "cat"
color  = "#f5a97f"       # the agent's colour: ASCII pet, name, board cards, events

[pets.codex1]
sprite = "fox"           # your own design
```

Three built-in themes. Press `T` in the app to cycle them.

## Install and setup from the terminal

One command installs it, and `tomville doctor` shows the whole setup in the terminal: what is ready, what is missing, and the command to fix it.

### Install

After publishing (phase 2), one line, the same way herdr installs:

```bash
curl -fsSL https://raw.githubusercontent.com/DuongAnh1201/tomville/main/install.sh | sh
```

Or, for people who already use Python tools:

```bash
uv tool install tomville     # or: pipx install tomville
```

Update with `tmv update`; remove with `tmv uninstall`. Settings in `~/.config/tomville/` stay.

During the weekend build (phase 1), install straight from GitHub:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install git+https://github.com/DuongAnh1201/tomville
```

While the repo is private, this works only where `gh` is logged in with access, as on the development tablet.

## CLI

`tomville` works like `claude` and `codex`: run it bare for the interactive app, add options to change how it runs, or use a command for a one-shot job that prints and exits. The installer also adds a short alias, `tmv`.

```
tomville [options]              open the office (interactive)
tomville <command> [options]    run one command and exit
tomville <command> --help       help for one command
```

Every option is optional. With none, settings come from `settings.toml`, then built-in defaults.

### Global options (any command)

| Option | Default | What it does |
| --- | --- | --- |
| `-C, --project DIR` | current folder | Project whose `TASKS.md` is shown |
| `--config FILE` | `~/.config/tomville/settings.toml` | Use another settings file |
| `--json` | off | Machine-readable output, for scripts and agents |
| `--no-color` | off | Plain text; also on when `NO_COLOR` is set |
| `-q, --quiet` / `-v, --verbose` | normal | Less or more output |
| `-h, --help` | | Show help |
| `-V, --version` | | Show the version |

### Office options (bare `tomville`)

| Option | Values | What it does |
| --- | --- | --- |
| `--fps N` | `5` `10` `15` `30` | Frame rate for this run |
| `--style S` | `emoji` `ascii` `blocks` | Sprite style |
| `--theme T` | `night` `game-boy` `green-screen` | Colour theme |
| `--pet AGENT=PET` | e.g. `codex1=fox` | Pet for one agent; repeat for more |
| `--board FILE` | path | A board file other than `TASKS.md` |
| `--layout L` | `auto` `landscape` `portrait` | Force a layout |
| `--team SHAPE` | `lead` `pipeline` | Team shape for this run (see [Team shapes](#team-shapes)) |
| `--poll SEC` | number | Polling interval if herdr's event stream is unavailable (default 1) |
| `--demo` | | Fake agents and tasks; works without herdr. Good for trying pets and themes |
| `--still` | | No animation; pets jump straight to their zone |

### Commands

| Command | What it does | Useful options |
| --- | --- | --- |
| `send AGENT TEXT` | Prompt another agent and log who sent it (see [Who talks to whom](#who-talks-to-whom)). For agents to use instead of `herdr agent prompt` | `--wait`, `--timeout MS` (passed to herdr) |
| `status` | Print the team and board once, then exit. Like `claude -p`: no app opens | `--json`, `--watch [SEC]` (reprint every N s), `--agent NAME` |
| `doctor` | Check the setup and print fixes | `--json` |
| `setup` | Calibrate emoji width and write settings with a pet per running agent | `--yes` (accept defaults, no questions), `--style`, `--theme` |
| `pets list` | Show every pet, animated | `--style` |
| `pets show NAME` | Show one pet's frames and palette | `--style`, `--fps` |
| `pets new NAME` | Create a pet file to edit | `--from cat` (copy a built-in), `--size 2x3` (tiles × rows) |
| `pets check NAME` | Check a pet file: sizes, palette letters, emoji width | |
| `theme list` | Preview all themes | |
| `config path` / `config show` | Print the settings file location or contents | |
| `config get KEY` / `config set KEY VALUE` | Read or change one setting, e.g. `config set fps 15` | |
| `update` (phase 2) | Upgrade to the latest release, like `herdr update` | `--check` (only report) |
| `uninstall` (phase 2) | Remove the app; keep or delete settings | `--purge` (also delete `~/.config/tomville/`) |
| `web` (phase 3) | Serve the office in a browser | `--port 8787`, `--host 127.0.0.1` |
| `completion SHELL` (later) | Print tab-completion for `bash`, `zsh` or `fish` | |

### Where settings come from

The highest line wins:

1. Command-line options (`--fps 15`)
2. Environment variables: `TOMVILLE_FPS`, `TOMVILLE_STYLE`, `TOMVILLE_THEME`, `TOMVILLE_CONFIG`
3. `~/.config/tomville/settings.toml`
4. Built-in defaults

So `--fps 30` tries 30 fps once, and `tomville config set fps 30` keeps it.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | OK |
| `1` | Problem found (`doctor`, a broken pet file) or runtime error |
| `2` | Wrong command or option |

Same convention as herdr, so scripts can check the result.

### Examples

```bash
tomville                                      # open the office
tmv --demo --theme game-boy                   # try it with fake agents
tmv --style blocks --pet codex1=fox --fps 15  # one-off look
tmv status                                    # quick text summary
tmv status --watch 5                          # live summary in a small pane
tmv status --json                             # for scripts and agents
tmv doctor
tmv pets new fox --from cat && tmv pets check fox
tmv config set theme night
```

`tmv status` output:

```
myproject · 3 agents · 3 tasks
  🐱 claude   lead    working   T2 Write tests for login
  🐶 codex1   worker  blocked   T1 Add login form   ← needs approval
  🐑 codex2   worker  idle
  Todo 1 · Doing 1 · Review 1 · Done 0
```

### Agents can use it too

Because `status --json` prints the team and board as JSON, Claude can read it with one command. An optional line for the `duo` skill:

```markdown
- To see the whole team at once, run `tomville status --json`.
```

### Doctor

```
Tomville doctor · v0.1.0

 Environment
  ✔ Python 3.12.3
  ✔ Terminal 142 × 41 cells, 24-bit colour
  ✔ Emoji width calibrated (emoji style)

 herdr
  ✔ herdr 0.9.5 at /root/.local/bin/herdr
  ✔ Running inside herdr (HERDR_ENV=1)
  ✔ Claude integration installed
  ✔ Codex integration installed

 Agents
  ✔ claude   (cat, #f5a97f)
  ✖ codex1   not running → herdr agent start codex1 --kind codex --pane <pane>

 Board
  ✔ TASKS.md found (3 tasks)

 Settings  ~/.config/tomville/settings.toml
 Sprites   ~/.config/tomville/sprites/ (1 custom pet)

 1 problem found.
```

Required: Python, herdr, and running inside herdr. Everything else is a warning; the office still starts and shows what it can.

## Tech stack

Kept small so it fits in two days.

| Layer | Choice | Why |
| --- | --- | --- |
| Language | Python 3.11+ | Already on Ubuntu; `tomllib` built in |
| Terminal UI | [Textual](https://textual.textualize.io/) + [Rich](https://rich.readthedocs.io/) | Layouts, touch, animation timers, 24-bit colour, `cell_len` for emoji width |
| CLI | `argparse` (standard library) with subcommands; two entry points, `tomville` and `tmv` | Options and commands with built-in `--help`; no extra dependency |
| Settings | TOML: `tomllib` to read, `tomli-w` to write | Human-editable, same format as Codex and herdr |
| Agent status | `herdr agent list` (JSON via `subprocess`) | Uses the existing setup; no extra server |
| Board | `TASKS.md`, re-read when its modified time changes | No file-watching library needed |
| Packaging | `pyproject.toml` + hatchling; [uv](https://docs.astral.sh/uv/) | One command to install, update, remove |
| Tests | pytest for the world model, sprite loader and doctor | The game logic is tested with fake events, no agents needed |

Dependencies: `textual` and `tomli-w` only.

## Project layout

```
tomville/
  pyproject.toml
  README.md
  install.sh         # one-line installer (phase 2)
  CHANGELOG.md
  src/tomville/
    cli.py           # argparse: office options + status, doctor, setup, pets, theme, config
    core/            # shared by CLI and web; no UI code here
      events.py      # herdr event stream + messages.jsonl + TASKS.md -> events
      messages.py    # tmv send, message log, hook entry point
      world.py       # pets, zones, targets, movement
      sprites.py     # load sprite files, palette, width check
      settings.py    # read/write settings.toml
      doctor.py      # checks shared by doctor and setup
    tui/             # phase 1: terminal front end
      app.py         # Textual app, layout, keys
      office.py      # renderer: office map + sprites widget
      status.py      # status output, text and JSON
    web/             # phase 3: browser front end
    data/
      sprites/       # built-in pets: cat, dog, sheep
      themes/        # night, game-boy, green-screen
      office.txt     # the floor plan, drawn as text
  tests/
```

User files live outside the package, so updates never overwrite them: `~/.config/tomville/settings.toml` and `~/.config/tomville/sprites/`.

## Two-day plan

> The build is now tracked in two parts in [milestones.md](milestones.md): Part 1 (fundamentals, lead + workers and pipeline) and Part 2 (other team shapes, custom pets, themes, publishing). The table below is the original plan; where they differ, `milestones.md` wins.

**Day 1: a live, moving office**

| Block | Build | Done when |
| --- | --- | --- |
| Morning | Project skeleton, `pyproject.toml`, office map, Textual layout (office + Team + Board + Events) | `tomville` opens the empty office |
| Midday | Event reader: `herdr agent list` + herdr event stream + `TASKS.md` into events | Team list and board show real data |
| Afternoon | World model: zones, status-to-behaviour table, cell-by-cell movement, fps option (`F`); lead + workers shape | Pets walk to their desk when you start Claude or Codex |
| Evening | Emoji and ASCII sprites, built-in cat, dog and sheep | Style switch (`S`) works; tests for the world model pass |

**Day 2: your own pets, setup and install**

| Block | Build | Done when |
| --- | --- | --- |
| Morning | Pipeline shape: conveyor office map, `[team]` settings, `--team`; `tmv send`, message log, Claude Code hook; handoff detection | `tmv send` moves an envelope and a card from planner to coder to tester |
| Midday | Block-pixel sprite format with palettes; custom pets folder; `pets list`, `pets show`, `pets new`, `pets check` | Your own fox walks around in its colours |
| Afternoon | Themes (`T`), agent colours, emoji width check and calibration screen | Map stays aligned on the 11-inch screen |
| Evening | CLI: office options, `status` (with `--json`, `--watch`), `doctor`, `setup`, `config`, `theme list`; `tmv` alias | `tmv status --json` and `tmv doctor` work; `--help` lists every option |
| Late | Tap to select, `Enter` to open the pane, idle power saving; install test with `uv tool install` from GitHub | Fresh install works end to end |

If day 1 runs late, drop block-pixel sprites from day 2 first: emoji and ASCII are enough to use the app.

Each day ends with a usable app.

## Roadmap

### Phase 2: publish the CLI (right after the weekend)

Goal: anyone installs it with one line, updates with `tmv update`, the same experience as herdr.

| Step | What | Done when |
| --- | --- | --- |
| 1. Name | `tomville` is free on PyPI and GitHub (checked 2026-10-16); pick a licence (MIT suggested) | Name and `LICENSE` in the repo |
| 2. Package | Version `0.1.0` in `pyproject.toml`, `CHANGELOG.md`, project links | `uv build` makes a wheel that installs cleanly |
| 3. Installer | `install.sh`: checks OS and arch, installs `uv` if missing, runs `uv tool install tomville`, prints the PATH line if needed | Works on Ubuntu (x86_64 and aarch64), macOS, Termux PRoot |
| 4. Update and uninstall | `tmv update` and `tmv uninstall` call `uv tool upgrade/uninstall` | Update from 0.1.0 to 0.1.1 works |
| 5. CI | GitHub Actions: lint and tests on every push | Green check on `main` |
| 6. Release | Push tag `v0.1.0` → Actions builds, publishes to PyPI (trusted publishing, no token) and creates a GitHub Release with the changelog | `uv tool install tomville` works on a clean machine |
| 7. Go public | Make the repo public; README starts with the one-line install | The install line works for anyone |

How it compares to herdr:

| | herdr | Tomville |
| --- | --- | --- |
| One-line install | `curl -fsSL https://herdr.dev/install.sh \| sh` | `curl -fsSL https://raw.githubusercontent.com/DuongAnh1201/tomville/main/install.sh \| sh` |
| What it installs | A Rust binary per platform | A Python app via `uv`, any platform with Python 3.11+ |
| Self-update | `herdr update` | `tmv update` |
| Releases | GitHub Releases | GitHub Releases + PyPI |

A short install domain (like `herdr.dev`) and standalone binaries without Python are optional extras for later.

### Phase 3: web UI (later)

The same office in a browser, for a bigger screen or to watch from another device.

| Step | What |
| --- | --- |
| 1. Quick version | `tmv web` runs the existing Textual app in the browser with `textual serve`. Almost no new code |
| 2. Real web UI | A small server (FastAPI) streams world events from `core/` over a WebSocket; the page draws pets on a pixel canvas, with real pixel art instead of characters |
| 3. Extras | Drag-and-drop board, pet editor in the browser, view from a phone on the same Wi-Fi |

Rules for phase 1 that keep phase 3 easy:

- All logic lives in `core/`; `tui/` only draws and handles keys.
- The world model emits plain events (dicts), so the web server can send the same events as JSON.
- `status --json` uses the same event format, so it doubles as the web API's data shape.

### Later (any phase)

- Pet editor: paint pets by tapping cells.
- Prompt box that sends tasks to the lead (`herdr agent prompt claude "..."`).
- GitHub Projects board instead of `TASKS.md`.
- Full setup wizard with live previews; more themes.
- Shell tab-completion (`tomville completion bash|zsh|fish`).
- More team shapes: pair/reviewer (two facing desks), parallel fan-out with git worktrees, peer group, and agents on other machines (`herdr --machine`).

## Risks

| Risk | Effect | Fallback |
| --- | --- | --- |
| `herdr agent list` output changes in a herdr update | Pets freeze or vanish | The event reader is one small file; test after `herdr update` |
| Emoji width differs on the tablet font | Map tiles shift | Calibration screen; ASCII style |
| Agents call `herdr agent prompt` directly instead of `tmv send` | Sender unknown (`?`) | Rule in `CLAUDE.md`/`AGENTS.md`; Claude hook logs it anyway; timing guess as fallback |
| Battery drain under PRoot | Tablet gets warm | 10 fps default; auto 2 fps when idle; 5 fps saver |
| herdr event stream drops or changes | Pets stop updating | Fall back to polling `herdr agent list`; raise `poll_seconds` to 2–3 (`--poll 3`) |
| Repo stays private | Others cannot install it | Phase 2, step 7: make it public |
| `install.sh` runs on unknown machines | Install fails or surprises users | Script stays short and readable; it only installs `uv` and the app |

## Decided

- Name: Tomville. Command `tomville`, short alias `tmv`; settings in `~/.config/tomville/`.
- Messages are logged by Tomville (`tmv send` + Claude Code hook), because herdr does not record senders.
- Status comes from herdr's event stream, with polling as a fallback.
- v1 team shapes: lead + workers, and pipeline. Other shapes come later.
- Tomville builds on top of herdr, not as a replacement. herdr still runs the panes, sessions and agent status; Tomville reads that status and draws it, running in its own herdr tab.
- v1 is watch-only; the prompt box comes later.
- Built-in pets: cat, dog, sheep. Built-in themes: night, game-boy, green-screen.
- Landscape first; portrait stacks the sidebar under the office.

## Open questions

- [ ] Which pet and colour for each agent?
- [ ] Licence: MIT, or another?
