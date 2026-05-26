---
name: bug-submit
description: Submit a bug report as a GitHub issue from the current repo, optionally with image attachments, and post a triage comment summarising the initial understanding of the problem. Use when the user wants to file a bug, open an issue for unexpected behaviour, log a defect they've just encountered, or report something broken. Accepts the bug description from $ARGUMENTS (or prompts when missing or thin), accepts images already attached to the conversation as well as paths passed in arguments or via a follow-up question, uploads any images to a secret gist for embedding, then creates the issue via `gh` and posts a triage comment grounded in a quick read of the relevant code paths. Step 0 confirms with the user via AskUserQuestion before doing any work when invoked proactively; the confirmation is skipped when the user explicitly typed /bug-submit. Because this skill posts to GitHub, the proactive-invocation confirmation is non-negotiable.
model: opus
effort: high
user-invocable: true
disable-model-invocation: false
argument-hint: <bug description (optionally with image paths), or omit to be asked>
allowed-tools: Read, Grep, Glob, AskUserQuestion, Skill, Bash(gh *), Bash(git *), Bash(ls *), Bash(find *), Bash(file *), Bash(date *), Bash(pwd), Bash(test *), Bash(cat *), Bash(mktemp *), Bash(rm *), Bash(basename *)
---

# bug-submit — File a triaged bug report on GitHub

You are running the `bug-submit` skill. The user may have arrived here by typing `/bug-submit` (with an optional description and/or image paths in `$ARGUMENTS`) or because the model proactively invoked the skill. Your job is to file a clean GitHub issue against the current repo and post a follow-up triage comment that captures your initial understanding of the problem — grounded in a quick read of the relevant code.

This skill has nine steps (Steps 0–8). Execute them in order. Do not skip Step 0 (proactive-invocation confirmation), Step 2 (repo readiness), Step 3 (clarification), Step 5 (issue creation), Step 6 (triage comment), or Step 7 (lessons capture).

## Step 0 — Confirm before proceeding (when invoked proactively)

This skill posts public content to GitHub — proactive invocation without a clear opt-in is higher cost than for read-only skills. The Step 0 check is strictly enforced.

Check the most recent user message in the conversation for the literal tag `<command-name>/bug-submit</command-name>` (or, equivalently, a leading `/bug-submit` typed by the user). If present, the user has explicitly opted in — skip this step and continue with Step 1.

Otherwise (you arrived here because the model decided to invoke this skill proactively from natural-language intent), call `AskUserQuestion` exactly once before any other work:

- **question**: `"Launch /bug-submit to file a GitHub issue for <your one-line restatement of the bug>? This will create an issue and post a triage comment on the current repo."`
- **header**: `"Run /bug-submit?"`
- **options**:
  - `{ "label": "Yes, proceed", "description": "Create the issue, attach any images, and post the triage comment." }` (mark this as Recommended)
  - `{ "label": "No", "description": "Don't run; I'll redirect." }`

If the user picks "No" or "Other", stop immediately. Do not create any issue or comment, and do not upload any images.

## Step 1 — Parse arguments and detect images

Parse `$ARGUMENTS` into two buckets:

- **Bug description text** — everything that isn't a path token.
- **Image path tokens** — anything that looks like a file path ending in `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, or `.bmp` (case-insensitive). Validate each exists with `test -f`; drop tokens that don't resolve to a real file (note the misses but don't error yet).

Also scan the **recent conversation context** for any image file paths surfaced by Claude Code — e.g. screenshots the user pasted or dragged in, which are saved to temp paths and become referenceable. Include any such paths in the candidate list, deduplicating against the argument paths.

You now have:

- `description_text` — may be empty or trivially short.
- `image_paths` — may be empty.

Do not ask anything yet — Step 3 handles the clarification round in one shot.

## Step 2 — Repo readiness

Confirm the working directory is a GitHub-backed repo and `gh` is authenticated:

- `git rev-parse --is-inside-work-tree` — must print `true`. If not, stop and tell the user to `cd` into a GitHub-backed repo first.
- `gh repo view --json nameWithOwner,hasIssuesEnabled -q '[.nameWithOwner, (.hasIssuesEnabled|tostring)] | @tsv'` — must succeed. Record the slug as `repo_slug`. If `hasIssuesEnabled` is `false`, stop with: `"Issues are disabled on <repo_slug>. Enable issues in the repo settings before filing."`
- `gh auth status` — must show an authenticated host matching the repo's host. If not, stop with: `"gh is not authenticated for <host>. Run 'gh auth login' and re-run /bug-submit."`

Do not attempt to authenticate on the user's behalf and do not prompt them for credentials.

## Step 3 — Clarify the bug

**This step is mandatory even in auto / non-interactive mode.** If the user or the harness has told you to "work without stopping" or "skip clarifying questions", that instruction does not apply here — a vague bug report wastes everyone's time downstream. Close material ambiguity before filing.

Decide whether you need to ask anything:

- If `description_text` is empty or under ~10 meaningful words, you need to ask for the description.
- If `description_text` is substantive but is missing one of: **what happened**, **what was expected**, **steps to reproduce**, ask to close those gaps.
- If `image_paths` is empty and the description suggests visual context would help (UI bugs, layout issues, error dialogs), ask whether any screenshots or image paths should be attached.

Make **one** `AskUserQuestion` call combining 1–4 questions to cover the gaps. Always present options with a recommendation rather than open-ended prompts — the user can still pick "Other" to supply free text. Sample questions when applicable:

- *"What's the bug?"* — only if no description.
- *"What did you expect to happen?"* — if expectation is unclear.
- *"How can this be reproduced?"* — if repro is unclear.
- *"Any screenshots or image paths to attach?"* — only if no images detected and visual context would help.

If the user supplies image paths in their answers (or in "Other" free text), append them to `image_paths` and re-validate with `test -f`. Note any that don't resolve and ask the user to fix the path **once** — never twice.

If after this round the description is still essentially empty (the user declined to elaborate), stop the skill cleanly with no issue created.

## Step 4 — Upload images (if any)

Skip this step entirely if `image_paths` is empty.

Otherwise, upload the images as a single **secret gist** so they get raw URLs the issue body can embed. Secret gists are not listed publicly but are accessible to anyone with the URL — surface that caveat to the user once via `AskUserQuestion` if any image filename or path looks like it may contain sensitive content (e.g. paths under `secrets/`, `.env`-adjacent dirs, or filenames suggesting credentials). If the user declines, set `image_paths` to empty and continue without images.

Run via the `Bash` tool:

```bash
gh gist create --secret --desc "bug-submit attachments for <repo_slug>" <path1> <path2> ...
```

Capture the gist URL from stdout (the last line is the gist URL). Then fetch the gist's raw URLs:

```bash
gh api "gists/$(basename <gist_url>)" --jq '.files | to_entries[] | "\(.key)\t\(.value.raw_url)"'
```

Parse the tab-separated `filename<TAB>raw_url` lines into `image_urls` (a list of `{filename, raw_url}` records). Map back to the original `image_paths` by filename, not positional order.

If `gh gist create` fails (e.g. gists are disabled for the account, or the auth scope lacks `gist`), surface the error verbatim, set `image_paths` to empty, and continue creating the issue with text only — note in the issue body that images were intended but could not be uploaded. Do not abort the whole skill on a gist failure.

## Step 5 — Create the issue

Build the issue title and body.

**Title:** a short, scannable summary derived from the bug description. Aim for 6–12 words, lead with the symptom (e.g. `"Login button does nothing on Safari 17"`). Avoid generic titles like `"Bug"` or `"Issue"`. Do not include `[Bug]` prefixes — the `bug` label (or its absence) carries that signal.

**Body** — use this template verbatim, sections in the order shown. If a section has nothing to say, write the italic placeholder; do not omit the heading.

```markdown
## Description
<the user's bug description, lightly cleaned up — preserve their wording where it's specific; do not invent details>

## Expected behaviour
<one or two lines if known; otherwise: `_Not specified._`>

## Steps to reproduce
<numbered list if known; otherwise: `_Not specified._`>

## Screenshots
<for each entry in image_urls: `![<filename>](<raw_url>)` on its own line. If image_paths is empty, write: `_None provided._`. If upload was attempted but failed, write: `_Upload failed — see triage comment._`>

---
Submitted via `/bug-submit` on <YYYY-MM-DD>.
```

Compute `<YYYY-MM-DD>` from `date -u +%Y-%m-%d`.

Write the body to a `mktemp` file so you don't have to shell-escape multi-line content, then create the issue:

```bash
gh issue create \
  --title "<title>" \
  --body-file <tmpfile> \
  --label bug
```

If `--label bug` fails because the label does not exist in the repo, retry the command **once** without `--label bug`. Do not invent labels and do not create labels on the repo.

Capture the issue URL from stdout (it's the only line of output on success). Derive the issue number as the trailing path segment. Record `issue_url` and `issue_number`. Remove the `mktemp` file once the command returns.

## Step 6 — Triage the issue and add a comment

Spend a focused effort understanding the bug before commenting — but **cap the investigation** so this step doesn't sprawl into a full debug session:

1. Skim the repo structure (`ls` of project root, plus any obvious entry-point folders such as `src/`, `app/`, `lib/`).
2. Grep for keywords from the bug description (component names, error messages, function names, route paths, visible UI strings). Limit to ~3 focused searches.
3. Read **at most 2 files** that look most directly relevant. Stop once you have enough to form an initial hypothesis — you are not fixing the bug, only triaging it.

Form a working understanding covering, in order:

- **Summary of understanding** — one or two sentences restating the problem in your own words. This is the most important part: a developer should be able to read just this line and know what they're picking up.
- **Probable affected area** — file paths, modules, or components most likely involved. State confidence honestly (e.g. "likely", "possibly", "uncertain"). If you read specific files, reference them as `path/to/file.ext:line` where applicable.
- **Severity (rough estimate)** — `low` / `medium` / `high` / `critical`, with a short justification anchored to user-visible impact (data loss, blocking, degraded experience, cosmetic).
- **Initial hypothesis** — your best guess at the root cause area, if anything stands out. If nothing does, say so plainly — do not invent.
- **Missing information that would help reproduce** — anything the report doesn't cover that a developer would need. Omit the section entirely if everything needed is already in the report.
- **Suggested next steps** — 1–3 concrete actions (e.g. "confirm repro on latest main", "check `path/to/file.ext` for null handling around line N", "add server logs around `<function>`").

Write the comment to a `mktemp` file and post:

```bash
gh issue comment <issue_number> --body-file <tmpfile>
```

Comment template (omit sub-sections with no content rather than writing an empty placeholder):

```markdown
## Initial triage

**Summary of understanding:** <…>

**Probable affected area:** <…>

**Severity (rough estimate):** <level> — <one-line justification>

**Initial hypothesis:** <… or "Nothing obvious from a quick read of the repo.">

**Missing information that would help reproduce:**
- <…>

**Suggested next steps:**
- <…>

---
Posted by `/bug-submit` triage on <YYYY-MM-DD>.
```

Keep the comment under ~25 lines. The point is a useful starting point for whoever picks the issue up, not a full investigation. Remove the `mktemp` file once the command returns.

## Step 7 — Capture lessons

Invoke the `lessons-capture` skill in this plugin via the `Skill` tool with the single argument `bug-submit`. It runs the reflection protocol, appends a dated entry to `~/.claude/dev-skills/lessons/bug-submit.md`, and returns the entry body for you to paste under the *Skill-improvement recommendations* heading in Step 8.

Do not run the reflection inline — `lessons-capture` is the single source of the protocol for all skills in this plugin.

## Step 8 — Present highlights

In chat, output a short, scannable summary so the user has the pointers they need without re-reading the whole conversation:

```
Issue created: <issue_url>

**Title:** <issue title>

**Triage**
- Probable area: <…>
- Severity: <level>
- Hypothesis: <one line>

**Attachments:** <count> image(s)<, gist: <gist_url> if any>

**Skill-improvement recommendations**
- <single item from Step 7, or the line "No skill-improvement recommendations from this run.">
```

Keep the chat output under ~20 lines. The issue and its triage comment are the artefacts; the chat is the pointer.

## Constraints (non-negotiable)

- **No issue or comment created without a substantive description.** If Step 3 fails to elicit one, stop with no GitHub-side state created.
- **Mandatory clarification step.** Step 3 runs even when the harness instructs autonomous operation. Closing material ambiguity is the whole point.
- **Never post secrets.** If the description, an image filename, or anything pulled from the conversation looks like it contains a credential (API keys, tokens, passwords, private connection strings), redact it in the issue body and the triage comment, and warn the user once before posting. Never include redacted values themselves — the redaction must be irrecoverable.
- **Image upload via secret gist only.** Do not upload to public gists, do not push to branches, do not commit images into the repo. If gist upload fails, fall back to a text-only issue.
- **Triage is grounded, not invented.** Step 6 must read real files in the repo before hypothesising. If nothing in the codebase looks relevant after a short search, say so in the comment — do not fabricate a hypothesis.
- **Severity is best-effort.** Never claim certainty about severity from a bug report alone; the comment is a starting point, not a verdict.
- **One issue per invocation.** Do not split a bug into multiple issues automatically — if the description covers two separate bugs, surface that in the triage comment and let the user split them deliberately.
- **No symlinks. No leftover temp files.** Clean up any `mktemp` files used for issue/comment bodies once posted.
- **Language-agnostic.** Do not bake in tooling specific to one ecosystem when reading the repo for triage. Adapt to whatever stack the repo is on.
- **Lessons capture runs every time.** Step 7 always invokes `lessons-capture`; whether it produces a recommendation or "none this run" is decided by that skill.
