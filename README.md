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
sprites/
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

[pets]
claude = "cat"
codex1 = "dog"
codex2 = "sheep"
```

## Interaction

| Key or touch | Action |
| --- | --- |
| Tap a pet, or `Tab` | Select it; the Team list highlights it |
| `Enter` on a selected pet | Switch herdr to that agent's pane (to approve, read output) |
| `F` | Cycle frame rate |
| `S` | Cycle sprite style |
| `B` | Show the board full-screen |
| `?` | Help |

v1 only watches. Approvals still happen in the agent's own pane: the blocked pet tells you where to go, and `Enter` takes you there. Sending prompts from the app comes later (milestone 5).

## Project layout

```
~/pixel-office/
  pixel_office/
    app.py          # Textual app, layout, keys
    poller.py       # herdr agent list + TASKS.md -> events
    world.py        # pets, zones, targets, movement
    sprites.py      # load frames, width check
    render.py       # office map + sprites widget
    settings.py
  sprites/          # one folder per pet
  maps/office.txt   # the floor plan, drawn as text
  settings.toml
  tests/            # world + poller tests with fake events
```

Requirements: Python 3 and `textual` (`pip install textual`). It must run inside a herdr tab, so `herdr agent list` sees the session.

## Milestones

1. **Static office (day 1):** map, Team list and board from real herdr and `TASKS.md` data; pets drawn in their zones, no movement.
2. **Movement (day 2):** frame timer, fps option, walking between zones, the status-to-behaviour table.
3. **Sprites and width (day 3):** three styles, sprite files, width check, calibration screen.
4. **Interaction (day 4):** select pets, `Enter` to open the pane, Events panel, idle power saving.
5. **Later:** a prompt box that sends tasks to the lead (`herdr agent prompt claude "..."`); reading the GitHub board instead of `TASKS.md`; a web version through Textual's browser mode.

Each milestone is usable on its own. Stop at any point.

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
