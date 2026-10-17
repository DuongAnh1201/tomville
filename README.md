# Proposal: Pixel Office, a retro game view of the agent team

2026-10-16 · Tom Nguyen

## Summary

Build a terminal app where each agent (Claude, Codex) is a pixel pet walking around a retro office. Its movement shows what the agent is doing. The app reads live status from herdr, which is already installed, and the task board from `TASKS.md`, so v1 needs no change to the agent setup.

- **Look:** a retro game in a character grid, with movement one cell at a time.
- **Screen:** designed for an 11-inch tablet in Termux, landscape first.
- **Options:** frame rate, sprite style (emoji, ASCII, block pixels), and a pet for each agent.
- **Built with:** Python + [Textual](https://textual.textualize.io/), running in its own herdr tab.

## What it looks like

Landscape on an 11-inch tablet, about 140 × 40 cells:

```
┌ Pixel Office · myproject ─────────────────────────────────────┬ Team ──────────────────────────┐
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
 [F]ps 10  [S]prites emoji  [Tab] next agent  [Enter] open pane  [?] help
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

## Architecture

```
 herdr agent list (JSON)  ─┐
                           ├─▶  State poller  ─▶  World model  ─▶  Renderer (Textual)  ─▶  screen
 TASKS.md (file watch)    ─┘     every 1 s         pets, zones,       sprite frames,
                                                   targets, paths     frame timer
                                                         ▲
                                     settings.toml ──────┘  (fps, sprite style, pets)
```

| Part | Job |
| --- | --- |
| State poller | Runs `herdr agent list` every 1 s and reads `TASKS.md` when it changes. Turns them into events: "codex1 became blocked", "T1 moved to review" |
| World model | Holds each pet's position, target zone and current animation. Events change targets; it does not draw anything |
| Movement | Each tick, a pet steps one cell toward its target: first along x, then along y, around walls |
| Renderer | A Textual widget that draws the office map, then each pet's current frame at its position. Textual only redraws changed cells |
| Settings | `settings.toml`, editable in the app with hotkeys |

The renderer never calls herdr directly, and the poller never draws. That keeps the game part testable with fake events and no agents running.

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

Sprites live in plain text files, one folder per pet, so you can draw your own:

```
src/pixel_office/data/sprites/
  cat/
    emoji.txt     # frames separated by a line with ---
    ascii.txt
    blocks.txt
  dog/ ...
```

`settings.toml`:

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

v1 only watches. Approvals still happen in the agent's own pane: the blocked pet tells you where to go, and `Enter` takes you there. Sending prompts from the app comes later (see [Later](#later-not-in-the-two-days)).

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

`~/.config/pixel-office/sprites/fox/blocks.txt`:

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

Your own pets go in `~/.config/pixel-office/sprites/<name>/` and override a built-in pet with the same name. Run `pixel-office pets list` to preview them all, and `pixel-office pets check <name>` to find mistakes in a pet file.

### Colours and themes

In `~/.config/pixel-office/settings.toml`:

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

One command installs it, and `pixel-office doctor` shows the whole setup in the terminal: what is ready, what is missing, and the command to fix it.

### Install

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install git+https://github.com/DuongAnh1201/pixel-office
```

This needs the repo to be public, or `gh` logged in with access to it. Update with `uv tool upgrade pixel-office`; remove with `uv tool uninstall pixel-office`. Settings in `~/.config/pixel-office/` stay.

## CLI

`pixel-office` works like `claude` and `codex`: run it bare for the interactive app, add options to change how it runs, or use a command for a one-shot job that prints and exits. The installer also adds a short alias, `pxo`.

```
pixel-office [options]              open the office (interactive)
pixel-office <command> [options]    run one command and exit
pixel-office <command> --help       help for one command
```

Every option is optional. With none, settings come from `settings.toml`, then built-in defaults.

### Global options (any command)

| Option | Default | What it does |
| --- | --- | --- |
| `-C, --project DIR` | current folder | Project whose `TASKS.md` is shown |
| `--config FILE` | `~/.config/pixel-office/settings.toml` | Use another settings file |
| `--json` | off | Machine-readable output, for scripts and agents |
| `--no-color` | off | Plain text; also on when `NO_COLOR` is set |
| `-q, --quiet` / `-v, --verbose` | normal | Less or more output |
| `-h, --help` | | Show help |
| `-V, --version` | | Show the version |

### Office options (bare `pixel-office`)

| Option | Values | What it does |
| --- | --- | --- |
| `--fps N` | `5` `10` `15` `30` | Frame rate for this run |
| `--style S` | `emoji` `ascii` `blocks` | Sprite style |
| `--theme T` | `night` `game-boy` `green-screen` | Colour theme |
| `--pet AGENT=PET` | e.g. `codex1=fox` | Pet for one agent; repeat for more |
| `--board FILE` | path | A board file other than `TASKS.md` |
| `--layout L` | `auto` `landscape` `portrait` | Force a layout |
| `--poll SEC` | number | How often to ask herdr for status (default 1) |
| `--demo` | | Fake agents and tasks; works without herdr. Good for trying pets and themes |
| `--still` | | No animation; pets jump straight to their zone |

### Commands

| Command | What it does | Useful options |
| --- | --- | --- |
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
| `completion SHELL` (later) | Print tab-completion for `bash`, `zsh` or `fish` | |

### Where settings come from

The highest line wins:

1. Command-line options (`--fps 15`)
2. Environment variables: `PIXEL_OFFICE_FPS`, `PIXEL_OFFICE_STYLE`, `PIXEL_OFFICE_THEME`, `PIXEL_OFFICE_CONFIG`
3. `~/.config/pixel-office/settings.toml`
4. Built-in defaults

So `--fps 30` tries 30 fps once, and `pixel-office config set fps 30` keeps it.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | OK |
| `1` | Problem found (`doctor`, a broken pet file) or runtime error |
| `2` | Wrong command or option |

Same convention as herdr, so scripts can check the result.

### Examples

```bash
pixel-office                                   # open the office
pxo --demo --theme game-boy                    # try it with fake agents
pxo --style blocks --pet codex1=fox --fps 15   # one-off look
pxo status                                     # quick text summary
pxo status --watch 5                           # live summary in a small pane
pxo status --json                              # for scripts and agents
pxo doctor
pxo pets new fox --from cat && pxo pets check fox
pxo config set theme night
```

`pxo status` output:

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
- To see the whole team at once, run `pixel-office status --json`.
```

### Doctor

```
Pixel Office doctor · v0.1.0

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

 Settings  ~/.config/pixel-office/settings.toml
 Sprites   ~/.config/pixel-office/sprites/ (1 custom pet)

 1 problem found.
```

Required: Python, herdr, and running inside herdr. Everything else is a warning; the office still starts and shows what it can.

## Tech stack

Kept small so it fits in two days.

| Layer | Choice | Why |
| --- | --- | --- |
| Language | Python 3.11+ | Already on Ubuntu; `tomllib` built in |
| Terminal UI | [Textual](https://textual.textualize.io/) + [Rich](https://rich.readthedocs.io/) | Layouts, touch, animation timers, 24-bit colour, `cell_len` for emoji width |
| CLI | `argparse` (standard library) with subcommands; two entry points, `pixel-office` and `pxo` | Options and commands with built-in `--help`; no extra dependency |
| Settings | TOML: `tomllib` to read, `tomli-w` to write | Human-editable, same format as Codex and herdr |
| Agent status | `herdr agent list` (JSON via `subprocess`) | Uses the existing setup; no extra server |
| Board | `TASKS.md`, re-read when its modified time changes | No file-watching library needed |
| Packaging | `pyproject.toml` + hatchling; [uv](https://docs.astral.sh/uv/) | One command to install, update, remove |
| Tests | pytest for the world model, sprite loader and doctor | The game logic is tested with fake events, no agents needed |

Dependencies: `textual` and `tomli-w` only.

## Project layout

```
pixel-office/
  pyproject.toml
  README.md
  src/pixel_office/
    cli.py           # argparse commands: run, setup, doctor, pets
    app.py           # Textual app, layout, keys
    doctor.py        # checks shared by doctor and setup
    poller.py        # herdr agent list + TASKS.md -> events
    world.py         # pets, zones, targets, movement
    sprites.py       # load sprite files, palette, width check
    settings.py      # read/write settings.toml
    data/
      sprites/       # built-in pets: cat, dog, sheep
      themes/        # night, game-boy, green-screen
      office.txt     # the floor plan, drawn as text
  tests/
```

User files live outside the package, so updates never overwrite them: `~/.config/pixel-office/settings.toml` and `~/.config/pixel-office/sprites/`.

## Two-day plan

**Day 1: a live, moving office**

| Block | Build | Done when |
| --- | --- | --- |
| Morning | Project skeleton, `pyproject.toml`, office map, Textual layout (office + Team + Board + Events) | `pixel-office` opens the empty office |
| Midday | Poller: `herdr agent list` + `TASKS.md` into events | Team list and board show real data |
| Afternoon | World model: zones, status-to-behaviour table, cell-by-cell movement, fps option (`F`) | Pets walk to their desk when you start Claude or Codex |
| Evening | Emoji and ASCII sprites, built-in cat, dog and sheep | Style switch (`S`) works; tests for the world model pass |

**Day 2: your own pets, setup and install**

| Block | Build | Done when |
| --- | --- | --- |
| Morning | Block-pixel sprite format with palettes; custom pets folder; `pets list`, `pets show`, `pets new`, `pets check` | Your own fox walks around in its colours |
| Midday | Themes (`T`), agent colours, emoji width check and calibration screen | Map stays aligned on the 11-inch screen |
| Afternoon | CLI: office options, `status` (with `--json`, `--watch`), `doctor`, `setup`, `config`, `theme list`; `pxo` alias | `pxo status --json` and `pxo doctor` work; `--help` lists every option |
| Evening | Tap to select, `Enter` to open the pane, idle power saving; install test with `uv tool install` from GitHub | Fresh install works end to end |

If day 1 runs late, drop block-pixel sprites from day 2 first: emoji and ASCII are enough to use the app.

## Later (not in the two days)

- Pet editor: paint pets by tapping cells.
- Prompt box that sends tasks to the lead (`herdr agent prompt claude "..."`).
- GitHub Projects board instead of `TASKS.md`.
- Full setup wizard with live previews; more themes.
- PyPI release (`uv tool install pixel-office`) and GitHub Actions CI.
- Web version through Textual's browser mode.
- Shell tab-completion (`pixel-office completion bash|zsh|fish`).

Each day ends with a usable app.

## Risks

| Risk | Effect | Fallback |
| --- | --- | --- |
| `herdr agent list` output changes in a herdr update | Pets freeze or vanish | The poller is one small file; test after `herdr update` |
| Emoji width differs on the tablet font | Map tiles shift | Calibration screen; ASCII style |
| Battery drain under PRoot | Tablet gets warm | 10 fps default; auto 2 fps when idle; 5 fps saver |
| Polling herdr every second costs CPU | Slower agents | Raise `poll_seconds` to 2–3 |

## Open questions

- [ ] Which pet for each agent?
- [ ] Landscape only, or also portrait?
- [ ] Office theme: plain office, a farm (fits the herdr sheep), or space?
- [ ] Should v1 include the prompt box, or stay watch-only?
