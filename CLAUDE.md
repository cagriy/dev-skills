# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A Claude Code **plugin** (`.claude-plugin/plugin.json`, name `dev-skills`) that ships a TDD-driven feature workflow plus a few standalone helper skills under `skills/`. There is no application code, no build step, no test suite — the artifact is the SKILL.md content itself. Changes ship as edits to the markdown skill definitions plus the `templates/feature-tracker.html` template.

The skills divide into two groups:

- **Feature chain** — `feature-storm`, `feature-design`, `feature-plan`, `feature-implement`, plus the internal `feature-resolve` they all delegate to for pathing.
- **Standalone helpers** — `bug-submit` (file a triaged bug report as a local entry under `bugs/` in the current repo). These do not use `feature-resolve` and do not write under `features/`.
- **Reflection / improvement** — `lessons-capture` (internal, called by every skill in the plugin) and `lessons-learn` (user-only, periodic).

## The skill chain (architecture)

```
/feature-storm  →  /feature-design  →  /feature-plan  →  /feature-implement
       │                │                  │                   │
       │                │                  │                   │
       ├────────────────┴──────────────────┴───────────────────┤
       │     each one calls feature-resolve at the start       │
       │     (folder, version, stage_file, tracker_file)       │
       │                                                       │
       └─────── each one's final step calls lessons-capture ───┘
                            │
              ~/.claude/dev-skills/lessons/<slug>.md
                            ↑
       /dev-skills:lessons-learn <slug> (user-invoked, periodic)
```

Per-feature output structure (in the **target project's** cwd):

```
features/
  feature-v<N>-<description>/
    feature-storm-v<N>-<description>.md       ← optional
    feature-design-v<N>-<description>.md
    feature-plan-v<N>-<description>.md
    feature-implement-v<N>-<description>.md   ← (future stage; not yet emitted by /feature-implement)
    feature-v<N>-tracker.html                 ← seeded by feature-resolve, updated by each stage
```

- **`feature-storm`** *(optional)* — high-level product/requirements brainstorm. Asks the user for goals, scope, users, technical constraints, open questions. Writes a 5-section storm.md. Step 0 is the proactive-confirmation gate.
- **`feature-design`** — produces the technical design under `features/feature-v<N>-<desc>/feature-design-v<N>-<desc>.md`. Clarification loop (Step 4) and self-review (Step 6) are load-bearing — skipping them defeats the skill. Can start cold (no storm) or pick up from a just-saved storm via Step 0 chain-in.
- **`feature-plan`** — produces `feature-plan-v<N>-<desc>.md` under the same feature folder. Refuses to run without an existing design; refuses if design §8 (Open questions) is non-empty. The plan file is named directly off the resolver — there is no separate plan-versioning.
- **`feature-implement`** — executes the plan stage-by-stage on the **current branch**. Never creates branches, never pushes, one commit per green stage. Resumes from the last committed stage by `git log --grep`. Detects project tooling (`TEST`/`LINT`/`FORMAT_CHECK`/`TYPE_CHECK`/`BUILD`) from manifests + CI config and reuses those slot names throughout. Establishes a test/lint baseline in Step 3 so pre-existing failures aren't gated as regressions.
- **`feature-resolve`** — internal-only (`user-invocable: false`). Called at the start of every feature-* skill with `stage=<slug>[, version=<N>][, description=<phrase>]`. Computes the correct `features/feature-v<N>-<desc>/` folder, creates it on first use, seeds `feature-v<N>-tracker.html` from the plugin template, and returns a parseable resolution block (`mode`, `version`, `description`, `feature_folder`, `stage_file`, `tracker_file`, `prereq_file`, `notes`). Never creates or edits stage `.md` files. Decides create-new vs continue-existing based on whether the latest folder already has the requested stage's file.
- **`bug-submit`** — standalone (not part of the feature chain). Files a bug report as a local folder under `bugs/` in the current repo for a bug the user just hit, optionally with image attachments copied into the bug folder, and writes a `bug-N-<desc>.md` report whose triage section is grounded in a quick read of the codebase. Allocates the next bug number by scanning both `bugs/` and `bugs/archive/`. Step 8 then regenerates `bugs/bugs-tracker.html` (the bug-tracker view of the shared template) wholesale from the filesystem — an Issues tab listing open (`bugs/`) and closed (`bugs/archive/`) bugs, each expandable to its full report + screenshots. Writes only to the local filesystem — no GitHub issue, no gist, no push/commit. Step 0 is the proactive-confirmation gate; Step 3 is the mandatory clarification round; Step 9 calls `lessons-capture` with the `bug-submit` slug.
- **`lessons-capture`** — internal-only (`user-invocable: false`). Called as the final step of each skill in this plugin with the calling skill's slug. Appends one entry (or "no recommendation") to `~/.claude/dev-skills/lessons/<slug>.md` via a single atomic `>>` append. **Never edits any SKILL.md.**
- **`lessons-learn`** — user-only (`disable-model-invocation: true`). Consolidates the log for one slug, presents filtered improvements via `AskUserQuestion`, edits the target `SKILL.md`, then archives the entire active log as a UTC-stamped snapshot. Never auto-commits.

The reflection protocol lives in `lessons-capture` alone, and the convention/version logic lives in `feature-resolve` alone — the feature-* skills used to inline both and drifted, so each got extracted. Don't reintroduce inline reflection or inline `features/` scanning in the feature-* skills.

## Non-negotiable invariants to preserve when editing skills

These are spread across the skill files but easy to break with a well-meaning edit:

- **Feature-* skill artefacts live under `features/feature-v<N>-<description>/`**, in the target project's cwd. `docs/` is **legacy** — feature-* skills may read it for grounding context but never write to it. The lessons log under `~/.claude/dev-skills/` is the only feature-* output that lives outside the project. Standalone helpers (e.g. `bug-submit`) do not write under `features/` — `bug-submit` writes its artefacts under `bugs/` in the target repo: a `bugs/bug-N-<description>/` folder per bug (report markdown plus copied-in images), a regenerated `bugs/bugs-tracker.html`, plus its own lessons log entry.
- **`feature-resolve` is the single source of pathing.** Feature-* skills never glob `features/`, never increment versions themselves, and never construct stage file paths by string concatenation. They invoke `feature-resolve` and use its returned `feature_folder` / `stage_file` / `tracker_file` / `prereq_file` verbatim.
- **Integer versions only.** `v1`, `v2`, `v10` — never `v1.0`, `v1.2`. Numeric compare on version (so `v10` > `v9`). No minor-version revisions of stage files — to revise, you re-run the stage on a new feature version (default) or pass an explicit `version=<N>` to overwrite (resolver asks).
- **Step 0 (proactive-invocation confirmation) gate.** Each feature-* skill checks for the literal `<command-name>/<slug></command-name>` tag, or a chained opt-in from the previous skill's final step. Otherwise it calls `AskUserQuestion` once before doing anything. For `feature-implement` this is strictly enforced because it writes code and commits.
- **Clarification steps run even in auto / non-interactive mode.** The skills explicitly override "skip clarifying questions" instructions — closing material ambiguity is the whole point. Don't add a bypass.
- **Skills are deliberately language-agnostic.** `lessons-learn` filter #3 actively drops or rewrites language/framework-specific suggestions. When editing a skill, keep examples as illustrative lists across ecosystems, not as a single canonical command.
- **Tracker token substitution is defensive.** Each skill substitutes only tokens that are still literal `{{...}}` — never overwrites content placed by an earlier stage. Future-stage tokens get the empty placeholder (`<p class="empty">Not yet filled — pending /feature-<step>.</p>`) the first time the tracker is touched.
- **Tracker progress bar is owned per stage.** Each skill flips its own `data-stage="<slug>" data-state="pending"` → `complete` as part of its tracker update step, only when the stage file is written / committed (or finalised — for `/feature-implement`, after all stages are green). There is no in-flight `current` state: a step is either grey (not done) or green (done). Never touch another skill's `data-stage` entry.
- **The Issues region is NOT a `{{token}}` — don't "consolidate" it into one.** The bug tracker's Issues panel is a living list owned solely by `bug-submit`, regenerated wholesale each run between `<!-- ISSUES_AT/OPEN/CLOSED:START -->…:END -->` markers. It is deliberately a different mechanism from the one-shot feature-panel tokens. Never write those literal comment markers inside the template's doc-comment block (an inner `-->` closes the doc comment early and breaks the page). Open/closed status is derived from `bugs/` vs `bugs/archive/`, and the Open/Closed counts are computed by the template's JS at load — never hand-written.
- **No symlinks anywhere.** Per global convention; also enforced in the skills (including the template copy in `feature-resolve` Step 6).
- **`lessons-learn` archives by snapshotting the whole active log** (`mv` to `<slug>.archive-<UTC>.md`) — it does not write per-entry status tags into the archive. Deferred entries get written back to a fresh active log.

## Skill frontmatter contract

Each `SKILL.md` starts with YAML frontmatter. The fields that matter for behavior:

- `user-invocable: true|false` — gates whether the user can type `/<slug>`. `feature-resolve` and `lessons-capture` are `false`; `lessons-learn` uses `disable-model-invocation: true` so only the user can trigger it.
- `model: opus`, `effort: xhigh` — the four user-facing feature skills set these explicitly.
- `allowed-tools` — narrowly scoped per skill. `feature-implement` needs full `Bash`; the others use `Bash(ls *)`, `Bash(find *)`, `Bash(cp *)`, etc. `feature-resolve` adds `Bash(cp *)` for tracker seeding.
- `argument-hint` — shown in the slash-command picker.

## Files

- `skills/<slug>/SKILL.md` — the skill definitions; this is the product.
- `.claude-plugin/plugin.json` — plugin manifest.
- `templates/feature-tracker.html` — token-substitution HTML template (`{{FEATURE_VERSION}}`, `{{DESIGN_BULLETS}}`, etc.) plus a 4-step progress bar (`storm` → `design` → `plan` → `implement`) using `data-stage` / `data-state` attributes. `feature-resolve` copies this into each new feature folder; each feature-* skill substitutes its own tokens and flips its own progress step. The same template doubles as the **bug tracker**: it carries a 5th "Issues" tab and an optional `<body data-tracker-kind="bugs">` attribute that (via CSS) hides the stepper + feature tabs and shows only the Issues tab. The Issues panel is **not** `{{token}}`-driven — it is a living list regenerated wholesale by `/bug-submit` between HTML-comment markers (`<!-- ISSUES_OPEN/CLOSED/AT:START -->…:END -->`). Open vs. closed comes from `bugs/` vs. `bugs/archive/`; cards are expandable `<details>` with relative-path `<img>` screenshots.
- `.gitignore` — ignores `.DS_Store` and a local `cli/` workspace.

## Editing workflow

Edits to a `SKILL.md` are usually applied via `/dev-skills:lessons-learn <slug>` after the log accumulates signal — that path keeps changes traceable to captured runs. Manual edits are fine when fixing wording, fixing broken cross-references between skills (e.g. Step numbers in the chain, chain-in opt-in checks, tracker token names), or shipping a structural change that the lessons system can't drive.

When changing one feature-* skill, scan the other three for mirrored sections — the `feature-resolve` invocation block, the chain-in opt-in checks in Step 0, the tracker update step, and the lessons-capture call all appear in all four. Keep them aligned.

When changing `templates/feature-tracker.html`, also scan the four feature-* skills **and** `bug-submit` for any token name they substitute. Adding a new token requires assigning ownership to exactly one skill; removing a token requires deleting the substitution step in whoever owned it. Two distinct fill mechanisms coexist in this one template, so keep them straight: the **feature panels** are one-shot `{{TOKEN}}` substitutions owned by the feature-* skills; the **Issues panel** is a marker-delimited region (`<!-- ISSUES_*:START/END -->`) regenerated wholesale by `bug-submit` on every run. If you rename a marker, the `data-tracker-kind` attribute, the `data-kind="issues"` tab, the `.issue*` CSS classes, or the issue-card HTML shape, update `bug-submit` Step 8 in lockstep — that is the only consumer of the bug-tracker side of the template.
