---
name: feature-implement
description: Execute a feature plan from features/feature-v<N>-<description>/ stage-by-stage on the current branch, following the plan's TDD cycle. Use when the user asks to implement, build, execute, or roll out a plan that already exists — typically as a follow-up to /feature-plan. Refuses to start without both the design and plan files on disk (delegated to feature-resolve). Syncs the repo's current branch with remote first, never creates a new branch, never pushes. Establishes a test baseline first; if any tests already fail, it stops and offers to investigate, file a bug, or halt rather than building on a red suite. Before the stage loop, asks the user to pick an execution strategy — direct in the main agent, one subagent per stage, or one subagent per three-stage chunk (all sequential, all committing one-per-stage). After each stage: checks coverage against the stage plan, self-reviews the code for bloat / duplication / orphaned-and-superseded code / functional issues / inefficiency / security, runs tests, and commits. At the end, runs a whole-project dead-code sweep (baseline-scoped, so it removes only orphans this feature stranded), updates the per-feature tracker, surfaces any improvements to this skill itself, and closes by offering to run the plugin's two eval skills (evals-code-run + evals-e2e-run) in parallel read-only subagents. Step 0 confirms with the user via AskUserQuestion before doing any work when invoked proactively; the confirmation is skipped when the user explicitly typed /feature-implement. Because this skill writes code and commits, the proactive-invocation confirmation is non-negotiable.
user-invocable: true
disable-model-invocation: false
argument-hint: <optional v<N> to target a specific feature, or omit to use the latest with a plan>
allowed-tools: Read, Grep, Glob, Write, Edit, AskUserQuestion, Skill, Agent, Bash
---

# feature-implement — Stage-By-Stage TDD Implementation Of A Plan

You are running the `feature-implement` skill. The user may have arrived here by typing `/feature-implement` (with an optional version in `$ARGUMENTS`), by chaining in from `/feature-plan`, or because the model proactively invoked the skill. Your job is to actually build the feature described in the plan at the path returned by `/feature-resolve`, one stage at a time, on the current branch, committing after each green stage.

**Terminology (plugin-wide).** Two words are overloaded; keep them apart. A **step** is a numbered step of *this skill's own procedure* — the `## Step …` headings below (e.g. *Step 4*); the only other "steps" are the **TDD steps** inside a plan stage (write test → confirm fail → implement → confirm pass). A **stage** has two senses: a **chain stage** is one of `storm → design → plan → implement` (it shows up as `stage=…`, `stage_file`, and the tracker's `data-stage`), while a **plan stage** is a committable unit of work *inside* the implementation plan (e.g. `Stage 1`) — `/feature-plan` creates these and `/feature-implement` builds one per commit. A procedure step is never a plan stage, and a plan stage is never a procedure step.

This skill has twelve steps (Steps 0–11). Execute them in order. Do not skip Step 0 (proactive-invocation confirmation), Step 2 (file readiness), Step 3 (repo readiness), Step 5 (strategy choice + TDD loop), Step 7 (final coverage & dead-code sweep), Step 8 (tracker update), or Step 9 (lessons capture) — they are the load-bearing steps.

## Step 0 — Confirm before proceeding (when invoked proactively)

This skill writes code and creates commits — proactive invocation without a clear opt-in is much higher cost than for `/feature-design` or `/feature-plan`. The Step 0 check is therefore strictly enforced.

Check the most recent user message in the conversation for the literal tag `<command-name>/feature-implement</command-name>` (or, equivalently, a leading `/feature-implement` typed by the user). If present, the user has explicitly opted in via the slash command — skip this step and continue with Step 1.

Also treat as opt-in (and skip this step) if you were just invoked as a chain from `/feature-plan`'s Step 11 — i.e. the immediately previous turn was an `AskUserQuestion` result with header `"Run /feature-implement?"` and the user selected the option starting `"Yes, run /feature-implement"`. In that case the user has already confirmed; do not re-ask.

Otherwise (you arrived here because the model decided to invoke this skill proactively from natural-language intent, with no recent chained opt-in), call `AskUserQuestion` exactly once before any other work:

- **question**: `"Launch /feature-implement to build the feature staged in <plan version, e.g. v3>? This will write code and create one commit per stage on the current branch."` — name the specific version you'd implement.
- **header**: `"Run /feature-implement?"`
- **options**:
  - `{ "label": "Yes, proceed", "description": "Run the skill stage-by-stage on the current branch, committing each green stage." }` (mark this as Recommended)
  - `{ "label": "No", "description": "Don't run; I'll redirect." }`

If the user picks "No" or "Other", stop immediately. Do not write any files, run any tests, or create any commits.

## Step 1 — Resolve the feature folder via `feature-resolve`

Parse `$ARGUMENTS` for an explicit version token only — `/feature-implement` does not take requirements text or a description.

- Look for a leading `v<N>` or `version <N>` (case-insensitive; bare `1` does **not** count — only `v1` / `v 1` / `version 1`). If found, record as `explicit_version` and strip from the input. Integer only.
- Free-form text other than the version is ignored.

Invoke `feature-resolve` via the `Skill` tool with the argument string:

```
stage=implement[, version=<N>]
```

Include `version=` only if Step 1 captured an `explicit_version`. Do not pass `description=` — the description is authoritative from the feature folder.

The resolver enforces all of the following:

- Without a version arg, it picks the latest `features/feature-v<N>-<desc>/` folder that has a plan file but no implement file (Rule C) — exactly the right target.
- If the latest folder already has an implement file, the resolver asks the user whether to overwrite or target an older version.
- If no plan exists anywhere, the resolver errors and tells the user to run `/feature-plan` first. Surface that error verbatim and stop.

Parse the resolver's output block. Record `mode`, `version`, `description`, `feature_folder`, `stage_file` (the implement-output path, if you later need to emit one — currently unused; this skill creates commits rather than a single .md), `prereq_file` (the **plan** file), and `tracker_file`. Use these verbatim downstream.

If the resolver stops with an error, pass the message to the user verbatim and stop. Do not retry with invented arguments.

## Step 2 — Read the plan, read the design, sanity-check both

The resolver returned `prereq_file` = the plan. Construct the design path from `feature_folder` + `version` + `description`:

```
<feature_folder>/feature-design-v<version>-<description>.md
```

Verify the design file exists with `ls` / `test -f`. If it does not (the resolver should have refused this case, but defend), stop with a one-line error naming the missing path.

`Read` both files in full now. Build an internal model:

- From the design: requirements (§3), components (§5), security/performance/observability decisions (§5), risks (§7), rollout (§9).
- From the plan: every stage with its TDD steps, files touched, definition of done, and the Requirements coverage map.

If plan §*Deviations from the design* is non-empty and unresolved, surface it to the user via `AskUserQuestion` and ask whether to proceed as-is or pause for a design refresh (a new feature version via `/feature-design`). Do not silently override.

If a brainstorm file also lives in `feature_folder` (`feature-storm-v<version>-<description>.md`), you may `Read` it for context, but the plan is the binding contract — do not let the storm override the plan.

## Step 3 — Repo readiness

The skill works **on the current branch** and **never creates a new branch** or pushes.

Run these checks in order:

1. `git rev-parse --is-inside-work-tree` — confirm we are inside a git repo. If not, stop and tell the user.
2. Identify the repo's default branch (in priority order: the remote HEAD via `git symbolic-ref refs/remotes/origin/HEAD`, falling back to `main`, then `master`). Call this `<default>`.
3. `git status --short` — check for uncommitted changes.
   - **First, distinguish the chain's own churn from the user's work.** If the only uncommitted changes are this feature's own artifacts (`features/feature-v<version>-*` — the design/plan/tracker files left by the preceding chain stage) and/or files that are gitignored-but-tracked, this is the chain's own output, not the user's unrelated work: offer to commit the feature docs as a `docs(...)` commit (ignoring the gitignored churn) and proceed, rather than treating it as a generic dirty-tree stop. This is near-guaranteed on chained `plan → implement` runs.
   - Otherwise, if the working tree is dirty, **stop**. Show the user what's modified and ask whether to commit/stash/discard before proceeding. Do not touch their changes.
4. `git rev-parse --abbrev-ref HEAD` — get the current branch.
   - If the current branch is **not** `<default>`, warn the user (e.g. "You're on `feature/x`, not `<default>`. This skill normally implements on `<default>`. Continue on the current branch?") and proceed only if confirmed. Do **not** switch branches yourself. Do **not** create a new branch.
5. `git fetch --prune` — refresh remote refs.
6. Compare local against `origin/<current branch>` (use the current branch you're on, since you may have confirmed staying on a non-default branch). Cases:
   - **Up to date** → continue.
   - **Behind** → `git pull --ff-only`. If a fast-forward is not possible, stop and ask the user to reconcile.
   - **Ahead** → continue (your local has unpushed commits; that's fine — this skill never pushes).
   - **Diverged** → stop and ask the user to reconcile. Never resolve a divergence automatically.
   - **No remote configured for this branch** → continue and note in the final summary.

Only proceed past Step 3 when the working tree is clean and the branch is either up to date or only ahead.

7. **Detect the project's tooling commands.** Before running anything, identify how this project runs **tests, lint, format-check, type-check**, and (where relevant) **build** and **dead-code analysis**. Inspect in this order:
   - Project manifests: `pyproject.toml`, `package.json` (scripts), `Package.swift` + any `*.xcodeproj`/`xcodebuild` wrappers, `Cargo.toml`, `go.mod`, `pom.xml`/`build.gradle(.kts)`, `Gemfile`, `mix.exs`, `composer.json`, `*.csproj`, etc.
   - Repo-level entrypoints: `Makefile`, `Taskfile.yml`, `justfile`, `fastlane/Fastfile`, `scripts/*` — often the canonical wrapper around raw tooling.
   - CI config: `.github/workflows/*.yml`, `.gitlab-ci.yml`, `.circleci/config.yml`, `azure-pipelines.yml`, `bitrise.yml`. CI shows the commands the maintainers treat as canonical.
   - Docs: `README.md`, `CONTRIBUTING.md`, anything under `docs/` (legacy reference material).

   Record the resolved commands as named slots — `TEST`, `LINT`, `FORMAT_CHECK`, `TYPE_CHECK`, `BUILD` (optional), and `DEADCODE` (optional — a whole-program unused-code analyzer). Reuse them by name through sub-point 8, Step 5e, Step 5h, and Step 7 so command choice stays consistent across stages. Reference examples (adapt to what the project actually uses):
   - **Python (uv):** `TEST="uv run pytest -q"`, `LINT="uv run ruff check ."`, `FORMAT_CHECK="uv run ruff format --check ."`, `TYPE_CHECK="uv run mypy"`, `DEADCODE="uv run vulture src tests"`. `ruff` (LINT) already flags unused imports/locals; `vulture` adds unreachable functions/classes — raise `--min-confidence` or feed a generated whitelist (`vulture … --make-whitelist > whitelist.py`, then pass `whitelist.py`) to suppress dynamic-dispatch false positives. Swap `uv run` for `poetry run` / `hatch run` if those are configured instead.
   - **Swift (SwiftPM):** `TEST="swift test"`, `LINT="swiftlint"`, `FORMAT_CHECK="swift-format lint -r Sources Tests"`, `BUILD="swift build"`, `DEADCODE="periphery scan"` (auto-detects SPM; add `--skip-build` to reuse an existing build, and use `--write-baseline`/`--baseline` for the Step 3 baseline). Suppress known false positives with `// periphery:ignore` comments.
   - **Swift (Xcode):** `TEST="xcodebuild test -scheme <S> -destination <D>"`, `BUILD="xcodebuild -scheme <S> build"`, `DEADCODE="periphery scan --project <P>.xcodeproj --schemes <S>"`; prefer the project's fastlane lane or `Makefile` wrapper if present.
   - **JS/TS:** `TEST="pnpm test --silent"` (or `npm`/`yarn` equivalent), `LINT="pnpm lint"`, `FORMAT_CHECK="pnpm format --check"` or `prettier --check`, `TYPE_CHECK="pnpm tsc --noEmit"`.
   - **Go:** `TEST="go test ./..."`, `LINT="golangci-lint run"`, `FORMAT_CHECK="gofmt -l ."` (any output = unformatted), `TYPE_CHECK="go vet ./..."`.
   - **Rust:** `TEST="cargo test --quiet"`, `LINT="cargo clippy --all-targets -- -D warnings"`, `FORMAT_CHECK="cargo fmt --check"`; type-check is implicit in `cargo check`.
   - **Java/Kotlin (Gradle):** `TEST="./gradlew test"`, `LINT="./gradlew check"`, `BUILD="./gradlew build"`. Maven: `TEST="mvn -q test"`, `BUILD="mvn -q package"`.
   - **`DEADCODE` in other ecosystems:** JS/TS → `knip` or `ts-prune`; Go → `deadcode ./...` or `staticcheck`; Rust → the compiler's built-in `dead_code` lint (`cargo build` warnings, or `-D dead_code`). Where a language has no dedicated analyzer, leave `DEADCODE` unset rather than improvising — Step 7 recommends one.

   If a slot has no configured tooling for this project, set it to `none — no baseline` and skip the corresponding action everywhere downstream. (For `DEADCODE`, that means no baseline and no Step 7 sweep — but Step 7 still emits a one-line recommendation to adopt a suitable analyzer.)

8. **Baseline the test failures and lint/type state.** Using the commands recorded in sub-point 7, run `TEST` once and record the names of any tests that already fail on the unmodified working tree. Then run `LINT`, `FORMAT_CHECK`, and `TYPE_CHECK` once and record any pre-existing failures, with the offending files/rules, not just a pass/fail verdict. If `DEADCODE` is set, also run it once and record the pre-existing dead-code findings — prefer the tool's native baseline where it has one (`periphery scan --write-baseline baseline.json`, or vulture's `vulture … --make-whitelist > whitelist.py`) so Step 7's comparison is exact. Save these lists for use in Step 5e, Step 7, and Step 10. Any slot recorded as `none — no baseline` in sub-point 7 is skipped. Like the lint/type baseline, the dead-code list is an *exclusion set*, not a gate — it never blocks the run; it only marks pre-existing dead code that Step 7's sweep must leave alone. The recorded **test**-failure list also drives the pre-implementation gate in sub-point 9: a non-empty test baseline halts the skill (the user decides what to do) rather than being silently carried into the stage loop. The lint/type list, by contrast, is the set of pre-existing problems excluded from regression gating (it does not block — see the next paragraph).

   Step 5e's regression check compares post-stage test failures against the test baseline rather than against zero; any failure already in the baseline is not a stage-introduced regression. The lint/type baseline serves the same purpose: a lint or type error already present on the unmodified tree (commonly in generated/stamped files such as Python's `version.py`, Swift's `BuildInfo.swift`, or a JS `_version.ts`) is not a regression — only ones newly introduced by this implementation are. If a stage's changes clear a *baseline* test or lint failure, that's fine — drop it from the baseline silently. The lists only grow shorter, never longer.

9. **Pre-implementation test gate — never build on a red baseline.** If sub-point 8's `TEST` baseline recorded **any** failing or erroring tests, **do not continue to implementation.** A test suite that is already red before a single line of feature code means the ground is unstable, and Step 5e's regression machinery cannot reliably separate a newly introduced break from the existing mess. Stop here and call `AskUserQuestion` exactly once:

   - **question**: `"<count> test(s) already fail on the unmodified tree, before any implementation: <short list of failing test ids>. I won't build on a red baseline. How do you want to proceed?"`
   - **header**: `"Tests already failing"`
   - **options**:
     - `{ "label": "Investigate now", "description": "Pause and diagnose why these tests fail before deciding — usually the right first move." }` (mark this as Recommended)
     - `{ "label": "File a bug", "description": "Hand off to /bug-submit to file the failing tests as a bug, then stop without implementing." }`
     - `{ "label": "Stop", "description": "Halt /feature-implement now and leave the repo untouched." }`

   Act on the choice:
   - **Investigate now** → do not enter the stage loop. Read the failing tests and the code they exercise and establish the root cause *with* the user (do not guess). Then, together: if the failures get resolved, re-run `TEST`; once the baseline is clean, resume from sub-point 8 and continue Step 3 normally. If the failures turn out to be real and out of scope for this feature, fall back to **File a bug** or **Stop** — never silently proceed on red.
   - **File a bug** → invoke the `bug-submit` skill via the `Skill` tool, passing a one-line description that names the failing tests and the `TEST` command as the argument. When it returns, **stop** `/feature-implement` without implementing, and tell the user to re-run it once the bug is fixed.
   - **Stop** (or "Other" with stop-like intent) → stop immediately. Make no edits and no commits; leave the repo untouched.

   **This gate fires even under an autonomous / "work without stopping" instruction** — like the Step 0 and Step 6 gates, a red baseline is a material condition that such instructions do not licence you to ignore. In a genuinely headless run with no channel to ask, default to **Stop** and report the failing baseline tests rather than building on them.

## Step 4 — Determine the starting stage

A run may be a fresh start or a resume. Detect prior stage commits for this feature version using the commit-message format from Step 5h. Anchor the grep on the closing paren so `v3` does not match `v30`:

```
git log --grep="(plan v<version>):" --oneline
```

Where `<version>` is the integer feature version returned by the resolver. Match each line against the format `<type>(plan v<version>): Stage N — <stage title>` to extract `N`.

Resolve the starting stage:

- If no prior stage commits exist for this version → start at **Stage 1**.
- If prior stage commits exist → identify the highest completed stage `K`. Default to resuming at **Stage K+1**. Briefly tell the user ("Detected Stage 1–K already committed; resuming at Stage K+1.") and proceed without asking, unless the detection is ambiguous (e.g. non-contiguous stage numbers, mixed commit-message formats), in which case ask via `AskUserQuestion`.
- If all stages appear already committed → tell the user the plan looks fully implemented; do not re-run stages. Skip to Step 7 (final coverage check) and then to Steps 8–10, but make no new commits.

## Step 5 — Choose a strategy, then implement each stage (TDD loop)

The remaining stages (from the starting stage determined in Step 4 to the last) are implemented **in order, never in parallel** — commits are the resume contract, and concurrent writers would race the working tree and the index. Treat each stage as atomic: it either completes green and gets committed, or it is left uncommitted and the user is consulted.

### Choosing the execution strategy

**Do this before any stage work — do not skip it.** Decide *who* drives the per-stage TDD cycle (the `5a`–`5i` cycle below). Let `R` = the number of stages still to implement (last − starting + 1).

- This is a **required choice, not a clarification you may assume away** — treat it like Step 0's gate. **Ask whenever you can prompt the user**: arriving via the slash command, chaining in from `/feature-plan`, and running under a general "work autonomously / don't stop to ask" instruction all still require this question. Heads-down execution is **not** licence to silently pick Direct.
- Skip the question — and default to **Direct**, saying so in one line — only when **(a)** `R ≤ 1` (there is nothing to choose), or **(b)** there is genuinely no interactive channel to answer on (a true headless / scheduled run, not merely an autonomous-feeling one).
- Otherwise call `AskUserQuestion` exactly once:
  - **question**: `"How should I execute the <R> remaining stages? All three run the same TDD cycle and commit one-per-stage on the current branch, in order — the only difference is who drives each stage."`
  - **header**: `"Execution strategy"`
  - **options**:
    - `{ "label": "Direct", "description": "Implement every stage in this conversation. Simplest, full visibility, uses the most context." }` (mark this as Recommended)
    - `{ "label": "Subagent per stage", "description": "Launch one general-purpose subagent per stage, in order. Keeps this conversation's context lean; each stage is isolated." }`
    - `{ "label": "Subagent per 3-stage chunk", "description": "Launch one subagent per consecutive group of three stages, in order. Fewer launches than per-stage, still context-isolated." }`

  If the user picks "Other", interpret their intent or fall back to **Direct**. Record the choice as `STRATEGY ∈ {direct, per-stage, per-chunk}`.

**Direct** — run the `5a`–`5i` cycle yourself for each stage in order, exactly as written below. (This is the historical behaviour of the skill.)

**Subagent modes (`per-stage`, `per-chunk`)** — partition the remaining stages into units: one stage per unit for `per-stage`, or consecutive groups of three for `per-chunk` (the last group may be shorter). Before partitioning, pre-scan the stages and pull out of subagent units any stage a subagent cannot complete: stages whose verification is inherently manual/integration (e.g. a live UI or browser check), stages needing a skill or context available only in this conversation, and stages that provision a new environment over the network (dependency installs — a sandboxed subagent typically has no network access). Run those stages in the main agent at their ordinal position, and say so when recording the strategy. Then, **for each unit in order**:

1. Launch a subagent with the `Agent` tool (called `Task` in some Claude Code versions) — `subagent_type: general-purpose`, **default isolation, not a worktree** (it must commit on the *current* branch in the shared working tree). Brief it with the **subagent contract** below. Launch one unit at a time and wait — never launch the next unit before this one returns.
2. When it returns, verify in the main agent — treat the subagent's report as a claim to check, not a result to trust:
   - `git log --grep="(plan v<version>):" --oneline` — confirm a commit exists for every stage the unit was meant to deliver, and `git status` shows a clean tree.
   - `git show --stat` each new stage commit — confirm it touched only that stage's expected files (catches stray files swept in, and inaccurate self-reports).
   - Re-run `TEST` (and `BUILD`, when set and the unit touched non-test code) yourself — the command's exit status is the sole pass/fail authority; never accept the unit's green claim, editor/indexer diagnostics, or the presence/absence of console output in its place.
   - Scan the unit's touched files for newly introduced compiler/linter diagnostics and reconcile them against that authoritative `TEST`/`BUILD` result: fix real ones in a follow-up commit before the next unit launches; treat isolated-analysis false positives (e.g. unresolved same-module or test-framework symbols outside the real build graph) as non-blocking.
3. If any expected stage commit is missing, or the subagent reported a Step 6 stop condition or a deviation, **do not launch the next unit** — surface the subagent's report to the user and decide together (same handling as Step 6). Step 4's resume logic lets you continue later from the last committed stage.
4. If the unit's subagent times out, crashes on an infrastructure error, or returns no report, do not assume wholesale failure and do not re-run the unit. Reconcile from the main agent: `git log --grep` to identify which of the unit's stages already committed; inspect the working tree for a complete-but-uncommitted stage and, if it verifies green (run `TEST`), commit it from the main agent with the standard message format; then resume only the remaining stages — a fresh subagent with an updated carry-forward note, or directly for a small trailing stage. Never re-run an already-committed stage.
5. Otherwise continue to the next unit.

Whoever executes, the `5a`–`5i` cycle is identical — nothing about TDD, self-review, coverage, commit format, or the git constraints changes; only the executor does. The final coverage & dead-code sweep (Step 7), tracker update (Step 8), lessons capture (Step 9), summary (Step 10), and eval offer (Step 11) **always run in the main agent** after every unit completes, never inside a subagent (the evals a user accepts in Step 11 are themselves delegated to subagents, but the offer and the launch are the main agent's).

#### Subagent contract (per-stage and per-chunk modes)

A subagent starts with a fresh context and cannot see this conversation, so its briefing must be self-contained. Pass, as the prompt:

- **Scope** — "Implement **only** stage `<N>` [through `<M>`] of the plan, test-first; do not touch any other stage."
- **Files** — absolute paths to the plan file (`prereq_file`) and the design file; tell it to `Read` both and re-read the target stage block before coding.
- **Tooling** — the resolved `TEST` / `LINT` / `FORMAT_CHECK` / `TYPE_CHECK` / `BUILD` commands from Step 3 verbatim (or "none" where unset).
- **Baseline** — the Step 3 lists of pre-existing test and lint/type failures, so it gates regressions against the baseline, not against zero.
- **Prior-stage state** *(units after the first only)* — a short carry-forward note: the stages already completed, the public interface (modules/types/functions and their signatures) of anything earlier units built that this unit will build on, any resolved interpreter / dependency / toolchain pins, and any deviations recorded so far. This keeps later units reusing prior work instead of re-scaffolding or guessing existing APIs.
- **Discipline** — the full `5a`–`5i` cycle: the pre-flight scans, write test → confirm fail → implement → confirm pass, coverage check against the stage plan, self-review (bloat / duplication-reuse / supersession-orphans / functional / inefficiency / security / style), final `TEST`, and **one commit per stage** with the exact message `<type>(plan v<version>): Stage <N> — <stage title>`. It must `git add` only the files the stage touched. Stage commits contain the stage's source and test files only; plan-deviation notes and repo-mandated side artifacts (changelog, wiki) go in a separate `docs:` commit whose subject omits `(plan v<version>):`.
- **Git constraints** — current branch only; never create or switch branches, never push, never `--amend` / `--no-verify` / force. Commit each stage before starting the next.
- **Stop conditions** — the Step 6 conditions: on an undiagnosable failure, a decision not covered by the plan/design, an externally-dirtied tree, or an unplanned large security issue, it must **stop**, leave completed stages committed and partial work uncommitted, and report rather than invent.
- **Verification honesty** — if part of a stage's definition of done requires verification the subagent cannot perform (live UI, external system, manual check), it runs every available automated check, does **not** claim the live verification, and returns an exact live-verification checklist for the main agent to run (Step 7 picks it up).
- **Return format** — a compact report: per stage, the title, commit short-sha, test result, the exact files committed, and an **API introduced** list (new public symbols — types, functions, constants — with signatures) for the main agent to paste verbatim into the next unit's carry-forward note; plus any deviations (and whether it updated the plan's *Deviations from plan*), any stop condition hit, and the final clean/dirty tree state.

Treat a unit as atomic the way a single stage is: it either lands all its stage commits green, or it stops and the user is consulted.

For every stage (whoever is executing it):

### 5a. Re-read the stage details
Re-read the stage block in the plan file (do not rely on memory). Note: goal, design references, files to touch, the four TDD steps, definition of done, stage-specific risks.

If the plan flagged the stage as **non-TDD scaffolding**, skip the test cycle for *that* stage — do the scaffolding work (5d), then jump to 5e. Everything else uses the full cycle below.

**Pre-flight testability** — for any stage whose test imports a module that does I/O (network, filesystem, OS-level streams) in its constructor, confirm the module exposes a dependency-injection seam before writing the test; if not, treat adding the seam as the first sub-step rather than discovering it via test failure.

**Pre-flight type identity** — for stages introducing new exception/error types (or other types compared by identity via `isinstance`, `instanceof`, equality on the class itself, `pytest.raises(MyError)`, `XCTAssertThrowsError(MyError)`, `expect().toThrow(MyError)`, etc.), confirm the test imports the type from the *same* module/binding the production code raises from. Some loaders produce two distinct identities for the same source declaration — e.g. Python's `spec_from_file_location` loading `plugin.py` as `mcp_bridge_plugin` while tests do `from mcp_bridge.plugin import MyError`; JVM classloaders treating a class loaded twice as two distinct types; Swift where the same type vended from two frameworks isn't equal at runtime; Node duplicating a package via symlinked/duplicated `node_modules`. Assertions against one identity won't match objects produced against the other. `grep` for dynamic-load patterns (`spec_from_file_location`, `Class.forName`, `dlopen`, duplicated `node_modules`) in test fixtures and verify the test's import path matches the production code's.

**Pre-flight signature-change scan** — when a stage changes a public constructor or function signature (adds a required kwarg, renames a parameter, changes the return type in a breaking way), `grep` across the codebase for every caller / instantiator of that symbol before writing the first test. List them in the stage's notes as "tests likely to need updating in this stage" so the inner-stage TDD slice can plan for them, rather than discovering them only at 5e's wider-suite regression check. Targeted-test green ≠ system green when constructor signatures move.

**Pre-flight time-dependency scan** — when a stage introduces current-time-based logic (clock reads, "now"-relative filtering, time-window cutoffs, TTL/expiry), `grep` existing tests for hardcoded or fixed-date fixtures that the new time logic would retroactively filter out or expire, before writing the first test. Plan to inject and pin the clock through a shared test seam within this same stage, rather than discovering the dated-fixture breakage only at 5e's wider-suite regression check.

**Pre-flight reuse scan** — before writing any new helper, parse/validate/resolve block, or test fixture, `grep` the target module, its sibling entry-point files (parallel handlers over the same domain), and the test tree for an existing equivalent; prefer calling or generalising it (add a parameter, loop over the kinds) over writing a parallel copy. When the stage adds a new variant of an existing family (an Nth sibling method, row factory, or per-variant test file), read the siblings first — three or more repeating the same boilerplate means the stage extracts the shared helper rather than pasting another copy.

### 5b. Write the test first
Create or modify the test file(s) specified by the stage. Write concrete test cases that describe the new behavior. Do **not** write any production code yet.

### 5c. Run the test and confirm it fails
Run the targeted test (preferred) or the surrounding test command. Capture the actual failure output and verify it matches (or is plausibly the same as) the "expected initial failure" the plan recorded. If the test **passes** at this point, something is wrong — either the test isn't exercising the new behavior, or the behavior already exists. Stop and resolve before continuing.

### 5d. Implement the code
Make the minimum changes needed to satisfy the test. Modify only the files the stage names (or files whose change is a direct, necessary consequence). If the stage's planned files turn out to be wrong, update the plan via `Edit` to reflect reality before continuing — and note the change in *Deviations from plan* (add a section to the plan file if needed). Don't silently drift.

### 5e. Run the test and confirm it passes
Re-run the targeted test, then run a wider relevant test suite (e.g. the module's tests, then the project's full unit suite if it's fast). The targeted test must pass. For the wider suite, **compare failures against the Step 3 baseline**: any failure already in the baseline is pre-existing and not a stage regression; any *new* failure not in the baseline must be fixed before continuing. Do not commit a state with new (non-baseline) failures. If a stage's changes cause a baseline test to start passing, drop it from the baseline list (the list only shrinks).

### 5f. Coverage check against the stage plan
Re-read the stage in the plan and verify, point-by-point, that what you implemented covers what the stage promised:

- Every file the stage said it would touch was either touched or had its omission justified.
- Every behavior the stage said it would deliver has at least one passing test.
- The stage's *Definition of done* checklist is satisfied.
- The Requirements coverage map's design requirements assigned to this stage are now actually exercised by tests.

If gaps appear, fill them within the same stage (go back to 5b). Do not paper over with TODOs.

### 5g. Self-review the new code
Before committing, review the change this stage introduced. Run all of these lenses; fix what you find via `Edit` in the same stage. Every lens but **Duplication / reuse** and **Supersession / orphans** looks only at the new diff — those two deliberately reach outside it: one at existing code the change should have called, the other at code the stage may have stranded:

- **Bloat** — code that wasn't required by the test or the stage goal. Speculative abstractions, premature factories, dead branches, "for future use" parameters. Remove.
- **Duplication / reuse** — logic that re-implements something that already exists, or repeats itself within the stage. This lens reaches beyond the diff: `grep` the module, its sibling entry-point files, and the rest of the repo for the distinctive shapes just written (parse/validate/resolve blocks, dispatch branches, success tails, string-splitting predicates). Two or more contiguous blocks of roughly 4+ lines differing only in a single expression get factored into one helper; a **third near-identical sibling block is a hard trigger** to parameterise rather than paste. Apply the same rule to test fixtures, fakes, and payload builders — reuse or hoist them into the project's shared-fixture mechanism instead of re-declaring per file. Exempt framework-mandated boilerplate and genuine cross-boundary config that cannot be imported.
- **Supersession / orphans** — this lens looks *beyond* the stage's diff. Whenever the stage introduced a path that **replaces or obsoletes** existing code (a new function/class/module/endpoint superseding an old one, a rewired call site that bypasses a previous implementation), `grep` the codebase for remaining references to the superseded symbol(s). If nothing outside its own definition and tests still references it, it is now a dead-code island — **delete it, and its now-dead tests, in this same stage** so the orphan never outlives the commit that stranded it. Record a non-trivial removal under *Deviations from plan*. Do **not** delete on a zero-grep alone when the symbol is reachable in ways a text search misses — public/exported API with external consumers, dynamic dispatch (reflection, string-keyed registries, DI containers), serialization targets, or framework entry points; flag those to the user (or leave them for the Step 7 sweep) instead of removing them.
- **Functional issues** — off-by-one, wrong default, swapped arguments, error paths that swallow errors, missing nullability handling. Fix with another test if behavior is non-obvious.
- **Inefficiencies** — N+1 queries, unbounded scans, blocking I/O on hot paths, redundant work in tight loops, leaks of file handles / connections / listeners. Fix.
- **Security issues** — injection (SQL/command/template/prompt), missing input validation at trust boundaries, secrets in code or logs, unsafe deserialization, path traversal, SSRF, missing authz checks. Fix immediately; never defer security to a later stage unless the plan explicitly stages it that way.
- **Style/comments** — remove comments that describe *what* the code does or reference the current task. Keep only comments that explain non-obvious *why*. No multi-paragraph docstrings unless they already exist in the file's style.

If a fix changes behavior, add or update a test to lock it in (go back to 5c briefly).

### 5h. Final test pass and commit
Run `TEST` (the command recorded in Step 3 sub-point 7) one more time after self-review edits. All green.

Then commit. Use one commit per stage with this message format (via HEREDOC). `<version>` is the integer feature version from Step 1; `<N>` is the stage number:

```
<type>(plan v<version>): Stage <N> — <stage title>

<one-paragraph summary of what changed and why,
referencing design §<n> / plan Stage <N>>
```

Where `<type>` is `feat` for new behavior, `refactor` for non-behavioral structural change, `chore` for scaffolding-only stages, `fix` if the stage corrected a bug, `test` if the stage was tests only.

Stage `git add` should add **only** the files this stage touched. Prefer `git add <files>` over `git add -A` to avoid sweeping in unrelated changes. Never `--no-verify`, never `--amend` a previous commit.

A stage commit contains the stage's source and test files only. Anything else that changed alongside it — plan-file deviation notes from 5d, repo-mandated side artifacts (changelog, wiki), tracker edits — goes in a separate `docs:`-typed commit, either straight after the stage commit or folded into the Step 8 tracker commit. Keep `(plan v<version>):` out of these docs commit subjects so they never pollute Step 4's resume grep (e.g. `docs: record plan v<version> Stage <N> deviation`).

After the commit, run `git status` to confirm a clean tree before moving to the next stage.

### 5i. Move to the next stage
Loop back to 5a for the next stage. Between stages, do not push, do not switch branches, do not modify the plan/design unless 5d forced a deviation note.

## Step 6 — Stop conditions during the loop

Stop the loop immediately (and tell the user) if any of the following happen:

- A test fails after self-review edits and you cannot diagnose it within a reasonable attempt.
- A stage requires a decision not covered by the plan or design — surface to the user via `AskUserQuestion`; do not invent. **This applies even in auto / non-interactive mode**: an instruction to "work without stopping" or "skip clarifying questions" does not authorise inventing requirements. Inventing a missing decision and pushing code on top of it costs more than the pause.
- The working tree becomes dirty in a way you didn't cause (e.g. another process is writing files).
- A security issue is too large to fix within the stage and the plan didn't account for it.
- The plan turns out to be wrong in a way that would require revising the design (not just the plan). Stop; recommend `/feature-design` to produce a new feature version.

When stopping, leave the repo in the cleanest reasonable state: uncommitted partial work for the current stage stays uncommitted; never auto-revert the user's view of the tree without asking.

## Step 7 — Final coverage & dead-code sweep

After the last stage commits cleanly, run a coverage sweep:

- For every requirement in design §3, find at least one test that verifies it (search test files via `Grep`).
- For every component in design §5 *Architecture / components*, confirm the file(s) exist and have tests.
- Run `TEST` (from Step 3 sub-point 7) one last time. All green.
- **Dead-code sweep.** Run `DEADCODE` (from Step 3 sub-point 7) across the **whole project** and compare against the Step 3 dead-code baseline — only findings *not* in the baseline are orphans this feature introduced. The whole-project scope is deliberate: cross-stage orphans (one stage builds a path, a later stage supersedes it) live in files no single stage edited, so a diff-scoped scan would miss exactly the islands this sweep exists to catch. Reuse an existing build where the tool allows it (e.g. `periphery scan --skip-build`, or scope `vulture` to the touched packages plus their callers) to keep the run cheap. For each newly-orphaned symbol, **remove it and its now-dead tests** — *unless* it is reachable in ways static analysis misses (public/exported API with external consumers, dynamic dispatch, serialization targets, framework entry points), in which case surface it to the user rather than deleting. If a baseline finding stops appearing, drop it from the baseline silently. If `DEADCODE` is `none — no baseline` (no analyzer configured), do **not** improvise a scan; instead recommend the right tool for the project's language in the Step 10 summary (`vulture` for Python, `periphery` for Swift, `knip`/`ts-prune` for JS/TS, etc.) so the next run is covered.

If anything is missing (uncovered requirement, untested component, or a confirmed dead-code orphan), add a final lightweight stage following the same TDD cycle and commit it the same way — *Stage N+1 — Coverage gaps* for missing tests, or *Stage N+1 — Dead-code cleanup* (committed as `refactor`) for orphan removals. Update the plan file to reflect the added stage.

## Step 8 — Update the tracker

The tracker at `tracker_file` already exists from earlier stages. If the file is somehow missing (resolver `notes` flagged `tracker_seed: skipped`), defensively copy the plugin template:

```bash
find ~ -path "*/dev-skills/templates/feature-tracker.html" 2>/dev/null
# cp the match (prefer ~/.claude/plugins/ if multiple) to <tracker_file>
```

If no template can be located, skip the tracker update and note it in Step 10 — do **not** fail the whole skill.

Apply these edits via the `Edit` tool. For each `{{TOKEN}}`, check it is still literal text in the file. Skip silently if already substituted — with two caveats:

- Detect leftover literal tokens **in the rendered body only** — ignore the HTML comment legend at the top of the template, which names every token and makes a fully populated tracker look unfilled if grepped whole-file (risking overwrites of earlier skills' panels with empty placeholders).
- The Implementation panel is this skill's to fill **even when it holds no literal tokens**: if it shows the seeded placeholders (`Awaiting /feature-implement` / `Not yet filled — pending /feature-implement.`), replace them with the real content below. The skip-if-substituted rule protects the header tokens and other skills' panels, not this skill's own section.

**Header tokens** (only edit if still literal):

- `{{FEATURE_VERSION}}` → `<version>`.
- `{{FEATURE_TITLE}}` → `description` with hyphens replaced by spaces, preserving case.
- `{{FEATURE_SLUG}}` → `feature-v<version>-<description>`.
- `{{GENERATED_AT}}` → today's UTC date (`date -u +%Y-%m-%d`).

**Implementation section tokens** (this skill owns these). Compute the timestamp once via `date -u +"%Y-%m-%d %H:%M UTC"` and reuse the same value for the chip:

- `{{IMPLEMENTATION_AT}}` → `Updated <YYYY-MM-DD HH:MM UTC>` (the timestamp chip text — no surrounding HTML).
- `{{IMPLEMENTATION_BULLETS}}` → an `<ul>` of up to 10 high-level highlights a reviewer needs at a glance: e.g. `Stages completed: <N>/<N>`, `Tests: <pass count>/<total>`, `Design coverage: <N>/<N>`, `Pre-existing failures excluded: <count or None>`, `Dead-code orphans removed: <count or None>`, `Deviations from plan: <None | <count>>`, `Final commit: <short-sha>`, and any genuinely surprising outcome. One `<li>` per item, plain text.
- `{{IMPLEMENTATION_DETAILS}}` → free-form HTML rendering the run in increasing detail: a **Stages completed** list (one `<li>` per stage with title and commit short-sha) → a **Tests & lint** summary block (final counts, baseline failures excluded from regression gating, naming them) → a **Design coverage** `<table>` mapping requirements to verifying tests → **Deviations from plan** (or "None") → any **Notes** the user needs (e.g. branch left ahead of remote). Use `<h3>` for top-level section titles, `<h4>` for sub-sections, `<ul>` / `<table>` for content. Order content from highest-level to most detailed so a reader can stop reading at any depth.

**Other tokens** — substitute with the empty placeholder *only if still literal* (most will already be content from earlier stages):

- `{{BRAINSTORMING_AT}}` → `Awaiting /feature-storm`
- `{{BRAINSTORMING_BULLETS}}` / `{{BRAINSTORMING_DETAILS}}` → `<p class="empty">Not yet filled — pending /feature-storm.</p>`
- `{{DESIGN_AT}}` → `Awaiting /feature-design` (should never happen — design must exist; defend regardless)
- `{{DESIGN_BULLETS}}` / `{{DESIGN_DETAILS}}` → `<p class="empty">Not yet filled — pending /feature-design.</p>` (same caveat)
- `{{PLAN_AT}}` → `Awaiting /feature-plan` (should never happen — plan must exist; defend regardless)
- `{{PLAN_BULLETS}}` / `{{PLAN_DETAILS}}` → `<p class="empty">Not yet filled — pending /feature-plan.</p>` (same caveat)

**Progress bar** (mandatory transition — only fired in this step, after all stages are green and committed):

- old_string: `data-stage="implement" data-state="pending"`
- new_string: `data-stage="implement" data-state="complete"`

If the Edit fails, the implement step is already `complete` (rerun on a fully tracked feature) — leave it alone.

Do **not** touch other skills' tokens beyond the empty-placeholder fallback above. Do **not** touch other skills' progress steps.

Finish by committing the tracker update — plus any still-uncommitted docs edits from the run (plan deviation notes, repo-mandated side artifacts) — as one docs commit, e.g. `docs: mark v<version> implementation complete in tracker`, so the run ends with a clean tree. This is a docs commit, not a stage commit: keep `(plan v<version>):` out of its subject so it never matches Step 4's resume grep.

## Step 9 — Capture lessons

Invoke the `lessons-capture` skill in this plugin via the `Skill` tool with the single argument `feature-implement`. It runs the reflection protocol, appends a dated entry to `~/.claude/dev-skills/lessons/feature-implement.md`, and returns the entry body for you to paste under the *Skill-improvement recommendations* heading in Step 10.

Do not run the reflection inline — `lessons-capture` is the single source of the protocol for all skills in this plugin.

## Step 10 — Present the final summary

In chat, output a scannable summary. Use this shape:

```
Implemented: <prereq_file path>  (against <design path>)
Branch: <branch> (no new branches created, no pushes)
Tracker: <tracker_file path>

**Feature:** v<version> — <human-readable title>

**Stages completed**
- Stage 1 — <title> — <commit short-sha>
- Stage 2 — <title> — <commit short-sha>
- ...

**Tests:** <e.g. "All 42 tests passing">
**Pre-existing failures excluded from regression gating:** <"None" or comma-separated test ids from the Step 3 baseline>
**Design coverage:** <N>/<N> requirements verified by tests.
**Dead-code sweep:** <"None found" | "<N> orphan(s) removed in Stage N+1" | "No analyzer configured — recommend installing <vulture|periphery|…>">
**Deviations from plan:** <"None" or short list, one line each>

**Skill-improvement recommendations**
- <as produced in Step 9>

**Next step:** eval offer coming up; push when ready after that (this skill never pushes — run /push when you're satisfied).
```

Keep the chat output under ~40 lines. Do not paste diffs or full file contents.

## Step 11 — Offer to run the evals

The run ends with the implementation committed but **not pushed** — exactly the state the plugin's two eval skills score. Offer them now, after the summary, so quality metrics for this run are captured before anything is pushed.

Ask via `AskUserQuestion` exactly once:

- **question**: `"Run the eval suite on this implementation? evals-code-run scores the unpushed commits for duplication/bloat/inefficiency/security (logs to ~/.claude/evals/code.json); evals-e2e-run scores the feature's storm/design/plan artefacts and their consistency with the implementation (logs to ~/.claude/evals/design.json). Both are read-only towards the repo."`
- **header**: `"Run evals?"`
- **options**:
  - `{ "label": "Yes, run both", "description": "Run evals-code-run and evals-e2e-run in two parallel read-only subagents; two eval-log appends, no repo changes." }` (mark this as Recommended)
  - `{ "label": "No, skip", "description": "Finish without evals; /evals-code-run and /evals-e2e-run can be run manually later." }`

If the user declines (or picks "Other" with decline intent), the skill is done. In a truly headless run with no channel to ask, default to skipping — the evals can always be run by hand later.

If the user accepts, launch **two subagents in parallel** — one message, two `Agent` calls, `subagent_type: general-purpose` — one per eval skill, and wait for both. Parallel is safe by construction: both skills are read-only towards the repo, and they write to different log files. Each subagent starts with a fresh context, so its brief must be self-contained:

- Instruct it to invoke its skill via the `Skill` tool — `evals-code-run` for one, `evals-e2e-run` for the other (plugin-qualified `dev:` form where needed) — and execute it to completion.
- State explicitly: "You are being run from /feature-implement's eval offer; the user already confirmed via AskUserQuestion — execute the skill without re-asking." This satisfies each eval skill's Step 0 clause for contexts with no user channel.
- Pass the repo root, the current branch, and the feature version `v<version>` for context. If Step 3 found no remote/upstream for this branch, also pass the base ref the evals should diff against (as the skill argument) — without an upstream, "unpushed" is otherwise undefined for them.
- Constraint: read-only towards the repo — no edits, no commits, no pushes; the only writes are the eval logs under `~/.claude/evals/`.
- Return format: the eval skill's own final summary — the score table plus the log-write confirmation — verbatim.

When both return, relay the two score summaries to the user in compact form. If a subagent fails or the `Agent` tool is unavailable in your context, run that eval skill directly in this conversation instead (its own steps handle everything). Never fail the implementation run over an eval error — report it and finish.

## Constraints (non-negotiable)

- **No new branches.** Implementation happens on the current branch (default branch unless the user confirms otherwise). Never `git checkout -b`.
- **Never push.** This skill commits only. The user invokes `/push` separately.
- **Never `--no-verify`, never `--amend` a published commit, never force-push.** Standard git safety still applies.
- **Both files must exist on disk.** No implementation begins without the design and plan files confirmed present under the resolver-returned feature folder (Step 1 + Step 2). Never bypass the resolver.
- **TDD as written in the plan is mandatory.** Behavior-changing stages: write test → confirm fail → implement → confirm pass. Scaffolding-only stages may skip the test cycle; the plan must mark them.
- **Never build on a red test baseline.** If Step 3's `TEST` baseline shows any failing tests, stop before the stage loop and let the user investigate, file a bug (`/bug-submit`), or halt (Step 3 sub-point 9) — implementation never proceeds on top of pre-existing test failures. This gate holds even under autonomous "don't stop to ask" instructions; a truly headless run defaults to halting.
- **One commit per stage.** No batch commits across stages. No commits mid-stage. The commit-message format is the resume contract for Step 4 — do not deviate from `<type>(plan v<version>): Stage <N> — <title>`.
- **Execution strategy changes only the executor.** Per-stage / per-chunk subagent modes run the identical `5a`–`5i` cycle and obey every constraint here — current branch only, no new branches, no pushes, one commit per stage with the exact message format. Units run strictly in order, never in parallel. The strategy question **must be asked whenever the user can be prompted** — slash-command, chain-in, and autonomous runs included — and is skipped (defaulting to Direct) only when ≤1 stage remains or the run is truly headless (no interactive channel). Steps 7–11 always run in the main agent, never in a subagent (Step 11's accepted evals are delegated to subagents by design).
- **The eval offer never blocks or mutates.** Step 11 runs only with user consent, launches read-only skills, and a declined offer or a failed eval never fails the implementation run. The offer comes before any push because both eval skills score unpushed commits.
- **Integer versions only.** `v<N>` in commit messages, file references, and tracker tokens — never `v<N>.<M>`.
- **No silent design or plan drift.** If reality forces a change, update the plan file and record it under *Deviations*. Stop and surface big drifts to the user.
- **Self-review every stage before commit.** Bloat, duplicated or reimplemented logic, superseded/orphaned code, functional issues, inefficiencies, security — fix in the stage, not later.
- **Dead-code sweep is baseline-scoped and never deletes blindly.** Step 7's `DEADCODE` run gates only orphans this feature introduced (diffed against the Step 3 baseline), never pre-existing dead code; symbols reachable via public API, dynamic dispatch, serialization, or framework entry points are surfaced to the user, not auto-removed. With no analyzer configured, recommend one rather than improvising a scan.
- **Tracker edits are defensive.** Substitute only tokens still literal `{{...}}`; never overwrite content placed by `/feature-storm`, `/feature-design`, `/feature-plan`, or any other skill. The progress bar's `data-stage="implement"` entry is this skill's alone to touch.
- **No symlinks.** If a defensive tracker template copy is needed in Step 8, always copy — never link.
- **Lessons capture runs every time.** Step 9 always invokes `lessons-capture`; whether it produces a recommendation or "none this run" is decided by that skill.
- **Never paste full code or plan content into chat.** Step 10 is summary only.
