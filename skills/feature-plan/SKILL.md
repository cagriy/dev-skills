---
name: feature-plan
description: Produce a staged, TDD-driven implementation plan that maps 1:1 to an existing feature design under features/feature-v<N>-<description>/. Use when the user asks to plan an implementation, break a feature into stages, or write a plan/roadmap for an existing design — typically as a follow-up to /feature-design. Refuses to plan without a real design file (delegated to feature-resolve). Reviews the plan for design coverage, inaccuracies, conflicts, and security issues before presenting staged highlights, then updates the per-feature tracker. Step 0 confirms with the user via AskUserQuestion before doing any work when invoked proactively; the confirmation is skipped when the user explicitly typed /feature-plan or just chained in from /feature-design.
model: opus
effort: xhigh
user-invocable: true
disable-model-invocation: false
argument-hint: <optional v<N> to target a specific feature, or omit to use the latest with a design and no plan yet>
allowed-tools: Read, Grep, Glob, Write, Edit, AskUserQuestion, Skill, Bash(ls *), Bash(find *), Bash(mkdir -p *), Bash(test *), Bash(cp *), Bash(pwd), Bash(date *)
---

# feature-plan — TDD-Staged Implementation Plan For A Design

You are running the `feature-plan` skill. The user may have arrived here by typing `/feature-plan` (with an optional version in `$ARGUMENTS`), by chaining in from `/feature-design`, or because the model proactively invoked the skill. Your job is to produce a detailed, staged, test-driven implementation plan tied to an existing design document at the path returned by `/feature-resolve`.

**Terminology (plugin-wide).** Two words are overloaded; keep them apart. A **step** is a numbered step of *this skill's own procedure* — the `## Step …` headings below (e.g. *Step 4*); the only other "steps" are the **TDD steps** inside a plan stage (write test → confirm fail → implement → confirm pass). A **stage** has two senses: a **chain stage** is one of `storm → design → plan → implement` (it shows up as `stage=…`, `stage_file`, and the tracker's `data-stage`), while a **plan stage** is a committable unit of work *inside* the implementation plan (e.g. `Stage 1`) — `/feature-plan` creates these and `/feature-implement` builds one per commit. A procedure step is never a plan stage, and a plan stage is never a procedure step.

This skill has eleven steps (Steps 0–10). Execute them in order. Do not skip Step 0 (proactive-invocation confirmation), Step 4 (design coverage check), Step 5 (clarifying questions when needed), Step 6 (review and update), Step 7 (tracker update), or Step 8 (lessons capture) — they are the load-bearing steps.

## Step 0 — Confirm before proceeding (when invoked proactively)

Check the most recent user message in the conversation for the literal tag `<command-name>/feature-plan</command-name>` (or, equivalently, a leading `/feature-plan` typed by the user). If present, the user has explicitly opted in via the slash command — skip this step and continue with Step 1.

Also treat as opt-in (and skip this step) if you were just invoked as a chain from `/feature-design`'s Step 10 — i.e. the immediately previous turn was an `AskUserQuestion` result with header `"Run /feature-plan?"` and the user selected the option starting `"Yes, run /feature-plan"`. In that case the user has already confirmed; do not re-ask.

Otherwise (you arrived here because the model decided to invoke this skill proactively from natural-language intent, with no recent chained opt-in), call `AskUserQuestion` exactly once before any other work:

- **question**: `"Launch /feature-plan to produce a TDD-staged plan for <design version, e.g. v3>?"` — name the specific feature you'd plan against.
- **header**: `"Run /feature-plan?"`
- **options**:
  - `{ "label": "Yes, proceed", "description": "Run the skill and produce the implementation plan." }` (mark this as Recommended)
  - `{ "label": "No", "description": "Don't run; I'll redirect." }`

If the user picks "No" or "Other", stop the skill immediately and do not start Step 1. Do not write any files, do not ask further questions.

## Step 1 — Resolve the feature folder via `feature-resolve`

Parse `$ARGUMENTS` for an explicit version token only — `/feature-plan` does not take requirements text or a description (the description is authoritative from the feature folder; the requirements are authoritative from the design).

- Look for a leading `v<N>` or `version <N>` (case-insensitive; bare `1` does **not** count — only `v1` / `v 1` / `version 1`). If found, record as `explicit_version` and strip from the input. Integer only — no minor versions.
- If `$ARGUMENTS` contains other free-form text (e.g. the user typed feature requirements out of habit), note it for context but do not act on it. Plans don't redefine scope — the design does.

Invoke `feature-resolve` via the `Skill` tool with the argument string:

```
stage=plan[, version=<N>]
```

Include `version=` only if Step 1 captured an `explicit_version`. Do not pass `description=` — plan is always about an existing feature folder, and the resolver derives the description from that folder.

The resolver enforces all of this:

- Without a version arg, it picks the latest `features/feature-v<N>-<desc>/` folder that has a design file but no plan file (Rule C) — exactly the right target.
- If the latest folder already has a plan, the resolver asks the user whether to overwrite in place or target an older version. This is the only way to revise a plan under this plugin (revisions are deliberately dropped from the versioning scheme).
- If no design exists anywhere, the resolver errors and tells the user to run `/feature-design` first. Surface that error verbatim and stop.

Parse the resolver's output block. Record `mode`, `version`, `description`, `feature_folder`, `stage_file` (this is where Step 4 writes the plan), `prereq_file` (the design file you must read), and `tracker_file`. Use these verbatim downstream.

If the resolver stops with an error, pass the message to the user verbatim and stop. Do not retry with invented arguments.

## Step 2 — Read the design end-to-end

`Read` the design file at `prereq_file` (returned by the resolver). Build an internal map of:

- The numbered requirements in §3.
- The components / modules described in §5 (Architecture / components).
- The interfaces, data model, control flow, failure cases, security, performance, observability, compatibility, and testing sections in §5.
- The risks in §7 and the rollout plan in §9.

If §8 (Open questions) of the design is non-empty (anything other than "None — all decisions closed."), stop and tell the user the design still has open questions and must be closed before planning. Point at the specific items. Do not attempt to plan around them.

If a brainstorm file also lives in `feature_folder` (`feature-storm-v<N>-<description>.md`), `Read` it too — it captures the original product intent and any open questions §8 of the design should have addressed. Cross-check that the storm's intent is reflected in the design before planning.

## Step 3 — Ground the plan in the codebase

Use `Read`, `Grep`, and `Glob` to verify the design's assumptions about the existing codebase: do the files/functions/utilities cited in §4 and §5 actually exist? What is already in place vs. what needs to be built? Bound the exploration to what the plan touches.

Catalogue the project's test directory and naming conventions before drafting — for each new test file the plan will create, name an existing sibling that follows the same pattern (e.g. `<tests-root>/<area>/<existing-sibling-test-file>`). This avoids inventing test paths in Step 4 that you then have to rename in Step 6 once you notice they don't match the project's convention.

Also identify the project's primary test framework and runner (read package/build manifests, existing test files, and any CI config). Record the runner command the plan's "run the test" steps will use. If the project uses multiple frameworks for different layers, record which one applies to each area the plan touches.

For each **shared symbol the design changes** — a constructor or function signature, a widely-used class, a renamed config key — grep its construction/reference count across both source and tests to size the blast radius before staging. That count drives the staging decision (land the change atomically, defer it, or add a backward-compatible shim) and guards against plans that break the suite between stages or bundle an un-reviewably large mechanical edit.

The goal is (a) to produce concrete, executable steps in Step 4, and (b) to surface conflicts between the design and current reality that you will raise in Step 6.

## Step 4 — Draft the staged implementation plan

The plan is a sequence of **stages**. A stage is a unit of work that ends with a working, tested, mergeable increment — small enough that a reviewer can hold it in their head, large enough to be meaningful. Order stages so that each one builds on the last and leaves the system in a working state.

For every stage that introduces or changes behavior, the steps inside the stage **must follow the test-driven development cycle**:

1. **Write the test first** — concrete test cases for the behavior the stage will deliver. Cite the file path the test will live in.
2. **Run the test and confirm it fails** — record the expected failure mode so the test is proven to actually exercise the new behavior.
3. **Implement the code** — the minimum needed to make the test pass; cite the files/functions to add or modify.
4. **Run the test and confirm it passes** — and run the surrounding test suite to confirm no regressions.

Stages that are pure scaffolding (e.g. creating an empty module file, adding a dependency) may skip the test cycle if there is nothing to assert; mark these stages explicitly as **non-TDD scaffolding** with a one-line justification.

Write the plan to the `stage_file` path returned by Step 1. In **continue-existing** mode where the user authorised an overwrite, edit the existing file in place to match this shape — do not duplicate or branch sections.

```markdown
# <Feature Name> — Implementation Plan v<N>

**Status:** Draft
**Date:** <YYYY-MM-DD>
**Design:** [feature-design-v<N>-<description>.md](./feature-design-v<N>-<description>.md)

## Overview
One paragraph: what is being built, how the plan is staged, how the plan maps to the design.

## Development strategy — Test-Driven Development
Every behavior-changing stage in this plan follows the TDD cycle:

1. **Write the test first.** Add the test(s) that describe the new behavior.
2. **Run the test and confirm it fails.** Capture the failure to prove the test exercises the new behavior.
3. **Write the implementation.** The minimum code needed to satisfy the test.
4. **Run the test and confirm it passes.** Plus the surrounding suite, to catch regressions.

Stages that introduce no observable behavior (pure scaffolding) may skip this cycle and are labeled "non-TDD scaffolding" with a justification.

## Requirements coverage map
A table mapping every numbered requirement in §3 of the design to the stage(s) that deliver it.

| Design req | Delivered by stage(s) |
| --- | --- |
| R1: <one-line restatement> | Stage 2, Stage 4 |
| R2: ... | Stage 3 |
| ... | ... |

Every design requirement must appear in this table with at least one stage. If you cannot map a requirement, return to Step 3 and find the gap.

## Stages

### Stage 1 — <Short title>
**Goal:** <one sentence — what this stage delivers>
**Design references:** §<n>, §<n> of feature-design-v<N>-<description>.md
**Touches:** <files to create/modify, by path>

**Steps (TDD):**
1. Write test: `<path/to/test_file>` → `<test_name_or_id>` covering <behavior>. Expected initial failure: <one concrete failure mode in this project's test framework, e.g. a missing-symbol/module error, or an assertion that the not-yet-implemented function returns the wrong value>.
2. Run the test — confirm it fails with the expected error.
3. Implement: create/modify `<path>` to <concrete change>.
4. Run the test — confirm pass. Run the surrounding suite — confirm no regressions.

**Definition of done:** <bulleted, checkable>

**Risks specific to this stage:** <only if non-trivial; otherwise "None">

### Stage 2 — <Short title>
<same shape>

### Stage N — <Short title>
<same shape>

## Cross-cutting concerns
Concerns that don't fit cleanly into one stage but must be tracked:
- **Security** — input validation, authz, secret handling decisions taken from design §5 and how they appear across stages.
- **Performance** — limits, indexes, hot-path decisions from design §5.
- **Observability** — logs/metrics/traces added across stages.
- **Compatibility / migration** — how data and callers are handled across stages so the system stays working between merges.

## Verification
End-to-end verification once all stages are complete: how the user confirms the feature works against the acceptance criteria in design §3.

## Risks and open issues
Concrete risks specific to *implementation* (not design risks — those live in the design). Each with a mitigation.

## Deviations from the design
Either "None — plan matches design v<N> exactly." or a numbered list of deviations with rationale. Any deviation here is a signal that the design may need a follow-up version; flag the suggestion to the user in Step 9.
```

Compute `<YYYY-MM-DD>` from `date -u +%Y-%m-%d`. Use `v<N>` (integer) in the header — never `v<N>.<M>`.

## Step 5 — Ask clarifying questions only as needed

**This step is mandatory even in auto / non-interactive mode.** If the user or the harness has told you to "work without stopping", "skip clarifying questions", or otherwise run autonomously, that instruction does **not** override this step — when a planning-level decision is genuinely unresolved by the design, ask.

If, while drafting Step 4, you hit a planning-level decision that is **not** resolved by the design and that would meaningfully change the staging or the implementation steps, use `AskUserQuestion` (1–4 questions per call) to resolve it. Examples of planning-level questions:

- Order of stages when multiple valid orderings exist (e.g. ship the data migration first, or the API first?).
- Whether to land a feature flag in an early stage or skip it.
- Which existing test harness / framework to use when the design didn't specify.
- Concrete file paths when the design described shape but not location.

Do **not** re-litigate design decisions. If a question would change the design itself (scope, requirements, approach), stop and tell the user the design needs a new feature version via `/feature-design`. Do not silently expand scope in the plan.

When in doubt, prefer asking over guessing — but only if the answer changes the plan.

## Step 6 — Review the plan and update

Re-read the draft critically and fix what you find via `Edit` directly in the plan file. Run all of these checks:

- **Design coverage** — every numbered requirement in design §3 appears in the *Requirements coverage map* with at least one stage. Every component in design §5 *Architecture* has at least one stage that creates or modifies it. If anything is missing, add a stage or extend an existing one.
- **TDD discipline** — every behavior-changing stage has all four TDD steps in order; the "confirm fail" step records a concrete expected failure (not "it will fail"); every "non-TDD scaffolding" stage has a justification.
- **Inaccuracies** — every file, function, library, framework, or API cited *as already existing* must actually exist (verify the non-obvious ones with `Read`/`Grep`). For things the plan introduces, the cited path/name must be consistent across stages. Replace or remove anything invented.
- **Conflicts** — does any stage contradict another? Does any stage rely on something an earlier stage hasn't yet introduced? Does any stage break the system between merges? Fix the ordering or split the stage.
- **Conflicts with the design** — does the plan silently change a decision from the design? If so, either revert to the design or move it to *Deviations from the design* with rationale (and flag to the user in Step 9). Re-ordering or re-grouping implementation stages relative to the design's §9 rollout sequence is **not** a deviation — the plan owns staging order; only changes to scope, requirements, approach, or interfaces count.
- **Security issues** — does any stage introduce a regression in input validation, authz, secret handling, logging of sensitive data, or trust boundaries that the design protected? Does the *order* of stages create a window where the system is insecure (e.g. endpoint live before authz check is wired)? Fix by reordering, adding guard stages, or feature-flagging.
- **Hand-waves** — replace any "TBD", "TODO", "we'll just…", "should be straightforward" with concrete steps or move them to *Risks and open issues* with explicit mitigations.
- **Stage size** — no single stage should be so large that it can't be reviewed in one sitting. Split large stages. Conversely, do not fragment trivially small steps into their own stages.

After edits, do a final pass to confirm:

1. Every design requirement is in the coverage map and tied to a stage.
2. Every behavior-changing stage has the four TDD steps with a concrete "confirm fail" failure mode.
3. Stages are ordered so the system is working and shippable after each one.
4. *Deviations from the design* either says "None" or explicitly lists differences with rationale.

If any of these still fail, loop on Step 6 until they pass.

## Step 7 — Update the tracker

The tracker at `tracker_file` already exists from earlier stages. If it's somehow missing (resolver `notes` flagged `tracker_seed: skipped`), defensively copy the plugin template:

```bash
find ~ -path "*/dev-skills/templates/feature-tracker.html" 2>/dev/null
# cp the match (prefer ~/.claude/plugins/ if multiple) to <tracker_file>
```

If no template can be located, skip the tracker update and note it in Step 9 — do **not** fail the whole skill.

Apply these edits via the `Edit` tool. For each `{{TOKEN}}`, check it is still literal text in the file. Skip silently if already substituted.

**Header tokens** (only edit if still literal):

- `{{FEATURE_VERSION}}` → `<N>`.
- `{{FEATURE_TITLE}}` → `description` with hyphens replaced by spaces, preserving case.
- `{{FEATURE_SLUG}}` → `feature-v<N>-<description>`.
- `{{GENERATED_AT}}` → today's UTC date.

**Plan section tokens** (this skill owns these — always fill them with real content). Compute the timestamp once via `date -u +"%Y-%m-%d %H:%M UTC"` and reuse the same value for the chip. **If `/feature-storm` or `/feature-design` ran first, these are no longer the literal `{{PLAN_*}}` tokens — the earlier stage rendered them as the placeholder prose `Awaiting /feature-plan` (the chip) and two `<p class="empty">Not yet filled — pending /feature-plan.</p>` blocks (bullets + details). Overwrite those placeholder strings with the real plan content; the skip-if-substituted rule above protects only *other* skills' tokens, never your own Plan panel.**

- `{{PLAN_AT}}` → `Updated <YYYY-MM-DD HH:MM UTC>` (the timestamp chip text — no surrounding HTML).
- `{{PLAN_BULLETS}}` → an `<ul>` of 5–10 plan highlights, one `<li>` per bullet — typically the stage titles plus the *Deviations from the design* line.
- `{{PLAN_DETAILS}}` → free-form HTML rendering the plan in increasing detail, drawn from the file written in Step 4. Cover, in order: the **Overview** paragraph → the **Stages** list (one `<h3>` or `<h4>` per stage with its one-line goal and the files it touches; do not paste the full TDD step list — that's in the .md) → the **Requirements coverage map** as a `<table>` → **Cross-cutting concerns** → **Verification** → **Deviations from the design**. Use `<h3>` for top-level section titles, `<h4>` for sub-sections, `<p>` / `<ul>` / `<table>` for content. Order content from highest-level to most detailed so a reader can stop reading at any depth.

**Other tokens** — substitute with the empty placeholder *only if still literal* (most will already be content from earlier stages):

- `{{BRAINSTORMING_AT}}` → `Awaiting /feature-storm`
- `{{BRAINSTORMING_BULLETS}}` / `{{BRAINSTORMING_DETAILS}}` → `<p class="empty">Not yet filled — pending /feature-storm.</p>`
- `{{DESIGN_AT}}` → `Awaiting /feature-design` (should never happen — design must exist for plan to run; but defend regardless)
- `{{DESIGN_BULLETS}}` / `{{DESIGN_DETAILS}}` → `<p class="empty">Not yet filled — pending /feature-design.</p>` (same caveat)
- `{{IMPLEMENTATION_AT}}` → `Awaiting /feature-implement`
- `{{IMPLEMENTATION_BULLETS}}` → `<p class="empty">Not yet filled — pending /feature-implement.</p>`
- `{{IMPLEMENTATION_DETAILS}}` → `<p class="empty">Not yet filled — pending /feature-implement.</p>`

**Progress bar** (mandatory transition — only fired in this step, after the plan document is written and reviewed):

- old_string: `data-stage="plan" data-state="pending"`
- new_string: `data-stage="plan" data-state="complete"`

If the Edit fails, the plan step is already `complete` (backfill on a fully tracked feature) — leave it alone.

Do **not** touch other skills' tokens beyond the empty-placeholder fallback above. Do **not** touch other skills' progress steps.

## Step 8 — Capture lessons

Invoke the `lessons-capture` skill in this plugin via the `Skill` tool with the single argument `feature-plan`. It runs the reflection protocol, appends a dated entry to `~/.claude/dev-skills/lessons/feature-plan.md`, and returns the entry body for you to paste under the *Skill-improvement recommendations* heading in Step 9.

Do not run the reflection inline — `lessons-capture` is the single source of the protocol for all skills in this plugin.

## Step 9 — Present staged highlights

In chat, output a scannable summary so the user can see the shape of the plan without opening the file:

```
<Created | Revised>: <stage_file path>
**Against design:** <prereq_file path>
**Tracker:** <tracker_file path>

**Feature:** v<N> — <human-readable title>

**Stages**
1. <Stage 1 title> — <one-line goal>
2. <Stage 2 title> — <one-line goal>
...
N. <Stage N title> — <one-line goal>

**Development strategy:** test-first per stage (write test → confirm fail → implement → confirm pass).

**Design coverage:** <N>/<N> requirements mapped.

**Deviations from design:** <"None" or short list with one-line rationale each>

**Top risks**
- <1–3 implementation risks, each one line>

**Next step:** <e.g. "Begin Stage 1: <title>" — single concrete action>

**Skill-improvement recommendations**
- <single item from Step 8, or the line "No skill-improvement recommendations from this run.">
```

Keep the chat output under ~35 lines — if the plan has more than 8 stages, group the *Stages* list by phase so the cap still holds. The file is the artifact; the chat is the pointer. If you logged deviations from the design, explicitly suggest the user consider a new feature version via `/feature-design`.

## Step 10 — Offer to chain into /feature-implement

After presenting the staged highlights, give the user a one-click way to continue into implementation. Call `AskUserQuestion` exactly once:

- **question**: `"Continue with /feature-implement to build this plan stage-by-stage on the current branch?"`
- **header**: `"Run /feature-implement?"`
- **options**:
  - `{ "label": "Yes, run /feature-implement", "description": "Launch the implement skill against the plan just saved. It will write code and create one commit per green stage on the current branch." }`
  - `{ "label": "Not now", "description": "Stop here; the plan is saved." }`

**Which option is Recommended depends on the plan's *Deviations from the design* section:**
- If it says "None — plan matches design v<N> exactly." → mark **"Yes, run /feature-implement"** as Recommended.
- If it lists any deviation → mark **"Not now"** as Recommended instead, and append to its description: `"Consider running /feature-design first to fold the deviations back into the design (as a new feature version) before implementing."` The user can still pick "Yes" if they want to implement against the deviated plan as-is.

If the user picks "Yes, run /feature-implement", invoke the `feature-implement` skill via the `Skill` tool with the single argument `v<version>` (the integer feature version resolved in Step 1). The implement skill's Step 1 parses the version token and delegates to `feature-resolve`, which continues into the same feature folder — no conversation-context lookup involved.

If the user picks "Not now" or "Other", emit exactly one line before stopping:

```
**Next step:** when you're ready, run `/feature-implement v<version>`.
```

Do not skip this step or substitute the AskUserQuestion with prose. The offer is the affordance; rendering it as a question is what makes it one-click. Because `/feature-implement` writes code and commits, the "Not now" path is a perfectly reasonable choice — the user can review the plan first and run the chain later. The "Next step" hint is only emitted on decline.

## Constraints (non-negotiable)

- **No plan without a design.** The plan must reference an existing design under the resolver-returned feature folder. The resolver enforces this; never bypass it.
- **Output path comes from `feature-resolve` only.** Never write to `docs/`, never construct `features/...` paths by hand. Step 1 is the single source of pathing.
- **Integer versions only.** `v<N>` everywhere — no `v<N>.<M>`. The plan version matches the feature version; there is no separate plan minor-versioning.
- **The design's open questions must be empty.** If design §8 has any open question, stop. The plan cannot resolve design ambiguity — only `/feature-design` can.
- **TDD is non-optional for behavior-changing stages.** Pure scaffolding stages may skip it with a stated justification; everything else follows write → fail → code → pass.
- **No silent scope or decision changes.** Any divergence from the design lives in *Deviations from the design* with rationale, and is flagged to the user in Step 9.
- **Tracker edits are defensive.** Substitute only tokens still literal `{{...}}`; never overwrite content placed by `/feature-storm`, `/feature-design`, or any other skill. The progress bar's `data-stage="plan"` entry is this skill's alone to touch.
- **Lessons capture runs every time.** Step 8 always invokes `lessons-capture`; whether it produces a recommendation or "none this run" is decided by that skill.
- **No symlinks.** If a defensive tracker template copy is needed in Step 7, always copy — never link.
- **Never paste the entire plan into chat.** Step 9 is staged highlights only; the user opens the file for full content.
