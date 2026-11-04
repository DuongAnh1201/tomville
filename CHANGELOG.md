# Changelog

## 0.3.0 (2026-11-03)

### 📝 Shared Markdown docs

- **`tmv doc`**: agents and Tom read and write Markdown together. `list`, `read` (whole file or one section, with a version tag) and `new`; only `.md` files under `[docs] roots`, never outside the project (#94).
- `tmv doc edit`: lock + atomic write, 3-way merge of edits made at the same time, git-style conflict markers and `tmv doc resolve` (#95).
- Change log: `tmv doc log`, `diff`, `revert`; edits made outside tmv are logged as `tom (editor)` (#96).
- The team sees doc changes: `tmv watch` exits on them, the office shows them, the secretary's emails get a "Doc changes" part, and Telegram has `/doc read` and `/doc watch` (#97).
- Team notes in `notes/` of the main checkout are shared live by every worktree; project docs still go through branch and PR.

### Fixes

- `tmv up` starts pane agents again on herdr 0.9.5 (`pane split` needs `--direction`); later pane agents stack under the first. A herdr usage error now says the tmv and herdr versions don't match, and `tmv doctor` reports the herdr version and warns outside the tested range (#93, #104).
- `tmv setup` writes the agent rules to `AGENTS.md` only when `CLAUDE.md` imports `@AGENTS.md`, so Claude doesn't read them twice; the watch rule names `[board] watch = true` (#106).
- Tests no longer read the developer's own `.tomville/ville.toml` (#105).
- Also includes the 0.2.1 fixes below.

## 0.2.1 (2026-10-20, not published)

Merged but never tagged, so it was not uploaded to PyPI; these fixes ship in 0.3.0.

### Fixes

- The Telegram bot no longer stalls after running a while: taps are handled at once, acknowledged first and never lost. Network, herdr and lock waits now have time limits. `tmv telegram status` and `tmv doctor` show a heartbeat (#87, #88).
- The lead's end-of-turn questions reach Telegram even when the question isn't the last line, with the question lines in bold (#84, #86).

## 0.2.0 (2026-10-20)

### 📱 Telegram

- **Talk to your team from your phone.** Optional, one bot (so one chat) per ville: `tmv telegram setup`, or yes to the new last question of `tmv new`. Pair with a one-time code; only your private chat is answered (#58).
- Plain text goes to the lead, `/<agent>` to that agent; `/status`, `/board`, `/pending`, `/pause`, `/resume`, `/help`. Pings when an agent is blocked or a card is ready for review or done (#58).
- The lead's permission questions and choices arrive as buttons (allow once or deny; no answer in 10 minutes means no) (#78).
- Code and PR diffs are shown per file in IDE-style code blocks: `tmv reply --diff PR` (#72). Delivery and error fixes (#70).
- The secretary sends its summaries to the chat as well as by email (#59).
- The office shows the phone: a 📱 walks in from the door, replies and approvals appear as bubbles, and the Events panel logs them (#59).
- Safe by design: the token lives outside the project (mode 600), the bot has no shell, no server or open port is needed. Lead + workers team only for now.

### Also in this release

- The wall board in the office now shows the open cards under Todo, Doing and Review (#62).
- `tmv down` waits for slow agents to quit (#61).
- `tmv up` reports a running agent that is waiting on a question as running, not FAILED (#68, #69; thanks to @jay23606), and keeps blocked startups failed on repeated runs (#75).
- New opt-in `tmv watch`: waits for a GitHub issue or PR change for the lead (#74).
- Fixed a race in the event reader on Python 3.11 (#65).
- Secretary emails show what changed at every step, as plain text with bold and italic (#54, #56).

## 0.1.0 (2026-10-18)

First release, on PyPI as `tomville`:

- The office in the terminal: pets, desks, the board, movement and messages, in lead + workers and pipeline shapes.
- `tmv new` / `up` / `down` build and stop a team in herdr; `status`, `doctor`, `task`, `setup`, `send`.
- Tested on Ubuntu and macOS in CI; live use so far on Ubuntu in Termux PRoot.
