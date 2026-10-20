# Tomville

A retro game view of your agent team, in the terminal. Each coding agent (Claude Code, Codex, …) is a pet in a pixel office: it types at its desk while working, jumps when it needs you, naps in the lounge when idle, and carries cards to the board as it takes and finishes GitHub issues.

Tomville is built on top of [herdr](https://herdr.dev), the terminal workspace manager for coding agents. It reads live agent status from herdr and the task board from GitHub Issues (or a `TASKS.md` file).

```
▓ ┌─ BOARD ───────────┐        🐱claude #39       ▓
▓ │ Todo Doing Review │      ┌──────────┐         ▓
▓ └───────────────────┘      │   BOSS   │         ▓
▓        ┌────────┐  ┌────────┐  ┌─────────┐      ▓
▓        │claude2 │  │ codex1 │  │secretary│      ▓
▓  🐶codex1   🐱claude2 z z     🐑secretary         ▓
▓  LOUNGE           REVIEW                  DOOR  ▓
```

## 📱 Talk to your team from your phone

New in 0.2.0, and optional: connect a Telegram chat to your ville (`tmv telegram setup`, or answer yes to the last question of `tmv new`). Each ville gets its own bot, so each project is its own chat.

- Plain text goes to the lead; `/<agent>` messages an agent directly; `/status`, `/board`, `/pending` and `/pause` answer from the bot.
- Pings when an agent is blocked, or a card is ready for review or done.
- The lead's permission questions and choices come to your phone as buttons (allow once or deny; 10 minutes without an answer counts as no).
- Code and PR diffs are shown IDE-style, per file, with `tmv reply --diff PR`.
- Safe by design: only your paired private chat is answered, the token is kept outside the project (mode 600), the bot has no shell, and no server or open port is needed. Works with the lead + workers team only for now.

Details: [Phone (Telegram)](https://github.com/DuongAnh1201/tomville#phone-telegram) in the README.

## Requirements

- Linux or macOS (also runs in Termux on Android, inside a PRoot Ubuntu)
- Python 3.11 or newer
- [herdr](https://herdr.dev) on your `PATH`, with its integrations for your agents (`herdr integration install claude`, `herdr integration install codex`)
- The agent CLIs you want in the office (Claude Code, Codex, Gemini, …)
- For the GitHub board: [`gh`](https://cli.github.com), logged in

## Install

```bash
uv tool install tomville      # or: pipx install tomville
```

This gives you two commands, `tomville` and its short alias `tmv`. Check the setup with:

```bash
tmv doctor
```

## Quick start

Inside herdr, in your project folder:

```bash
tmv up
```

The first time, `tmv up` asks a few questions: the lead agent and the workers, each one's kind (`claude`, `codex`, …), model and place (its own git worktree, a tab or a pane), and whether to add a secretary agent. It saves the answers in `.tomville/ville.toml`, starts every agent in herdr, sends each a first prompt and opens the office in its own tab. After that, `tmv up` rebuilds the same team with no questions, and `tmv down` stops it.

Already running your agents by hand? Just open the office:

```bash
tmv
```

Try it without herdr or any agents:

```bash
tmv --demo
```

## Commands

| Command | What it does |
| --- | --- |
| `tmv` | Open the office |
| `tmv up` / `tmv down [NAME]` | Start the team from the ville, or stop what `tmv up` started |
| `tmv new` | Ask the ville questions again |
| `tmv status [--json]` | Print the team and board once |
| `tmv doctor` | Check the setup and print fixes |
| `tmv send AGENT "text"` | Prompt another agent and log who sent it |
| `tmv task new/take/move/list` | Manage GitHub task cards |
| `tmv setup` | Redo the emoji test, board labels, agent rules or the Claude hook |
| `tmv telegram setup/run/status/pause/resume/off` | Optional phone chat for this ville |
| `tmv reply TEXT` / `--diff PR` | Send a reply, or a PR diff, to your Telegram chat |
| `tmv watch` | Wait for a GitHub issue or PR change, then exit (for the lead) |
| `tmv config get/set` | Read and change settings |

In the office: `f` frame rate, `s` sprite style (emoji or ASCII), `g` board check interval, `t` sidebar, `?` help, `q` quit.

## Links

- Source, full design and issues: <https://github.com/DuongAnh1201/tomville>
- herdr: <https://herdr.dev>

MIT licensed.
