---
name: feature-design
description: Produce a reviewed feature design document under features/feature-v<N>-<description>/. Use when the user asks for a feature design, spec, design doc, design review, or to spec/scope a feature — typically as a follow-up to /feature-storm, or starting cold for features that don't need brainstorming. Grounds the design in the existing codebase (and any legacy docs/), asks clarifying questions until all open decisions are closed, writes feature-design-v<N>-<description>.md via feature-resolve, self-reviews for functional/security/efficiency gaps, updates the per-feature tracker, and presents highlights. Step 0 confirms with the user via AskUserQuestion before doing any work when invoked proactively; the confirmation is skipped when the user explicitly typed /feature-design, just chained in from /feature-storm, or just chained in from /feature-dispatch.
user-invocable: true
disable-model-invocation: false
argument-hint: <free-form feature requirements (optionally including v<N>), or omit to be asked / picked up from a just-completed /feature-storm>
allowed-tools: Read, Grep, Glob, Write, Edit, AskUserQuestion, Skill, WebFetch, Bash(ls *), Bash(find *), Bash(mkdir -p *), Bash(test *), Bash(cp *), Bash(pwd), Bash(date *)
---

# feature-design — Reviewed Feature Design With Self-Review

You are running the `feature-design` skill. The user may have arrived here by typing `/feature-design` (with optional free-form requirements in `$ARGUMENTS`), by chaining in from `/feature-storm`, or because the model proactively invoked the skill. Your job is to produce a single, complete, decision-closed feature design document at the path returned by `/feature-resolve`, then present highlights to the user.

**Terminology (plugin-wide).** Two words are overloaded; keep them apart. A **step** is a numbered step of *this skill's own procedure* — the `## Step …` headings below (e.g. *Step 4*); the only other "steps" are the **TDD steps** inside a plan stage (write test → confirm fail → implement → confirm pass). A **stage** has two senses: a **chain stage** is one of `storm → design → plan → implement` (it shows up as `stage=…`, `stage_file`, and the tracker's `data-stage`), while a **plan stage** is a committable unit of work *inside* the implementation plan (e.g. `Stage 1`) — `/feature-plan` creates these and `/feature-implement` builds one per commit. A procedure step is never a plan stage, and a plan stage is never a procedure step.

This skill has eleven steps (Steps 0–10). Execute them in order. Do not skip Step 0 (proactive-invocation confirmation), Step 4 (clarification loop), Step 6 (self-review), Step 7 (tracker update), or Step 8 (lessons capture) — they are the load-bearing steps.

## Step 0 — Confirm before proceeding (when invoked proactively)

Check the most recent user message in the conversation for the literal tag `<command-name>/feature-design</command-name>` (or, equivalently, a leading `/feature-design` typed by the user). If present, the user has explicitly opted in via the slash command — skip this step and continue with Step 1.

Also treat as opt-in (and skip this step) if you were just invoked as a chain from `/feature-storm`'s Step 9 — i.e. the immediately previous turn was an `AskUserQuestion` result with header `"Run /feature-design?"` and the user selected the option starting `"Yes, run /feature-design"`. In that case the user has already confirmed; do not re-ask.

Also treat as opt-in (and skip this step) if you were just invoked as a chain from `/feature-dispatch` — i.e. the immediately previous turn was an `AskUserQuestion` result with header `"Route this feature?"` and the user selected an option whose label starts with `"Run /feature-design"`. In that case the user has already confirmed via the dispatcher; do not re-ask.

Also treat as opt-in (and skip this step) if the user's immediately preceding message explicitly affirmed an assistant proposal that named this skill — e.g. they answered "yes" to "Want me to run this through /feature-design?". A fresh confirmation right after that affirmation is friction, not safety.

Otherwise (you arrived here because the model decided to invoke this skill proactively from natural-language intent, with no recent chained opt-in), call `AskUserQuestion` exactly once before any other work:

- **question**: `"Launch /feature-design to produce a feature design for <your one-line restatement of what the user asked for>?"` — replace `<...>` with the specific scope you intend to design.
- **header**: `"Run /feature-design?"`
- **options**:
  - `{ "label": "Yes, proceed", "description": "Run the skill and produce the design document." }` (mark this as Recommended)
  - `{ "label": "No", "description": "Don't run; I'll redirect." }`

If the user picks "No" or "Other", stop the skill immediately and do not start Step 1. Do not write any files, do not ask further questions.

## Step 1 — Capture requirements

Parse `$ARGUMENTS`. Detect three pieces of input, any of which may be absent:

- **Explicit version token.** Look for a leading `v<N>` or `version <N>` (case-insensitive; bare `1` does **not** count — only `v1` / `v 1` / `version 1`). If found, record as `explicit_version`; strip from remaining text. Integer only — no minor versions under this plugin's scheme.
- **Candidate short title.** Look for an obvious short phrase (quoted, or a `title=<phrase>` slot, or unambiguously the leading 2–8 words). If found, record as `candidate_description`.
- **Free-form requirements text.** Everything else is the initial requirements statement.

Resolve the requirements statement, in this priority order:

1. If the parsed free-form text is meaningful (>~5 words), use it as the initial requirements statement.
2. Else, if the conversation context shows a **just-completed `/feature-storm`** (storm bullets visible in recent assistant messages, or a `features/feature-v<N>-<desc>/feature-storm-v<N>-<desc>.md` path visible in recent tool results), use the storm's approved bullets as the requirements basis. Capture the storm's resolved `description` as `candidate_description` if Step 1 didn't already produce one. State in chat which storm you picked up (e.g. `"Continuing from /feature-storm: features/feature-v3-add-reminders/feature-storm-v3-add-reminders.md."`) so the user can redirect with one word.
3. Else, if the recent conversation contains the requirements — a substantial design/requirements discussion, or an enumerated proposal the assistant just made that the arguments reference tersely (a number/range/ordinal like `1-4`, or "that" / "do it") — resolve the requirements from that context. State in chat which discussion or items you adopted (e.g. `"Designing items 1–4 of the remediation list above."`) so the user can redirect with one word.
4. Else, make exactly one `AskUserQuestion` call asking what feature the user wants designed. Their answer becomes the requirements statement.

Do not proceed past Step 1 without a real requirements statement.

## Step 2 — Resolve the feature folder via `feature-resolve`

Settle the description that goes into the folder name:

1. If `candidate_description` was captured in Step 1 *and* is ≤10 words *and* looks filename-safe, use it.
2. Otherwise, derive a candidate from the requirements (≤10 words, ideally 2–5; strip articles/filler, preserve meaning and proper-noun case).
3. Call `AskUserQuestion` **exactly once** to confirm:
   - **question**: `"Use this short title for the feature folder: \"<candidate>\"?"`
   - **header**: `"Feature title"`
   - **options**:
     - `{ "label": "Yes, use this", "description": "Continue with \"<candidate>\". Folder will be features/feature-v<N>-<hyphenated>/." }` (mark this as Recommended)
     - `{ "label": "Edit it", "description": "Give a different short title (≤10 words)." }`
   - If the user edits, re-validate ≤10 words; ask once more if they overshoot. Do not truncate silently.

   **Skip the confirmation entirely** if Step 1 picked up a just-completed `/feature-storm` (the storm already established this description with the user), or if the user supplied the title explicitly — a quoted phrase or a `title=`/`description=` slot — that is ≤10 words and filename-safe; re-confirming a title the user just typed is friction without value. Still confirm when the candidate was merely inferred from the leading words of the requirements.

Now invoke `feature-resolve` via the `Skill` tool with the argument string:

```
stage=design[, version=<N>][, description=<confirmed phrase>]
```

Include `version=` only if Step 1 captured an `explicit_version`. Include `description=` always (resolver ignores it when continuing into an existing folder, but pass it for the create-new path).

Parse the resolver's output block. Record these fields verbatim — every later step uses them, and you must not reconstruct paths by string concatenation:

- `mode` (`create-new` or `continue-existing`)
- `version` (integer `N`)
- `description` (authoritative hyphenated description; use this everywhere downstream even if your input differed)
- `feature_folder` (absolute path)
- `stage_file` (absolute path — this is where Step 5 writes)
- `tracker_file` (absolute path — Step 7 edits this)
- `notes` (surface to the user only if non-trivial — e.g. description conflict, tracker seed skipped)

If the resolver stops with an error, pass the message to the user verbatim and stop. Do not retry with invented arguments.

**`feature-resolve` runs inline in this turn — do not end your turn when its result block appears.** The `Skill` tool loads it into your own context rather than delegating to a subagent, so the block is a checkpoint in the middle of *your* run, not a hand-off that returns control anywhere. Once you've recorded the fields above, continue straight into Step 3 in the same turn. Stopping here strands the user with a seeded folder, an empty tracker, and no design.

## Step 3 — Ground the design in the codebase

**Do this before the first `AskUserQuestion` in Step 4.** Clarifying questions written without grounding are vague and force extra rounds; reading the modules the feature will most likely extend first makes the questions concrete and lets you offer specific options.

**Read the storm first, if one exists for this feature.** Check the resolver-returned `feature_folder` for a file named `feature-storm-v<version>-<description>.md`. If it exists, `Read` it now, before any codebase exploration — it captures the product intent (§1–§6) and, crucially, the open questions §7 that **Step 4's clarification loop must close**; the storm's §6 (Risks) also seeds this design's own risks section. If no storm exists, that's fine — the user chose to design cold; proceed without it. Do not warn or prompt; cold design is a supported path. This mirrors the convention `/feature-plan` and `/feature-implement` use to read sibling artefacts from the same feature folder.

Use `Read`, `Grep`, and `Glob` only to understand the parts of the project the feature interacts with — entry points, existing modules the feature must integrate with, data models it must extend, tests that establish current behavior. Cite findings by `path:line` when relevant.

**Legacy `docs/` is fair game for grounding.** If the repo has older `docs/<prefix>-v<X>.<Y>.md` files (the previous-generation design convention), read them for context — they capture prior decisions and architectural intent. Do **not** continue their version numbering and do **not** write into `docs/`; the new artefact lives under the resolved `feature_folder`. The `notes` field from the resolver will mention if you're in a repo that has legacy docs.

Two more grounding sources are load-bearing when they exist: (a) if the feature supersedes or remediates an area covered by an earlier feature, read the most recent prior `features/feature-v<M>-*` design for that area — it records the prior approach and decisions your §6 *Alternatives considered* should contrast; (b) if the requirements come from a multi-item review/spec document, also read its corrections / caveats / "deliberately not recommended" sections and reconcile the target item's stated mechanism against them and the actual code path before designing to it — review docs regularly contain a rationale that a later section (or the code) contradicts.

The goal is twofold: (a) ask better clarifying questions in Step 4, and (b) ensure the design references real, existing structures rather than invented ones. Do not embark on a wide codebase audit — bound the exploration to what the feature touches.

If the working directory is unfamiliar, a single top-level listing plus reading the obvious entry points (README, package manifests, main module) is usually sufficient before moving on.

If the feature integrates with a third-party platform (cloud provider, API, framework, library), also ground in that platform's official documentation. **Prefer docs-MCP servers first**, with `context7` as the default for library and framework documentation; use vendor-specific MCP servers (e.g. Microsoft Learn) for those vendors' surfaces. Fall back to `WebFetch` against the platform's official documentation URL **only when no MCP server covers the topic**. Invent nothing about the external surface.

## Step 4 — Clarify until all material decisions are closed

**This step is mandatory even in auto / non-interactive mode.** If the user or the harness has told you to "work without stopping", "skip clarifying questions", or otherwise run autonomously, that instruction does **not** apply here — closing material ambiguity before the design is written is the entire purpose of this skill. Ask the questions anyway; a design produced from guesses is worse than a brief pause.

Iteratively use `AskUserQuestion` (1–4 questions per call) to resolve every material ambiguity. Cover at minimum:

- **Scope** — what is explicitly in and out of scope for this feature.
- **Acceptance criteria** — what "done" concretely means; how the user verifies the feature works.
- **Approach choices** — when multiple viable paths exist, present them as options for the user to pick. When an option differs from the others on a **measurable dimension** (cost, latency, storage, memory, quota/request usage), compute that quantity from the Step 3 grounding and state it inside the option description rather than offering an abstract trade-off — quantified options close the decision in one round and ground your recommendation in numbers the user can verify.
- **Constraints** — performance, security, dependencies, deadlines, compatibility, platform.
- **Data and state** — what is stored, where, with what lifetime, with what migration path if any.
- **Failure behavior** — how the feature behaves on bad input, partial failure, network errors, race conditions.

If a `/feature-storm` ran first, its §7 (Open questions for design) is the seed list — explicitly close every item there. Do not skip them on the assumption that "the design will figure it out". An item is *closed* either by a user answer **or** by a grounded decision you record in §5/§6 with rationale; reserve `AskUserQuestion` for items with a genuine user-facing trade-off.

After each round, restate your working understanding internally and ask: *Is there any remaining decision that would meaningfully change the design if it went the other way?* If yes, ask another round. Stop only when the remaining uncertainty would not redirect the design.

Three rules keep the rounds efficient and honest:

- **Sequence by dependency.** When the design inherits a load-bearing premise that was flagged high-risk or uncertain (e.g. an external integration whose feasibility was in doubt), re-confirm that premise in the first question — detail questions that silently depend on it are wasted if the premise falls.
- **Verified claims only.** Before presenting options whose descriptions or previews assert a specific technical or behavioural outcome, validate the claim against the Step 3 grounding (or a throwaway prototype). Never put an unverified behavioural guarantee in an option.
- **Cross-check the answers.** After the loop ends, re-scan all collected answers for cross-answer contradictions (one answer forbidding what another requires); surface and resolve any before writing the design, and note the reconciliation in the doc.

Do not pad with questions for their own sake. Equally, do not stop early to avoid friction — under-clarification is the failure mode this skill exists to prevent. The final design must have **no points that require further decisions**.

## Step 5 — Write the design document

**Guiding principle:** the design must always prefer a **modular, separately testable** structure over a monolithic one. Decompose the feature into small components with clear single responsibilities and explicit interfaces. Each component should be unit-testable in isolation (no hidden global state, no implicit coupling, no requirement to spin up the whole feature to test one piece). When there is a viable modular approach, choose it over the monolithic one even if the modular approach takes more files. If a monolithic approach is genuinely warranted (e.g. the seam would be artificial and add no testability), record the rationale explicitly under §6 *Alternatives considered*.

Write the file at the `stage_file` path returned by Step 2. Use this structure exactly. Every section is required; if a section has no content for this feature, write a brief explicit "Not applicable — <reason>" rather than omitting it.

```markdown
# <Feature Name> — Design v<N>

**Status:** Draft
**Date:** <YYYY-MM-DD>
**Storm:** [feature-storm-v<N>-<description>.md](./feature-storm-v<N>-<description>.md)  ← include this line only if the storm file exists in the same feature folder; omit otherwise.

## 1. Summary
One paragraph: what the feature is, who it is for, what problem it solves.

## 2. Goals and non-goals
- **Goals:** bulleted, concrete outcomes.
- **Non-goals:** what this design explicitly does not address (and why, briefly).

## 3. Requirements
Numbered functional and non-functional requirements derived from Steps 1 and 4. Each requirement must be testable.

## 4. Background and context
Relevant existing code, modules, data models, prior designs. Cite by `path:line` where applicable. Note what currently exists and what is missing. If a brainstorm document exists at `features/feature-v<N>-<desc>/feature-storm-v<N>-<desc>.md`, reference it.

## 5. Design
The single recommended approach, in enough detail that a competent engineer can implement it without re-deriving decisions.

Sub-sections as needed:
- **Architecture / components** — what is added, modified, removed. Show the modular decomposition: each component's single responsibility, its public interface, and which other components it depends on. If the feature is implemented as one cohesive unit rather than several, explain why splitting would be artificial.
- **Data model** — schemas, migrations, storage, lifetimes.
- **Interfaces** — APIs, function signatures, message shapes, CLI flags, UI surfaces.
- **Control flow** — happy path step-by-step; key alternative flows.
- **Failure and edge cases** — concrete behavior for each.
- **Security** — authn/authz, input validation, secret handling, trust boundaries.
- **Performance** — expected load, hot paths, caching, indexes, limits.
- **Observability** — logs, metrics, traces; what is alertable.
- **Compatibility / migration** — backwards compat strategy; data migration steps.
- **Testing strategy** — unit, integration, end-to-end coverage; how acceptance criteria are verified. Each component identified in *Architecture / components* must have a corresponding unit-test plan that does not require the rest of the feature to be running.

## 6. Alternatives considered
Only include alternatives that were actively evaluated and rejected. For each: one sentence on the alternative and one sentence on why it was rejected. If none were actively evaluated, write "None — <reason>" rather than omitting the section.

## 7. Risks and issues
Concrete risks with likelihood/impact and mitigation. Include known issues with the current codebase that this design must work around.

## 8. Open questions
This section **must** be empty or contain only the literal text "None — all decisions closed." If you find yourself listing real open questions here, return to Step 4 and resolve them before saving.

## 9. Rollout plan
Phasing, feature flags, dark launches, rollback strategy, communication.
```

Compute `<YYYY-MM-DD>` from `date -u +%Y-%m-%d`. Use `v<N>` (integer) in the header — never `v<N>.<M>`.

## Step 6 — Self-review and fix

Re-read the draft critically through these lenses, and fix what you find via `Edit` directly in the design file. Do not produce a separate review document.

- **Functional correctness** — does every numbered requirement in §3 map to concrete design content in §5? Any requirement without a corresponding design element is a gap to fix.
- **Decision closure** — is §8 truly empty / "None"? Any hand-wave ("we'll just…", "should be straightforward…", "TBD", "TODO", "to be decided") must be replaced with a concrete decision or moved to §7 as an explicit accepted risk with rationale.
- **Security gaps** — injection (SQL/command/template/prompt), authn/authz holes, secret handling, input validation at trust boundaries, unsafe deserialization, SSRF, path traversal, crypto misuse, logging of secrets/PII. Fix or document with mitigation.
- **Inefficiencies** — blocking I/O on hot paths, unbounded scans / buffers / retries, cache misuse, redundant computation, premature abstraction, shotgun surgery; *for data-backed features also*: N+1 queries, missing indexes. Skip lenses that do not apply to the feature's domain — do not invent database concerns for features that touch no database. Fix or justify what remains.
- **Modularity and testability** — is the feature decomposed into small components with single responsibilities and explicit interfaces? Can each component be unit-tested in isolation without standing up the rest of the feature? Flag any "god module" / monolithic blob that mixes responsibilities, and split it (or record an explicit rationale in §6 if the split would be artificial). Modularity for its own sake is not the goal — testability and clear seams are.
- **Reference integrity** — every `path:line` citation, function name, library, or API named in the design must actually exist. Verify the non-obvious ones with `Read`/`Grep`. Remove or correct anything invented.
- **Grounded-behaviour integrity** — existence is not enough: verify the design's *claims about* existing code against the Step 3 grounding. For any function the design leans on for an error-handling or degradation path, read its failure contract (raises vs returns empty vs no-op) rather than assuming graceful degradation. Confirm the proposed flow honours the documented preconditions and ordering/state invariants of any function or data structure it reuses or sits adjacent to. Every field or distinction the design derives must be obtainable from the grounded interface/response shapes — never promise data the integrated system cannot provide. If the feature touches a path served by an existing incremental-redraw, diff, cache, or index optimization, state whether the design preserves or consciously replaces it (with the cost). And for any requirement that changes a constant, default, or config value, confirm the current value from the codebase and flag already-satisfied no-op changes explicitly.
- **Cross-section consistency** — for any scenario the design describes in more than one place (§5.4 + §5.5 + §5.9), trace it through ALL sections and check they agree on the same outcome. Contradictions between sections are the most common review failure.

Update §1–§9 in place. Do not append a "review notes" section — the design is the artifact, not the review.

After the edits, do a final read-through to confirm:

1. §8 is empty / "None — all decisions closed."
2. No "TBD", "TODO", "FIXME", or hand-wave language remains.
3. Every requirement is addressed.
4. Risks in §7 each have a mitigation.

If any of these still fail, loop on Step 6 until they pass. Do not proceed to Step 7 with an unresolved design.

## Step 7 — Update the tracker

The tracker file at `tracker_file` already exists (seeded by `feature-resolve` in Step 2, and you flipped its `design` step to `current` then). If the file is somehow missing (resolver `notes` flagged `tracker_seed: skipped`), defensively copy the plugin template:

```bash
find ~ -path "*/dev-skills/templates/feature-tracker.html" 2>/dev/null
# cp the match (prefer ~/.claude/plugins/ if multiple) to <tracker_file>
```

If no template can be located, skip the tracker update and note it in Step 9 — do **not** fail the whole skill.

First `Read` the tracker file once — `feature-resolve` seeded it via a shell copy, so the `Edit` tool has no read-state for it and every edit below would otherwise fail its first attempt. Then apply these edits via the `Edit` tool. For each `{{TOKEN}}`, check it is still literal text in the file (so you never overwrite content from `/feature-storm` or any other prior stage). If a token is already substituted, skip that edit silently. Note: the seeded tracker opens with an HTML documentation comment that lists every token name literally, so a bare `{{TOKEN}}` match is non-unique — scope each Edit to the rendered body occurrence (the chip span, bullets `<ul>`, details block, or `<h1>` title), never the comment-block token.

**Header tokens** (only edit if still literal):

- `{{FEATURE_VERSION}}` → `<N>` (integer).
- `{{FEATURE_TITLE}}` → human-readable title: take `description`, replace hyphens with spaces, then title-case each word while preserving any existing capitalization and upper-casing well-known acronyms (REST, API, CLI, HTTP, URL, SQL) (`Add-Reminders` → `Add Reminders`; `python-rest-server` → `Python REST Server`).
- `{{FEATURE_SLUG}}` → `feature-v<N>-<description>`.
- `{{GENERATED_AT}}` → today's UTC date (`YYYY-MM-DD`).

**Design section tokens** (this skill owns these — always fill them with real content). Compute the timestamp once via `date -u +"%Y-%m-%d %H:%M UTC"` and reuse the same value for the chip. **If `/feature-storm` ran first, these are no longer the literal `{{DESIGN_*}}` tokens — the storm rendered them as the placeholder prose `Awaiting /feature-design` (the chip) and two `<p class="empty">Not yet filled — pending /feature-design.</p>` blocks (bullets + details). Overwrite those placeholder strings with the real design content; the skip-if-substituted rule above protects only *other* skills' tokens, never your own Design panel.**

- `{{DESIGN_AT}}` → `Updated <YYYY-MM-DD HH:MM UTC>` (the timestamp chip text — no surrounding HTML).
- `{{DESIGN_BULLETS}}` → an `<ul>` of 5–10 design highlights, one `<li>` per bullet, plain text content (no markdown — convert any markdown to HTML).
- `{{DESIGN_DETAILS}}` → free-form HTML rendering the design in increasing detail, drawn from the design file written in Step 5. Cover §1 (Summary) → §2 (Goals & Non-goals) → §5 (Architecture / data / interfaces / failure / security / performance / testing — pick the sub-sections that matter most for this feature) → §7 (Risks) → §9 (Rollout). Use `<h3>` for top-level section titles, `<h4>` for sub-sections, `<p>` / `<ul>` / `<table>` for content. Order content from highest-level to most detailed so a reader can stop reading at any depth. Skip §6 if empty and skip §8 (it's always "None").

**Storm and future-stage placeholders** — substitute with the empty placeholder *only if still literal*. If `/feature-storm` ran, `{{BRAINSTORMING_*}}` will already be content and you skip them:

- `{{BRAINSTORMING_AT}}` → `Awaiting /feature-storm`
- `{{BRAINSTORMING_BULLETS}}` → `<p class="empty">Not yet filled — pending /feature-storm.</p>`
- `{{BRAINSTORMING_DETAILS}}` → `<p class="empty">Not yet filled — pending /feature-storm.</p>`
- `{{PLAN_AT}}` → `Awaiting /feature-plan`
- `{{PLAN_BULLETS}}` → `<p class="empty">Not yet filled — pending /feature-plan.</p>`
- `{{PLAN_DETAILS}}` → `<p class="empty">Not yet filled — pending /feature-plan.</p>`
- `{{IMPLEMENTATION_AT}}` → `Awaiting /feature-implement`
- `{{IMPLEMENTATION_BULLETS}}` → `<p class="empty">Not yet filled — pending /feature-implement.</p>`
- `{{IMPLEMENTATION_DETAILS}}` → `<p class="empty">Not yet filled — pending /feature-implement.</p>`

**Progress bar** (mandatory transition — only fired in this step, after the design document is written and self-reviewed):

- old_string: `<li class="step" data-stage="design" data-state="pending">`
- new_string: `<li class="step" data-stage="design" data-state="complete">`

Scope the match to the full stepper `<li>` opening tag as above — the bare `data-stage="design" data-state="pending"` attribute pair also appears in the template's documentation comment as its worked example, so the shorter old_string fails with two matches on every fresh tracker.

If the Edit fails because no `pending` match exists, the design step is already `complete` (backfill on a fully tracked feature) — leave it alone.

Do **not** touch other skills' tokens (storm content, plan, implementation) beyond the empty-placeholder fallback above. Do **not** touch other skills' progress steps.

## Step 8 — Capture lessons

Invoke the `lessons-capture` skill in this plugin via the `Skill` tool with the single argument `feature-design`. It runs the reflection protocol, appends a dated entry to `~/.claude/dev-skills/lessons/feature-design.md`, and returns the entry body (a single recommendation in three lines, or the "No skill-improvement recommendations from this run." line) for you to paste under the *Skill-improvement recommendations* heading in Step 9.

Do not run the reflection inline — `lessons-capture` is the single source of the protocol for all skills in this plugin.

## Step 9 — Present highlights

In chat, output a short, scannable summary so the user does not need to open the file to get the gist:

```
Saved: <stage_file path>
Tracker: <tracker_file path>

**Feature:** v<N> — <human-readable title>

**Highlights**
- <Approach in one bullet>
- <Key data/interface decision>
- <Key security or performance decision>
- <Any notable trade-off the user should know>

**Risks**
- <Top 1–3 risks from §7, each one line>

**Acceptance**
- <How the user will verify the feature works, one or two bullets>

**Skill-improvement recommendations**
- <single item from Step 8, or the line "No skill-improvement recommendations from this run.">
```

Keep the chat output under ~30 lines. The file is the artifact; the chat is the pointer.

## Step 10 — Offer to chain into /feature-plan

After presenting the highlights, give the user a one-click way to continue into the planning skill. Call `AskUserQuestion` exactly once:

- **question**: `"Continue with /feature-plan to produce a TDD-staged implementation plan for this design?"`
- **header**: `"Run /feature-plan?"`
- **options**:
  - `{ "label": "Yes, run /feature-plan", "description": "Launch the plan skill against the design just saved." }` (mark this as Recommended)
  - `{ "label": "Not now", "description": "Stop here; the design is saved." }`

If the user picks "Yes, run /feature-plan", invoke the `feature-plan` skill via the `Skill` tool with the single argument `v<version>` (the integer feature version resolved in Step 2). The plan skill's Step 1 parses the version token and delegates to `feature-resolve`, which continues into the same feature folder — no conversation-context lookup involved.

If the user picks "Not now" or "Other", emit exactly one line before stopping:

```
**Next step:** when you're ready, run `/feature-plan v<version>`.
```

Do not skip this step or substitute the AskUserQuestion with prose. The offer is the affordance; rendering it as a question is what makes it one-click. The "Next step" hint is only emitted on decline.

## Constraints (non-negotiable)

- **Output path comes from `feature-resolve` only.** Never write to `docs/`, never construct `features/...` paths by hand. Step 2 is the single source of pathing.
- **Integer versions only.** `v<N>` everywhere — no `v<N>.<M>` minor versions. No "next available version" math in this skill; the resolver decides.
- **No open decisions.** §8 must be empty or "None — all decisions closed." before Step 7 begins.
- **Self-review is mandatory.** Step 6 must run even if the draft looks clean — security and efficiency gaps are usually invisible on the first pass.
- **Tracker edits are defensive.** Substitute only tokens still literal `{{...}}`; never overwrite content placed by `/feature-storm` or any other skill. The progress bar's `data-stage="design"` entry is this skill's alone to touch.
- **`docs/` is read-only legacy.** Step 3 may read legacy designs for context but never writes there. The empty-placeholder pattern in `feature-resolve` + Step 7 ensures the tracker renders cleanly regardless of whether prior stages ran.
- **No symlinks.** If a defensive tracker template copy is needed in Step 7, always copy — never link.
- **Lessons capture runs every time.** Step 8 always invokes `lessons-capture`; whether it produces a recommendation or "none this run" is decided by that skill.
- **Never paste the entire design into chat.** Step 9 is highlights only; the user opens the file for full content.
