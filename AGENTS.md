# Rules for agents working on Tomville

Read these before any work, every time you start.

## The project

Tomville is a retro game view of an agent team, built on top of herdr. Before you change anything, read:

- [idea.md](idea.md): what we decided and why
- [milestones.md](milestones.md): the build checklist and its rules
- [README.md](README.md): the full design

When these disagree, `milestones.md` wins for scope and `idea.md` for decisions. Don't change a decision on your own; tell the lead.

## The team

| Agent | Role |
| --- | --- |
| `claude` | **Lead.** Hands out issues, reviews and merges PRs, ticks `milestones.md` on `main` |
| `claude2` | Worker: visual side (world model, movement, sprites, `tmv new`) |
| `codex1` | Worker: data side (herdr events, GitHub board, CLI commands) |

Only the lead sends prompts to other agents. Workers don't control other herdr panes.

## Where you work

- Work only in **your own git worktree and branch** (the lead creates them). Never commit to `main` and never push to `main`.
- Stay inside your issue's milestone. Shared types (`src/tomville/core/models.py`) and plug-in interfaces change only through the lead: if you need a change, say so in your PR.
- Found a bug or idea outside your issue? Open an issue (`gh issue create --label bug` or `--label idea`) instead of fixing it now.

## The board: GitHub Issues

- **Take an issue:** `gh issue edit N --add-label status:doing,agent:<you> --remove-label status:todo`
- **Ready for review:** push your branch, open a PR with `Fixes #N` in the body, then `gh issue edit N --add-label status:review --remove-label status:doing`
- Once `tmv task` exists (M6), use `tmv task take N` / `tmv task move N review` instead.

## Done means tested

- Tick a task in `milestones.md` only when it works, in the same PR as the code. Follow the rules at the top of `milestones.md`.
- `uv run pytest` must pass. Tests run with no network and no herdr: use the recorded JSON in `tests/fixtures/`.
- Run the milestone's **Check** before asking for review, and say in the PR how you ran it.

## Tech

- Python 3.11+ (the tablet has 3.14), `uv`, Textual, pytest. Add dependencies with `uv add`.
- Code goes in `src/tomville/`: `core/` has no UI code; `tui/` is the terminal front end.
- Keep it simple and small. Match the style of the code around you.

## This machine

- Ubuntu in Termux PRoot on an Android tablet (aarch64). No `sudo`; install with `apt` or `uv`.
- CPU and battery are limited: don't leave watchers, servers or long loops running after you finish.
- herdr runs here; `herdr agent list` works in every pane.

## Reporting back

The lead reads the end of your output. Finish every task with one line:

- `DONE #N: <PR URL>`
- `BLOCKED #N: <what is wrong and what you need>`
