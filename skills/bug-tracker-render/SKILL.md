---
name: bug-tracker-render
description: Internal helper invoked only by other skills in this plugin (e.g. bug-submit, bug-fix) to (re)generate the repo-wide bugs/bugs-tracker.html from the plugin's tracker template plus the current filesystem state. Scans bugs/ (open) and bugs/archive/ (closed), renders each bug as an expandable Issues card with relative-path screenshots, and writes the tracker. Holds no state of its own — everything is re-derived on every call, so it both creates the tracker the first time and updates it thereafter. Never touches bug folders or report .md files. Not user-invocable.
user-invocable: false
allowed-tools: Read, Edit, Bash(git *), Bash(find *), Bash(cp *), Bash(mkdir *), Bash(ls *), Bash(test *), Bash(date *), Bash(basename *)
---

# bug-tracker-render

Invoked as a sub-step of another skill in this plugin (currently `bug-submit` and `bug-fix`) whenever the set of bugs on disk changes. Regenerates `bugs/bugs-tracker.html` from the plugin's `templates/feature-tracker.html` template + the current filesystem.

Externalising this keeps the tracker-rendering logic in exactly one place — the same reason `feature-resolve` and `lessons-capture` are separate skills. Callers must **not** inline tracker rendering; they invoke this skill instead.

The tracker is a **generated artefact**: it carries no state of its own, so this skill rebuilds it wholesale every call. That makes "create" and "update" the same operation, and means open-vs-closed is always re-derived from folder location — never stored.

## Step 1 — Locate the repo and the template

- `git rev-parse --show-toplevel` → `repo_root`. If it fails (not a git work tree), output `bug-tracker-render: skipped — not in a git work tree` and stop. The caller is responsible for ensuring we're in a repo.
- Locate the plugin template (mirror `feature-resolve`):

  ```bash
  find ~ -path "*dev-skills*/templates/feature-tracker.html" 2>/dev/null
  ```

  - **Try the running plugin's own copy first** — this skill's announced base directory is `…/dev-skills/<version>/skills/bug-tracker-render`, so the template is at `<base>/../../templates/feature-tracker.html`. Use it if it exists; no search needed, and it matches the running plugin version.
  - Otherwise run the `find` above. The `*dev-skills*` form is deliberate — installed plugins live at `…/dev-skills/<version>/templates/`, which the narrower `*/dev-skills/templates/…` pattern silently misses.
  - Exactly one match → use it.
  - Multiple matches → prefer one under a `plugins/cache/` path at the **highest** version over a working clone. Don't key this on `~/.claude/`: a profile directory can live elsewhere, and versions are cached side by side.
  - Zero matches → do **not** fail. Output `bug-tracker-render: skipped — template not found` and stop. The bug folders are the durable record regardless.

`tracker_file` = `<repo_root>/bugs/bugs-tracker.html`.

## Step 2 — Copy the template into place

```bash
mkdir -p "<repo_root>/bugs"
cp "<template>" "<tracker_file>"
```

Always overwrite — the tracker holds no state of its own; everything is re-derived below.

**Then `Read` the copied file once, before any `Edit` call.** The copy was made by a shell command, so the `Edit` tool has no read-state for it and *every* substitution below fails on its first attempt otherwise — roughly twenty-five wasted tool calls per regeneration, all of which then have to be retried. Reading any portion of the file is enough to satisfy this; read it once here rather than discovering the problem at the first token.

## Step 3 — Set the bug-tracker chrome

These tokens are literal in the fresh copy. Use `Edit`, and for any token that occurs more than once (e.g. `{{FEATURE_TITLE}}` appears in both `<title>` and the header) replace **all** occurrences:

- `<body>` → `<body data-tracker-kind="bugs">` (switches the template to the bug-tracker view: only the Issues tab, no stepper, no feature tabs). There is exactly one `<body>` tag in the file.
- `{{FEATURE_TITLE}}` → `Bug Tracker`.
- `{{FEATURE_VERSION}}` → empty string, and `{{FEATURE_SLUG}}` → empty string (both hidden on the bug view).
- `{{GENERATED_AT}}` → `date -u +%Y-%m-%d`.
- Each of the twenty feature-panel tokens → empty string (those panels are hidden, but don't leave literal `{{...}}` in the file): `{{BRAINSTORMING_AT}}`, `{{BRAINSTORMING_BULLETS}}`, `{{BRAINSTORMING_DETAILS}}`, `{{BRAINSTORMING_USAGE_CHIP}}`, `{{BRAINSTORMING_USAGE}}`, `{{DESIGN_AT}}`, `{{DESIGN_BULLETS}}`, `{{DESIGN_DETAILS}}`, `{{DESIGN_USAGE_CHIP}}`, `{{DESIGN_USAGE}}`, `{{PLAN_AT}}`, `{{PLAN_BULLETS}}`, `{{PLAN_DETAILS}}`, `{{PLAN_USAGE_CHIP}}`, `{{PLAN_USAGE}}`, `{{IMPLEMENTATION_AT}}`, `{{IMPLEMENTATION_BULLETS}}`, `{{IMPLEMENTATION_DETAILS}}`, `{{IMPLEMENTATION_USAGE_CHIP}}`, `{{IMPLEMENTATION_USAGE}}`. The last eight are the run-usage tokens `usage-report` fills on a feature tracker; the bug tracker has no run to report, so they blank like the rest.

## Step 4 — Gather the bugs

Scan both locations (maxdepth 1, directories named `bug-*`):

```bash
find "<repo_root>/bugs" -maxdepth 1 -type d -name 'bug-*' 2>/dev/null         # open
find "<repo_root>/bugs/archive" -maxdepth 1 -type d -name 'bug-*' 2>/dev/null  # closed
```

For each bug folder, read its `bug-<N>-<slug>.md` and extract: the number `N`, the title (from the `# Bug <N>: <title>` heading), the severity word (first token of the **Severity** line, lowercased — one of `low|medium|high|critical`), the filed date, and the report body. List the image files in the folder (anything ending `.png/.jpg/.jpeg/.gif/.webp/.bmp`). Sort each list by `N` **descending** (newest first).

## Step 5 — Render one card per bug

Use this shape. `data-status` is `open` or `closed`, and the image `src` prefix differs between the two (see below):

```html
<details class="issue" data-status="open">
  <summary class="issue-summary">
    <span class="issue-number">#<N></span>
    <span class="issue-title"><title></span>
    <span class="issue-sev sev-<level>"><level></span>
    <span class="issue-date"><filed date></span>
  </summary>
  <div class="issue-body prose">
    <h3>Description</h3>
    <p><description></p>
    <!-- Expected behaviour / Steps to reproduce: add an <h3> + content only when the report has real content (skip "Not specified"). -->
    <!-- Screenshots: one <img> per image, omit the block entirely if none. -->
    <h3>Screenshots</h3>
    <img src="<img-src>" alt="<filename>" />
    <h3>Triage</h3>
    <p><strong>Summary:</strong> <…></p>
    <p><strong>Probable area:</strong> <…></p>
    <p><strong>Hypothesis:</strong> <…></p>
    <p><strong>Next steps:</strong> <…></p>
    <!-- Resolution: if the report has a "## Resolution" section (closed bugs fixed by /bug-fix), render it here as <h3>Resolution</h3> + its content. -->
  </div>
</details>
```

Image `src` is **relative to the tracker** (which lives at `bugs/`):

- open bug → `bug-<N>-<slug>/<filename>`
- closed bug → `archive/bug-<N>-<slug>/<filename>`

Keep the body faithful but light — it mirrors the report. Escape any literal `<`, `>`, `&` in the bug text so they render as text, not markup.

## Step 6 — Write the three regions

With `Edit`, replace the placeholder content the fresh template ships between each marker pair (leave the marker comments themselves in place):

- `Awaiting /bug-submit` (between the `ISSUES_AT` start/end markers) → `Updated <UTC timestamp>` from `date -u +"%Y-%m-%d %H:%M UTC"`.
- `<p class="empty">No open issues.</p>` (between the `ISSUES_OPEN` start/end markers) → the concatenated **open** cards. Leave the placeholder if there are no open bugs.
- `<p class="empty">No closed issues.</p>` (between the `ISSUES_CLOSED` start/end markers) → the concatenated **closed** cards. Leave the placeholder if there are no closed bugs.

Do not touch any other part of the file. The Open/Closed counts render automatically from the cards at load time — never write them.

## Step 7 — Report

Output a single status line for the caller, e.g.:

```
bug-tracker-render: bugs/bugs-tracker.html updated — <O> open, <C> closed
```

or, if Step 1 bailed: `bug-tracker-render: skipped — <reason>`.

## Constraints (non-negotiable)

- **Never touch bug folders or report `.md` files.** This skill only reads them and writes `bugs/bugs-tracker.html`. Creating/moving/closing bugs is the caller's job.
- **Always regenerate wholesale.** Never try to patch a single card in place — rebuild from template + filesystem so the tracker can never drift from reality.
- **Status is derived, never stored.** Open = a folder in `bugs/`; closed = a folder in `bugs/archive/`. There is no status field to keep in sync.
- **No symlinks.** Always `cp` the template; never `ln -s`.
- **Relative image paths only.** Never embed remote URLs or absolute paths; the tracker and images ship together under `bugs/`.
- **Degrade, don't fail.** If the template can't be found or we're not in a repo, emit a one-line skip note and return — never abort the calling skill.
