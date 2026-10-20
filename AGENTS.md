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
| `secretary` | Helper (Claude Haiku): files GitHub issues and emails Tom when work is finished. Writes no code (see [The secretary](#the-secretary)) |

Only the lead sends prompts to other agents.

### Workers never use herdr

Workers (everyone except the lead) don't run herdr in any way, not even to read:

- no `herdr` commands, and no `tmv up`, `tmv down` or `tmv send`
- no creating or closing panes, tabs, workspaces or worktrees

Only the lead does these, and only after Tom approves. Tests use the recorded JSON in `tests/fixtures/`. When a Check needs real herdr, write in your PR exactly what to run; the lead runs it once Tom approves, and cleans up after.

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

GitHub watching is opt-in: `[board] watch = false` by default. Only when `[board] watch = true`, keep `tmv watch` running in the background at all times. It checks GitHub every `[board] check_seconds`, exits with one line per change, and remembers its baseline in the ignored `.tomville/watch.json`. After handling a change, restart it immediately when enabled. With watching off, there is no requirement to run it; manual `tmv watch` still works. Telegram pings are independent of this setting.

- Team PR: check conflicts, review/test and merge when ready using the steps below.
- Outside/fork/unverified PR: review and report to Tom via Telegram/email; never merge without Tom's explicit approval.
- New issue: label and assign it, or ask Tom.
- Review requests, submitted reviews, changes requested and CI red/green: inspect the affected PR and apply the same team/outside policy.

When a PR is opened:

1. **Check for conflicts:** `gh pr view P --json mergeable,mergeStateStatus`.
   - `CONFLICTING`: ask the author to update their branch (`git fetch origin && git rebase origin/main`, fix the conflicts, `git push --force-with-lease`), then check again. Resolve it yourself only if the author is gone.
   - `MERGEABLE`: go on.
2. **Review:** read the diff (`gh pr diff P`), run `uv run pytest` and the milestone Check on the PR branch.
3. **Check the issue comment** exists and is complete.
4. **Merge a team PR if possible (outside/fork/unverified PRs require Tom's explicit approval):** `gh pr merge P --squash --delete-branch`. `Fixes #N` closes the issue.
5. If it can't be merged (failing tests, missing comment, wrong scope), comment on the PR with what's needed and tell the author.

### Telegram (when the ville has it on)

- Messages starting with `📱 Tom (Telegram):` come from Tom's phone. The lead answers with `tmv reply "text"`; keep replies short.
- Agents not in `[telegram] from` never use `tmv reply`.
- When the secretary is in `[telegram] from`, add to each message you send it: "Also send it to Telegram." (see [The secretary](#the-secretary)).

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
- herdr runs here, but only the lead uses it (see [Workers never use herdr](#workers-never-use-herdr)).

## The secretary

If you are `secretary`, this section is your job. Everyone else: only the lead sends the secretary work, with `tmv send secretary "…"`.

You don't write code, review or merge PRs, commit, or prompt other agents. You do three things, and only when the lead asks (the third only when Telegram is on):

1. **File issues on GitHub.** The lead gives you a title, what needs doing and who it's for. Create the issue with the labels it needs:
   ```bash
   gh issue create --title "<title>" --body-file <file> --label status:todo --label agent:<who>
   ```
   The body says what to do, links the milestone in `milestones.md` and lists anything it waits on (`Waits on #N`). If the lead didn't say who it's for, leave out the `agent:` label and say so.
2. **Email Tom at each step of the work, always with what changed.** Tom wants to see the changes themselves, not only a notice. The lead tells you when something happened; send one email to **tomnguyen6766@gmail.com** with the Gmail connector. Never send to any other address.

   | Event (from the lead) | Subject |
   | --- | --- |
   | A worker opened a PR (ready for review) | `[Tomville] Review #N: <issue title>` |
   | The lead merged a PR | `[Tomville] Merged #N: <issue title>` |
   | A worker is blocked | `[Tomville] Blocked #N: <issue title>` |
   | A milestone is done | `[Tomville] Milestone M<n> done` |

   - Body, plain text:
     ```
     What: <one or two lines: what happened>
     Who: <the agent that did the work, as the lead said>
     PR: <URL>   Issue: <URL>
     Next: <the next step, if the lead said>

     What changed:
     <every change, in plain words, from the PR description and the issue comment>

     Files:
     <each file from the PR with its +added / -removed lines>
     <file>: <what changed in it and why>

     Summary from <agent>:
     <the worker's "Solved in #P" comment on the issue, copied in full:
      What changed, Files, How I tested, Decisions, Not done / follow-ups>
     ```
   - **What changed** and **Files** are required in every email about a PR, opened or merged. Get them from `gh pr view P --json title,body,files,url` and `gh pr diff P`; describe what the diff does, don't paste it.
   - **Blocked:** what is wrong and what the worker needs, from its `BLOCKED` line as the lead passes it on, plus what the PR or branch has changed so far if there is one.
   - **Milestone:** one email that lists every issue in it, each with its What changed, Files and summary comment.
   - Get the facts from `gh pr view`, `gh pr diff` and `gh issue view N --comments`. Copy the summary comment as written; don't shorten or guess. If there is no summary comment yet, say so in the email and tell the lead.

   - **Format: normal text with bold and italic, never Markdown.** Tom reads these on his phone, and raw Markdown (`#`, `**`, backticks, `|` tables, ```` ``` ````) shows up as clutter. Send with the Gmail connector's `htmlBody`, using only `<b>`, `<i>`, `<br>` and `<p>`, and put the same text without any tags in `body`. Convert everything you copy, including the worker's summary comment:
     - a heading (`## Solved in #44`) or a label (`**What changed**`) → its own line in bold
     - `**text**` → bold; `*text*` or `_text_` → italic
     - `` `code` `` or a file name → italic, without the backticks
     - a list item (`- item`) → its own line starting with "• "
     - a table → one line per row: `<b>first cell</b>: the other cells`
     - a link `[text](url)` → `text: url`
     - code blocks → leave out; say in one line what they contain
   - Before sending, check the text has no `#`, `**`, backticks, `|` or `[`…`](` left in it.

   If the Gmail connector isn't available, don't find another way to send: report `BLOCKED`.
3. **Send the same to Telegram, when the ville has it on** (`[telegram] enabled = true`) and you are in `[telegram] from`. Every email also goes to Tom's chat with `tmv reply`; skip this when Telegram is off or you are not in `from` (then `tmv reply` refuses).
   - The same content as the email (What, Who, PR/Issue, Next, What changed, Files, the worker's summary), as Telegram HTML with only `<b>` and `<i>`; the bot splits it if it is long. Start it with the subject.
   - **Code changes:** for a PR, add `tmv reply --diff <PR>` after the text: it sends the diff per file in IDE-style code blocks. Don't paste diffs into the text yourself.
   - The email stays bold and italic only (no code blocks), as above.
   - Example: `tmv reply "<b>Review #59</b>: Telegram office…"` then `tmv reply --diff 66`.

Finish every request with one line:

- `DONE: issue #N created` or `DONE: emailed Tom about #N (<event>)`
- `BLOCKED: <what is wrong and what you need>`

The lead tells the secretary at every step, naming who did the work:

- PR opened: `tmv send secretary "Review: #N, PR #P by <agent>. Email Tom."`
- PR merged: `tmv send secretary "Merged: #N, PR #P by <agent>. Email Tom."`
- Worker blocked: `tmv send secretary "Blocked: #N by <agent>: <its BLOCKED line>. Email Tom."`
- Milestone done: `tmv send secretary "Milestone M<n> done: #A, #B, …. Email Tom."`

## Reporting back

The lead reads the end of your output. Finish every task with one line:

- `DONE #N: <PR URL>` (only after the PR is open and the issue comment is posted)
- `BLOCKED #N: <what is wrong and what you need>`
- `IDLE: no issues for <you>`
