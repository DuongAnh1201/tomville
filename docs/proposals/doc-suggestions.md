# Proposal: suggested edits on protected docs

Status: **proposal for Tom, nothing built** · Issue #98 (B6) · Milestone M18 · Builds on `tmv doc edit` (#95) and the change log (#96).

## The problem

Today any agent can change any doc with `tmv doc edit`. That is right for working notes, but not for files Tom wants to keep a hand on: `AGENTS.md`, `CLAUDE.md`, `idea.md`, a decisions note, the README. For those, an agent's edit should become a **suggestion** that Tom approves, rejects, or approves with changes. It is not written until then.

## In one paragraph (the recommendation)

Tom lists protected files in `.tomville/ville.toml` (`[docs] protected = ["AGENTS.md", "notes/decisions.md"]`, globs allowed). When an agent runs `tmv doc edit|new|revert` on one of them, Tomville does not write. It stores the edit as a suggestion (the same data as a normal edit: path, section, base tag, text) and exits with code 4 and the suggestion ID. Tom sees it in the terminal (`tmv doc suggestions`), on Telegram (a diff with Approve / Reject buttons), and on the office wall. Approving applies the stored edit through the **same safe-edit path as #95**: if the file moved since the agent's base, it is 3-way merged; if the changes overlap, Tom gets the usual conflict choices instead of a silent overwrite. This is about 4 small issues on top of M18.

## 1. Marking files protected

```toml
[docs]
protected = ["AGENTS.md", "CLAUDE.md", "idea.md", "notes/decisions.md", "notes/policy-*.md"]
```

- Globs are matched on the path relative to the project root (`*` within a folder, `**` across folders). A folder name (`docs/`) protects everything in it.
- `.tomville/ville.toml` is always protected, whatever the list says, so an agent cannot unprotect a file through `tmv config`.
- Only Tom changes the list (by hand, or `tmv config set docs.protected '[...]'` outside an agent pane).
- Reading is never restricted. Only writes are routed.
- Default: empty. `tmv new` could offer the list above as a starting point.

## 2. Where suggestions live

One file per suggestion in `.tomville/doc-suggestions/<id>.json` in the main checkout (git-ignored, like the other `.tomville/doc-*` state), so every worktree sees the same queue.

```json
{"id": "s7", "path": "AGENTS.md", "section": "Your queue", "mode": "replace",
 "base": "a1b2c3d4e5f6", "text": "## Your queue\n…", "by": "codex1", "time": "2026-10-28T10:00:00+00:00",
 "why": "step 3 contradicts the board rules", "status": "pending"}
```

- `status`: `pending`, `approved`, `rejected`, `withdrawn`. Decided suggestions stay for history, with `decided_by`, `decided_at`, `reason`, and the resulting version tag.
- The base version is pinned so the object store (#96) never prunes it while the suggestion is pending.
- The change log gets lines too (`suggest`, `approve`, `reject`), so `tmv doc log` tells the whole story: who suggested, who decided, who changed the file.
- Limits to avoid spam: at most 5 pending per agent; a new suggestion from the same agent for the same section replaces its older pending one.
- Agents add `--why "…"` to say the reason. It is shown to Tom next to the diff.

## 3. How Tom sees them

| Where | What Tom sees | Notes |
| --- | --- | --- |
| Terminal | `tmv doc suggestions [PATH] [--all]` lists them; `tmv doc suggestions show s7` prints the diff against the file now, and whether it applies cleanly | Works with `--json` |
| Telegram | A message: *"codex1 suggests a change to AGENTS.md › Your queue"*, the reason, the diff in a code block (as `tmv reply --diff` does), buttons ✅ Approve · ❌ Reject · 💬 Reject with note | Reuses the approvals plumbing (paired chat only, random IDs, answers consumed once). Off unless `telegram.approvals` is on |
| Office | A 📝 paper on Tom's desk with the count; `📝 codex1 → AGENTS.md: s7` in the Events panel | Same style as the 📱 envelope |
| Email | Secretary sends a digest, only when Telegram is off or a suggestion has waited a day | Optional; lowest priority |

Differences from permission prompts: nobody is blocked waiting, so **suggestions do not expire**. A tap is still checked against the suggestion ID and its content hash, so a button for an edited or withdrawn suggestion does nothing.

## 4. Approve, reject, approve with changes

- **Approve** (`tmv doc suggestions approve s7`, or the button): applies the stored edit with the agent's base tag through the #95 path, written as Tom's decision but credited in the log ("codex1 via tom"). File unchanged since the base: written. Changed elsewhere: 3-way merged. Overlapping: refused with exit code 3 and the other change shown, exactly like `edit`.
- **Approve with changes**: `tmv doc suggestions approve s7 --edit` opens `$EDITOR` on the proposed text (the section, not the whole file) and applies what Tom saves. A script can pipe it: `approve s7 --text -`. The log says `approved with changes`, and the author is told the final text. Terminal only; the phone offers Approve or Reject.
- **Reject**: `reject s7 --reason "…"`. The reason is stored and shown to the author.
- **Withdraw**: the author can drop its own pending suggestion.
- **The file changed since the suggestion** (the case that matters):
  1. No overlap → the merge is clean and Approve just works. `show` says "applies cleanly (merged with 2 later changes)".
  2. Overlap → `show` says "conflicts with the current file". Tom's choices: `approve --merge` (writes the git-style markers and marks the doc conflicted, then `tmv doc resolve`, all from #95), `approve --edit` (fix it by hand), or `reject --reason "redo against the new version"`. The phone shows only Reject / "Ask to redo" here, since a conflict needs an editor.
- **How the author hears back**: only the lead prompts agents (AGENTS.md), so Tomville does not prompt on its own. The decision shows in `tmv doc suggestions --mine`, in the log, and in the lead's change notifications from #97. The lead relays it with `tmv send`.

## 5. Project docs versus `notes/`

| | Project docs (README, `AGENTS.md`, `docs/`) | Team notes (`notes/`) |
| --- | --- | --- |
| Normal flow | Branch, PR, review, lead merges | Live edit, no PR |
| Already reviewed? | Yes, every change is a PR | No |
| What "protected" adds | Little: the PR is already the suggestion. Tom's wish is a rule that a PR touching a protected file waits for **his** approval, even from the team | The suggestion queue above |

Recommendation: the suggestion queue is for **`notes/` and any shared file in the main checkout**. For protected project docs, a PR that changes them is flagged "needs Tom" (the lead's existing rule for outside PRs), backed by GitHub CODEOWNERS plus branch protection so it is a hard rule. We do not build a second approval system on top of PRs. In a worktree, `tmv doc edit` on a protected project doc says: "protected: open a PR and ask Tom", exit code 4, nothing written.

## 6. What this cannot do (honest limits)

`tmv doc edit` can only guard its own write path. An agent with a shell can still `echo >> AGENTS.md`. So there are two layers:

- **Soft (this proposal):** `tmv` refuses and suggests instead. This covers the normal, well-behaved path, and the rules in AGENTS.md tell agents to use it. "Who is Tom" is "not an agent pane": protected operations ignore `--as`, so an agent cannot claim to be Tom, but it is a guard, not security.
- **Hard (optional follow-up):** a Claude Code `PreToolUse` hook (we already install one) that denies Write/Edit on protected paths, and CODEOWNERS for the PR side. Codex agents have no such hook, so for them the CODEOWNERS check is the backstop. Read-only file permissions do not help: agents run as the same user.

## 7. Options

| | A. PR-only | **B. Suggestion queue (recommended)** | C. Branch per suggestion |
| --- | --- | --- | --- |
| Idea | No new feature: protected = PR needs Tom, lead flags it | Store the edit, Tom decides, apply via #95 merge | Every suggestion on `notes/` becomes a git branch and PR |
| `notes/` covered | No | Yes | Yes, but notes are not tracked in git |
| Reuses | PR flow | #95 merge and conflicts, #96 log, Telegram approvals | PR flow |
| Phone approval | Via GitHub | Yes (buttons) | Via GitHub |
| Cost | Tiny | Medium (4 issues) | Large, and fights the "notes have no PR" decision |

Recommendation: **B** for `notes/`, plus **A** for project docs (section 5). C contradicts the M18 decision that notes live outside branches.

## 8. Rough split into issues

1. **Protected setting and routing** (small): `[docs] protected`, glob matcher, `edit|new|revert` on a protected path stores a suggestion and exits 4; always-protected `ville.toml`; pending limits; tests.
2. **Suggestion commands** (medium): `tmv doc suggestions` list/show/approve/reject/withdraw, `--edit`/`--text`, stale and conflict handling through `edit_doc`, log lines, "Tom only" guard; tests.
3. **Phone and office** (medium): Telegram message with diff and buttons on the existing approvals plumbing, 📝 paper and Events line; tests with recorded updates.
4. **Hard enforcement and rules** (small): PreToolUse hook for protected paths, CODEOWNERS and lead rule for protected project docs, AGENTS.md rule text, README; optional secretary digest.

Order: 1, 2, then 3 and 4 in parallel.

## 9. Questions for Tom

1. Which files start protected? Suggested: `AGENTS.md`, `CLAUDE.md`, `idea.md`, `milestones.md` (agents tick tasks in it in every PR, so maybe not), `.tomville/ville.toml` (always).
2. Should suggestions ever expire? Recommended: no.
3. Approve from the phone only for clean merges, with conflicts and "approve with changes" in the terminal. OK?
4. Do you want the hard layer (hook, CODEOWNERS) now, or start with the soft one and see?
