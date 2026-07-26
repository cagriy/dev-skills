---
name: feature-storm
description: Brainstorm the high-level product / requirements view of a feature before any technical design work. Use when the user wants to think through a feature at the product layer — goals, scope, users, rough technical direction — without committing to a design yet. Typically the first step in the feature-storm → feature-design → feature-plan → feature-implement chain, but optional; /feature-design can start from cold. Establishes initial requirements with the user, calls /feature-resolve to allocate the feature folder, runs a structured brainstorming loop until the user approves a ≤10-bullet summary, writes feature-storm-v<N>-<desc>.md, updates the per-feature tracker (header + storming section + progress bar), captures lessons, and offers to chain into /feature-design. Step 0 confirms with the user via AskUserQuestion before doing any work when invoked proactively; the confirmation is skipped when the user explicitly typed /feature-storm or just chained in from /feature-dispatch.
user-invocable: true
disable-model-invocation: false
argument-hint: <free-form requirements (optionally including v<N> and a short title), or omit to be asked>
allowed-tools: Read, Grep, Glob, Write, Edit, AskUserQuestion, Skill, WebFetch, WebSearch, Bash(ls *), Bash(find *), Bash(mkdir -p *), Bash(test *), Bash(cp *), Bash(pwd), Bash(date *)
---

# feature-storm — High-level Product/Requirements Brainstorm

You are running the `feature-storm` skill. The user may have arrived here by typing `/feature-storm` (with optional free-form requirements in `$ARGUMENTS`) or because the model proactively invoked the skill. Your job is to brainstorm a feature at the **product/requirements layer** — goals, users, scope, rough technical direction — and persist the result as a brainstorm document plus an updated per-feature tracker. Deep technical design is **out of scope** for this skill; that is what `/feature-design` is for.

**Terminology (plugin-wide).** Two words are overloaded; keep them apart. A **step** is a numbered step of *this skill's own procedure* — the `## Step …` headings below (e.g. *Step 4*); the only other "steps" are the **TDD steps** inside a plan stage (write test → confirm fail → implement → confirm pass). A **stage** has two senses: a **chain stage** is one of `storm → design → plan → implement` (it shows up as `stage=…`, `stage_file`, and the tracker's `data-stage`), while a **plan stage** is a committable unit of work *inside* the implementation plan (e.g. `Stage 1`) — `/feature-plan` creates these and `/feature-implement` builds one per commit. A procedure step is never a plan stage, and a plan stage is never a procedure step.

This skill has ten steps (Steps 0–9). Execute them in order. Do not skip Step 0 (proactive-invocation confirmation), Step 3 (clarification loop), Step 4 (approval gate), Step 6 (tracker update), or Step 7 (lessons capture) — they are the load-bearing steps.

## Step 0 — Confirm before proceeding (when invoked proactively)

Check the most recent user message in the conversation for the literal tag `<command-name>/feature-storm</command-name>` (or, equivalently, a leading `/feature-storm` typed by the user). If present, the user has explicitly opted in via the slash command — skip this step and continue with Step 1.

Also treat as opt-in (and skip this step) if you were just invoked as a chain from `/feature-dispatch` — i.e. the immediately previous turn was an `AskUserQuestion` result with header `"Route this feature?"` and the user selected an option whose label starts with `"Run /feature-storm"`. In that case the user has already confirmed via the dispatcher; do not re-ask.

Otherwise (you arrived here because the model decided to invoke this skill proactively from natural-language intent, with no recent chained opt-in), call `AskUserQuestion` exactly once before any other work. Frame the question concretely so the user can correct your interpretation in the same step:

- **question**: `"Launch /feature-storm to brainstorm requirements for <your one-line restatement of what the user asked for>?"` — replace `<...>` with the specific scope you'd brainstorm.
- **header**: `"Run /feature-storm?"`
- **options**:
  - `{ "label": "Yes, proceed", "description": "Run the skill and produce the brainstorm document plus updated tracker." }` (mark this as Recommended)
  - `{ "label": "No", "description": "Don't run; I'll redirect." }`

If the user picks "No" or "Other", stop immediately and do not start Step 1. Do not write any files or ask further questions.

## Step 1 — Establish initial requirements

Parse `$ARGUMENTS`. Detect three pieces of input, any of which may be absent:

- **Explicit version token.** Look for a leading `v<major>` or `version <major>` (case-insensitive; bare `1` does **not** count — only `v1` / `v 1` / `version 1`). If found, record it as `explicit_version` and strip it from the remaining text. Note: under this plugin's scheme, versions are integers only — no minor versions.
- **Candidate short title.** Look for an obvious short phrase (e.g. wrapped in quotes, or a `title=<phrase>` slot, or unambiguously the leading 2–8 words of the input). If found, record it as `candidate_description`.
- **Free-form requirements text.** Everything else is the initial requirements statement.

Resolve the requirements statement:

- If the remaining free-form text has **more than ~5 meaningful words**, use it as the initial requirements statement.
- If it is empty or trivially short, make exactly one `AskUserQuestion` call asking the user what feature they want to brainstorm. Their answer becomes the initial requirements statement.

You must have a real requirements statement before continuing. If the user declines to provide one (e.g. answers "nevermind"), stop the skill cleanly with no files written.

**Ground brownfield requirements before clarifying.** If the requirements cite prior feature versions (e.g. `v9`, `v11`) or existing code/config symbols, or propose changing the current repo's existing behaviour, do a quick grounding read of those (the prior storm/design docs, the named symbols, or the relevant code path) before the Step 3 clarification round — enough to make the questions and their options fact-based. Stay at product altitude: you're confirming what exists and what's load-bearing, not designing. Grounding covers external references too: fetch and read any linked design/spec artifact the brief cites (mockups, design-tool links, shared specs) before the Step 3 round, and when a named third-party service or API is load-bearing and the user's assumption about it is unverified (auth model, sync vs async, key handling), do a quick docs/web feasibility check first — the questions must be fact-based from the first round.

## Step 2 — Resolve the feature folder via `feature-resolve`

Before calling the resolver, settle the **brief description** that will go into the folder name. Rules:

1. If `candidate_description` was lifted verbatim from a clearly-delimited title slot in the user's input (quoted, a `title=` slot, or a standalone leading line) *and* is ≤10 words *and* looks filename-safe — proceed with it **without a confirmation question**. State the chosen folder title in one line of prose; the Step 4 approval gate is the correction point.
2. Otherwise, derive a candidate (≤10 words, ideally 2–5) from the requirements statement. Strip articles/filler ("a", "the", "for users", "system"), preserve meaning, normalise spacing to single spaces, preserve the user's case where natural (e.g. proper nouns stay capitalised).
3. A **derived** candidate needs confirming — but prefer folding the confirmation into the first Step 3 `AskUserQuestion` bundle (as one of its up-to-4 questions, deferring the resolver invocation below until that round returns) rather than spending a standalone round-trip on the title alone. Whichever position it takes, ask it **exactly once**:
   - **question**: `"Use this short title for the feature folder: \"<candidate>\"?"`
   - **header**: `"Feature title"`
   - **options**:
     - `{ "label": "Yes, use this", "description": "Continue with \"<candidate>\". Folder will be features/feature-v<N>-<hyphenated>/." }` (mark this as Recommended)
     - `{ "label": "Edit it", "description": "Give a different short title (≤10 words)." }`
   - If the user picks "Edit it" or selects "Other" with a revised title, take that text as the description and re-validate ≤10 words. If they over-shoot, ask once more for a shorter version. Do not silently truncate.

Now invoke `feature-resolve` via the `Skill` tool. (If the title confirmation was folded into Step 3's first bundle, run that round first, then return here and invoke the resolver with the confirmed title — the rest of this step is unchanged.) Build the argument string:

```
stage=storm[, version=<N>][, description=<confirmed phrase>]
```

Include `version=` only if `explicit_version` was set in Step 1. Include `description=` always (the resolver may ignore it if continuing into an existing folder, but that's fine — pass it for the create-new case).

Parse the resolver's output block. Record these fields verbatim — every later step uses them:

- `mode` (`create-new` or `continue-existing`)
- `version` (integer `N`)
- `description` (the **authoritative** hyphenated description; use this everywhere downstream, even if the user's input differed)
- `feature_folder` (absolute path)
- `stage_file` (absolute path — this is where Step 5 writes)
- `tracker_file` (absolute path — this is what Step 6 edits)
- `notes` (any caveats; surface to the user only if non-trivial)

If the resolver stops with an error (e.g. plan/implement prereq missing — shouldn't happen for storm, but other error paths exist), pass the message to the user verbatim and stop. Do not retry with invented arguments.

**`feature-resolve` runs inline in this turn — do not end your turn when its result block appears.** The `Skill` tool loads it into your own context rather than delegating to a subagent, so the block is a checkpoint in the middle of *your* run, not a hand-off that returns control anywhere. Once you've recorded the fields above, continue straight into Step 3 in the same turn. Stopping here strands the user with a seeded folder, an empty tracker, and no brainstorm.

## Step 3 — Discuss specifics

**This step is mandatory even in auto / non-interactive mode.** If the user or the harness has told you to "work without stopping" or "skip clarifying questions", that instruction does **not** apply here — converging on product intent before writing the brainstorm document is the entire purpose of this skill. Ask the questions anyway.

Iteratively use `AskUserQuestion` (1–4 questions per call) to converge on the product picture. **Always present options with a recommendation** rather than open-ended prompts — the user can still pick "Other" to redirect. **Pace the bundle size to the user's footing:** for technically-uncertain or feasibility-gated features, open with the single highest-leverage question (or a short feasibility note) and expand to 3–4 question rounds only once the user is answering decisions rather than clarifying what's possible. **Sequence by dependency:** ask the foundational decisions whose answers constrain later questions first (e.g. where a component runs relative to its clients before how they communicate or authenticate), so a late-surfacing upstream fact doesn't invalidate answers already given. Cover at minimum:

- **Goals** — concrete outcomes the feature should achieve.
- **Non-goals** — what is explicitly out of scope (deferred, not "won't ever do").
- **Users & scenarios** — who uses this, in what context, what they're trying to accomplish.
- **Scope (in / out)** — what's in this feature vs. what's deferred to later iterations.
- **High-level technical direction** — hard constraints, ecosystem (cloud, platform, runtime), integrations, performance/security ceilings the design must respect. **Stay high-level** — do not solve the design; surface the constraints the design must honour.
- **Alternatives** — meaningfully different product-level approaches considered, and why the chosen direction wins.
- **Risks** — what could go wrong with this feature (adoption, data, integration, exposure), at product altitude.
- **Open questions for design** — the decisions you can already see `/feature-design` will need to close.

After each round, restate your working understanding internally and cross-check the answers for contradictions — when selections conflict (e.g. two mutually-exclusive options picked in one round), immediately re-ask to reconcile rather than relying on inline option warnings to have prevented the pick. Ask another round only if a remaining ambiguity would meaningfully change the brainstorm. Stop when the remaining uncertainty is at the design level, not the requirements level. Don't pad with questions for their own sake — and don't stop early to avoid friction.

Keep the conversation product-flavoured. If a question would require resolving a deep technical decision (specific algorithm, schema shape, library choice), defer it to design and record it as an open question instead.

## Step 4 — Summarise and gate on approval

Produce a single ≤10-bullet summary of where the brainstorm has landed. Each bullet should be a complete, scannable statement (not a fragment). Aim to cover, in roughly this order: what the feature is, who it's for, top 1–2 goals, top 1–2 non-goals, scope boundary, key technical constraint(s), a notable risk or rejected alternative (when one exists), 1–2 open questions for design. Cut bullets rather than overshoot 10.

Present the summary in chat as a clearly labeled block (e.g. under the heading **Brainstorm summary — for approval**). Immediately afterwards, call `AskUserQuestion` once:

- **question**: `"Approve this brainstorm summary as the input to /feature-design?"`
- **header**: `"Approve summary?"`
- **options**:
  - `{ "label": "Approve", "description": "Write feature-storm-v<N>-<desc>.md, update the tracker, and finish." }` (mark this as Recommended)
  - `{ "label": "Revise", "description": "Take me back into discussion to refine the summary." }`
  - `{ "label": "Stop", "description": "Abandon the brainstorm; do not write any files." }`

Branching:

- **Approve** → Step 5.
- **Revise** (or "Other" with feedback) → loop back to Step 3 with the user's feedback in mind. Do not skip Step 4 on the next pass — re-present a fresh ≤10-bullet summary after the next round and ask again. After three revise loops with no convergence, ask the user whether to stop or commit imperfectly to whatever the current draft is; never silently push on.
- **Stop** → exit the skill cleanly. Do not write `feature-storm-v<N>-<desc>.md`. Do not flip the progress bar to `complete` — the tracker's storm step stays at `pending`, accurately reflecting that no storm artefact was produced. Tell the user the brainstorm was abandoned.

## Step 5 — Write the brainstorm document

Write the file at the `stage_file` path returned by Step 2. Use this 7-section structure exactly — every section is required; if a section has no real content for this feature, write a one-line "Not applicable — <reason>" rather than omitting it.

```markdown
# <Human-readable title> — Brainstorm v<N>

**Status:** Draft
**Date:** <YYYY-MM-DD>

## 1. Summary
One paragraph: what we're considering building, who it's for, why now.

## 2. Goals
- Bulleted, concrete outcomes the feature should achieve.

## 3. Scope (in / out)
- **In scope:** ...
- **Out of scope / deferred:** ...

## 4. High-level technical direction
- Hard constraints, ecosystem, integrations, performance/security ceilings.
- Deliberately NOT detailed design — that lives in /feature-design.

## 5. Alternatives considered
- <Meaningfully different product-level approach> — rejected because <reason>.

## 6. Risks
- <Risk specific to this feature, with its expected impact>.

## 7. Open questions for design
- Each item is a specific decision /feature-design must close before planning.
```

Compute the human-readable title by taking the resolved `description` from Step 2, replacing hyphens with spaces, preserving case (`Add-Reminders` → `Add Reminders`). Compute `<YYYY-MM-DD>` from `date -u +%Y-%m-%d`.

Section content rules:

- **§1 Summary** is single-paragraph prose, no bullets.
- **§2 Goals**: 2–6 bullets, derived from Step 3 discussion. Each bullet must be testable (a reasonable person could agree the outcome was or wasn't achieved).
- **§3 Scope**: keep "out of scope" specific — name actual things being deferred, not generic disclaimers.
- **§4 Technical direction**: framed as constraints the design must respect, not as solutions. "Must run offline on iOS 16+" yes; "use SwiftData with CloudKit sync" no — that's for `/feature-design`.
- **§5 Alternatives considered**: 1–3 entries; each names a genuinely different approach at the product level (different scope, different UX, buy-vs-build, do-nothing) plus why it lost. Product-level alternatives only — tech-stack picks belong to `/feature-design`. "Not applicable — <reason>" requires a real reason (e.g. a mandated change with no product freedom), not a dodge.
- **§6 Risks**: each risk is specific to this feature (adoption, data, integration, security exposure, delivery — at product altitude) and names its impact. Generic boilerplate ("timeline risk") is not a risk entry.
- **§7 Open questions**: each item is a concrete decision (not "figure out the architecture"). If a question has any captured user preference, record it as an annotation: "(user leaned toward X, but didn't commit)".

After writing, record the file's absolute path — Step 8 references it.

## Step 6 — Update the tracker

`Read` the tracker file at `tracker_file`. The file should exist from Step 2; if it does not (e.g. `feature-resolve` noted `tracker_seed: skipped`), defensively copy the plugin template into place:

```bash
find ~ -path "*/dev-skills/templates/feature-tracker.html" 2>/dev/null
# cp the single match (or the ~/.claude/plugins/ one if multiple) to <tracker_file>
```

If no template can be located, skip the tracker update and note that in the final summary — do **not** fail the whole skill on a missing template.

Then apply the following edits via the `Edit` tool. For each token, check that it is still literal `{{...}}` text in the file (so you don't overwrite content from a prior stage). If a token is already substituted, skip that edit silently.

**Anchor every Edit in surrounding markup, not the bare token.** Each token also appears a second time inside the template's top-of-file documentation comment, so a bare `{{TOKEN}}` Edit fails with two matches — and `replace_all` would dump rendered HTML into that comment. Match the live occurrence via its wrapper instead, e.g. `<p class="section-timestamp">{{BRAINSTORMING_AT}}</p>` or `<div class="bullets">{{BRAINSTORMING_BULLETS}}</div>`. The one token with **two** live occurrences is `{{FEATURE_TITLE}}` — substitute both the page `<title>{{FEATURE_TITLE}}</title>` and the `<h1 class="feature-title">{{FEATURE_TITLE}}</h1>`, each with its own anchored Edit.

**Header tokens** (only edit if still literal):

- `{{FEATURE_VERSION}}` → `<N>` (integer, e.g. `3`).
- `{{FEATURE_TITLE}}` → human-readable title (e.g. `Add Reminders`).
- `{{FEATURE_SLUG}}` → `feature-v<N>-<description>` (mirrors the folder name).
- `{{GENERATED_AT}}` → today's UTC date (`YYYY-MM-DD`).

**Brainstorming section tokens** (these are this skill's own). Compute the timestamp once via `date -u +"%Y-%m-%d %H:%M UTC"` and reuse the same value for the chip:

- `{{BRAINSTORMING_AT}}` → `Updated <YYYY-MM-DD HH:MM UTC>` (the timestamp chip text — no surrounding HTML).
- `{{BRAINSTORMING_BULLETS}}` → an `<ul>` of the Step 4 approved bullets, one `<li>` per bullet, plain text content (no markdown — convert any markdown to HTML).
- `{{BRAINSTORMING_DETAILS}}` → free-form HTML drawn from §1 (Summary), §3 (Scope) and §4 (Technical direction) of the storm document. Use `<h3>` for sub-headings and `<p>` / `<ul>` for content. Order content from highest-level to most detailed so a reader can stop reading at any depth.

**Future-stage tokens** (substitute with the empty placeholder so the tracker renders cleanly before the next skill runs — only if still literal):

- `{{DESIGN_AT}}` → `Awaiting /feature-design`
- `{{DESIGN_BULLETS}}` → `<p class="empty">Not yet filled — pending /feature-design.</p>`
- `{{DESIGN_DETAILS}}` → `<p class="empty">Not yet filled — pending /feature-design.</p>`
- `{{PLAN_AT}}` → `Awaiting /feature-plan`
- `{{PLAN_BULLETS}}` → `<p class="empty">Not yet filled — pending /feature-plan.</p>`
- `{{PLAN_DETAILS}}` → `<p class="empty">Not yet filled — pending /feature-plan.</p>`
- `{{IMPLEMENTATION_AT}}` → `Awaiting /feature-implement`
- `{{IMPLEMENTATION_BULLETS}}` → `<p class="empty">Not yet filled — pending /feature-implement.</p>`
- `{{IMPLEMENTATION_DETAILS}}` → `<p class="empty">Not yet filled — pending /feature-implement.</p>`

**Progress bar** (mandatory transition — only fired in this step, after the brainstorm document is written):

- old_string: `data-stage="storm" data-state="pending"`
- new_string: `data-stage="storm" data-state="complete"`

If this Edit fails, the storm step is already `complete` (e.g. backfill on a fully tracked feature) — leave it alone.

Do **not** touch other skills' tokens (`{{BRAINSTORMING_*}}` aside, the design / plan / implementation content sections belong to those skills once they fill them with real content — the empty-placeholder fallback above is only for tokens that are still literal). Do **not** touch other skills' progress steps.

## Step 7 — Capture lessons

Invoke the `lessons-capture` skill in this plugin via the `Skill` tool with the single argument `feature-storm`. It runs the reflection protocol, appends a dated entry to `~/.claude/dev-skills/lessons/feature-storm.md`, and returns the entry body (a single recommendation in three lines, or the "No skill-improvement recommendations from this run." line) for you to paste under the *Skill-improvement recommendations* heading in Step 8's chat summary.

Do not run the reflection inline — `lessons-capture` is the single source of the protocol for all skills in this plugin.

## Step 8 — Present highlights

In chat, output a short, scannable summary so the user doesn't need to open the files to get the gist. Use this shape:

```
Saved: <stage_file path>
Tracker: <tracker_file path>

**Feature:** v<N> — <human-readable title>

**Brainstorm bullets**
- <bullet 1>
- <bullet 2>
- ...
(up to the 10 approved in Step 4)

**Top open questions for design**
- <1–3 items lifted from §7>

**Skill-improvement recommendations**
- <single item from Step 7, or the line "No skill-improvement recommendations from this run.">
```

Keep the chat output under ~30 lines. The files are the artifact; the chat is the pointer.

## Step 9 — Offer to chain into /feature-design

Call `AskUserQuestion` exactly once:

- **question**: `"Continue with /feature-design to produce the technical design for this feature?"`
- **header**: `"Run /feature-design?"`
- **options**:
  - `{ "label": "Yes, run /feature-design", "description": "Launch the design skill against the brainstorm just saved." }` (mark this as Recommended)
  - `{ "label": "Not now", "description": "Stop here; the brainstorm is saved." }`

If the user picks "Yes, run /feature-design", invoke the `feature-design` skill via the `Skill` tool with the single argument `v<version>` (the integer feature version resolved in Step 2). Passing the version anchors the downstream resolver to the same feature folder explicitly; design also still picks up the storm's bullets and description from conversation context, but the version arg removes any ambiguity if other half-completed feature folders exist on disk.

If the user picks "Not now" or "Other", emit exactly one line before stopping:

```
**Next step:** when you're ready, run `/feature-design v<version>`.
```

Do not skip this step or substitute the AskUserQuestion with prose. The offer is the affordance; rendering it as a question is what makes it one-click. The "Next step" hint is only emitted on decline — when the user accepts the chain, no hint is needed because the next skill is already running.

## Constraints (non-negotiable)

- **Output lives under `features/feature-v<N>-<description>/`**, not under `docs/`. Pathing is handled exclusively by `feature-resolve` in Step 2 — never invent paths.
- **No technical design decisions.** Storm captures *constraints* the design must respect, *not* the design itself. If a discussion drifts into specific schemas / algorithms / libraries, redirect to "this is a question for /feature-design" and record it as an open question.
- **Approval gate is mandatory.** Step 4 must produce a user-approved summary before any file is written. A "Stop" decision means no files written — do not partial-write.
- **Mandatory clarification step.** Step 3 runs even when the harness instructs autonomous operation. Closing material product ambiguity is the whole point.
- **Description is authoritative from `feature-resolve`.** When continuing into an existing folder, the folder's description wins — even if the user's `$ARGUMENTS` suggested a different title. Surface the resolver's `notes` to the user if it flagged a description conflict.
- **No minor versions.** This plugin uses integer feature versions only. Pass `version=<N>` to the resolver, never `<N>.<M>`.
- **Self-contained tracker edits.** Substitute only tokens that are still literal `{{...}}`; never overwrite content placed by another skill. The progress bar's `data-stage="storm"` entry is this skill's alone to touch.
- **Lessons capture runs every time.** Step 7 always invokes `lessons-capture`; whether it produces a recommendation or "none this run" is decided by that skill.
- **Never paste the entire storm document into chat.** Step 8 is the bullet summary plus pointers; the user opens the file for full content.
- **No symlinks.** When copying the tracker template defensively in Step 6, always copy — never link.
