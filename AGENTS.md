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
| `claude` | **Lead.** Hands out issues, checks PRs for conflicts, reviews and merges them; works on branches and PRs like everyone else |
| `claude2` | Worker: visual side (world model, movement, sprites, `tmv new`) |
| `codex1` | Worker: data side (herdr events, GitHub board, CLI commands) |

Only the lead sends prompts to other agents. Workers don't control other herdr panes.

## Never work on `main`

This applies to **everyone, the lead included**, and to every change, even a one-line doc fix.

- Work only on a branch: in your own git worktree (workers) or a short-lived branch (lead). Never commit to `main` and never push to `main`.
- Name branches after the issue: `m2-events`, `fix-12-board-offline`, `docs/pr-workflow`.
- Before you start, check: `git branch --show-current` must not print `main`.

## Every change: issue → branch → PR → comment → merge

1. **Issue first.** Every piece of work has an issue. No issue yet? Create one (`gh issue create`).
2. **Branch** from the latest `main` (`git fetch origin && git switch -c <branch> origin/main`).
3. **PR, always linked to the issue.** Push the branch and open a PR with `Fixes #N` in the body (use `Refs #N` if the PR only does part of the issue). No PR without an issue link.
4. **Detailed comment on the issue** as soon as the PR solves it (template below). The lead does not merge until this comment is there.
5. **The lead checks and merges** (see [For the lead](#for-the-lead)).

### Issue comment template

Post it with `gh issue comment N --body-file <file>`:

```markdown
## Solved in #<PR>

**What changed**
- <each change, in plain words>

**Files**
- `path/to/file.py`: <what and why>

**How I tested**
- `uv run pytest`: <N passed>
- Milestone Check: <what you ran and what you saw>

**Decisions**
- <choices you made and why; anything that differs from idea.md or the README>

**Not done / follow-ups**
- <left out, known issues, new issues opened: #N>
```

## For the lead

When a PR is opened:

1. **Check for conflicts:** `gh pr view P --json mergeable,mergeStateStatus`.
   - `CONFLICTING`: ask the author to update their branch (`git fetch origin && git rebase origin/main`, fix the conflicts, `git push --force-with-lease`), then check again. Resolve it yourself only if the author is gone.
   - `MERGEABLE`: go on.
2. **Review:** read the diff (`gh pr diff P`), run `uv run pytest` and the milestone Check on the PR branch.
3. **Check the issue comment** exists and is complete.
4. **Merge if possible:** `gh pr merge P --squash --delete-branch`. `Fixes #N` closes the issue.
5. If it can't be merged (failing tests, missing comment, wrong scope), comment on the PR with what's needed and tell the author.

## Where you work

- Stay inside your issue's milestone. Shared types (`src/tomville/core/models.py`) and plug-in interfaces change only through the lead: if you need a change, say so in your PR.
- Found a bug or idea outside your issue? Open an issue (`gh issue create --label bug` or `--label idea`) instead of fixing it now.

## Your queue

You don't watch GitHub on your own. The lead (or Tom) sends you a short nudge such as **"Check your issues and take the next one."** Then:

1. **Finish first.** If you already have an issue labelled `status:doing` and `agent:<you>`, keep working on it.
2. **List your queue:** open issues with your label that nobody has started:
   ```bash
   gh issue list --label agent:<you> --label status:todo --state open --json number,title,labels
   ```
3. **Pick the lowest number** (oldest first). Skip an issue if its body says it waits on another open issue, and say so.
4. **Take it and read it:** `gh issue edit N --add-label status:doing --remove-label status:todo`, then `gh issue view N --comments`. The issue body and comments are your task; the matching milestone in `milestones.md` has the Check.
5. **Work it** as in [Every change](#every-change-issue--branch--pr--comment--merge): branch, PR with `Fixes #N`, detailed issue comment.
6. **Report and stop:** end with `DONE #N: <PR URL>`. Don't start the next issue until you are nudged again; the lead reviews and merges first.

**Empty queue?** End with `IDLE: no issues for <you>`. Don't take issues labelled for another agent, and don't take unlabelled ones; ask the lead.

The lead knows when you finish because herdr reports your status (`done`, `blocked`, `idle`); the lead waits on it with `herdr agent wait <you>` in the background.

## The board: GitHub Issues

- **Take an issue:** `gh issue edit N --add-label status:doing,agent:<you> --remove-label status:todo`
- **Ready for review:** push your branch, open a PR with `Fixes #N` in the body, post the detailed issue comment, then `gh issue edit N --add-label status:review --remove-label status:doing`
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

- `DONE #N: <PR URL>` (only after the PR is open and the issue comment is posted)
- `BLOCKED #N: <what is wrong and what you need>`
- `IDLE: no issues for <you>`
