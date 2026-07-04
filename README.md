# dev-skills

A Claude Code plugin that ships a **TDD-driven feature workflow** plus standalone helper skills. Use it to brainstorm a feature, design it, plan it as a sequence of test-first stages, execute the plan stage-by-stage, and score the result — all from inside Claude Code.

There is no application code, no build step, no test suite. The artifact **is** the set of `SKILL.md` files under `skills/`, the HTML templates under `templates/`, and the one bit of executable code the plugin carries: the `hooks/` remote-readiness check.

## Notes

1. Clone the repo:

   ```bash
   git clone git@github.com:cagriy/dev-skills.git
   ```

2. Go into the repo folder and start Claude Code:

   ```bash
   cd dev-skills
   claude
   ```

3. Give Claude this prompt:

   > Review this repo for unfamiliar directory paths and amend them for my system. Then install the plugin for this computer user.

See the [Install](#install) section below for the marketplace-based installation.

## What it gives you

- A single, opinionated workflow for taking a feature from idea → design → plan → implementation, with **clarification gates at every step** so the skill refuses to drift past unclear requirements.
- A **prompt router** (`feature-dispatch`, model-invoked) that spots non-trivial feature requests in your normal prompts and offers to enter the chain at the right point — `/feature-storm` for vague ideas, `/feature-design` for clear-but-undesigned ones — before any code is written.
- A **per-feature output folder** (`features/feature-v<N>-<description>/`) in the target project that collects the brainstorm, design, plan, and a live HTML tracker.
- A **local bug workflow**: `bug-submit` files a triaged bug as a folder under `bugs/` (with optional image attachments copied in), and `bug-fix` diagnoses one open bug to a fact-based root cause, fixes it test-first, then archives it and commits. Both render a shared `bugs/bugs-tracker.html` Issues view.
- An **eval suite**: `evals-code-run` scores your unpushed commits for duplication, bloat, inefficiency, and security (higher = worse); `evals-e2e-run` scores a chain-built feature's artefact quality and stage-to-stage consistency (higher = better). Both append JSON entries to logs under `~/.claude/evals/` and are offered automatically at the end of `/feature-implement`.
- A lightweight **lessons-learned loop**: the feature skills and `bug-fix` append improvement observations to a per-skill log; you periodically apply them with `/lessons-learn`.
- A **remote-readiness hook** that fetches on session start (and at most every 2 hours on prompts) and warns you when your branch is behind its upstream. It never pulls and never blocks — Claude just offers you a `git pull --ff-only` on its next turn.

## The skill chain

**[Interactive architecture diagram → `diagram/index.html`](diagram/index.html)** — open it in a browser for the full end-to-end picture (every skill, step, gate, loop-back, and hook). Regenerate it with `/diagram-update` after changing skills.

```
                  (model-only, fires on feature-shaped prompts)
                              feature-dispatch
                                    │
                  ┌─────────────────┴─────────────────┐
                  ▼ (vague / high-level)              ▼ (clear-but-undesigned)
/feature-storm  →  /feature-design  →  /feature-plan  →  /feature-implement
       │                │                  │                   │
       │                │                  │                   ├──→ offers /evals-code-run
       ├────────────────┴──────────────────┴───────────────────┤    + /evals-e2e-run
       │     each one resolves its feature folder & writes     │
       │     to features/feature-v<N>-<desc>/ + tracker.html   │
       │                                                       │
       └─────── each one's final step captures one lesson ─────┘
                            │
              ~/.claude/dev-skills/lessons/<slug>.md
                            ↑
                  /lessons-learn <slug> (periodic)
```

Per-feature output structure (in the **target project's** cwd):

```
features/
  feature-v<N>-<description>/
    feature-storm-v<N>-<description>.md       ← optional
    feature-design-v<N>-<description>.md
    feature-plan-v<N>-<description>.md
    feature-v<N>-tracker.html                 ← live progress page
```

Integer feature versions only (`v1`, `v2`, … `v10`). No minor versions; to revise, re-run the stage on a new version (or pass `version=<N>` to overwrite).

## User-facing skills

### `/feature-storm`  *(optional, first step)*
High-level product / requirements brainstorm. Establishes goals, scope, users, technical constraints, and open questions before any technical design starts.

- **Use when:** you want to think through a feature at the product layer before committing to a design.
- **Outputs:** `feature-storm-v<N>-<desc>.md` and updates to the tracker's *Brainstorming* section.
- **Chains into:** `/feature-design`.

### `/feature-design`
Produces the technical design for a feature. Runs a mandatory clarification loop until all open decisions are closed, then a self-review pass for functional / security / efficiency gaps.

- **Use when:** you have a clear product picture and need to lock in the technical approach.
- **Outputs:** `feature-design-v<N>-<desc>.md` and updates to the tracker's *Design* section.
- **Refuses to finish** while any open question remains in §8.
- **Chains into:** `/feature-plan`.

### `/feature-plan`
Maps the design 1:1 to a staged, **test-first** implementation plan. Each stage names the files it will touch, the test(s) to write first, the implementation steps, and a definition of done. The planning core runs inside a single subagent that asks no questions: planning-level gaps are decided autonomously and recorded in the plan's *Planning decisions taken* section, while design-level gaps halt the run and point you back at `/feature-design`.

- **Use when:** the design is locked and you want a concrete, executable roadmap.
- **Outputs:** `feature-plan-v<N>-<desc>.md` and updates to the tracker's *Plan* section.
- **Refuses to run** without a design file, or if the design has unresolved §8 questions.
- **Chains into:** `/feature-implement`.

### `/feature-implement`
Executes the plan stage-by-stage on the **current branch**. Never creates branches, never pushes; one commit per green stage. After each stage: coverage check → self-review (bloat / functional issues / inefficiency / security) → run tests → commit. Resumes from the last committed stage on re-runs.

- **Use when:** the plan is approved and you want to actually build the feature.
- **Outputs:** code, tests, and one commit per stage on the current branch; updates to the tracker's *Implementation* section.
- **Tooling autodetect:** picks up `TEST` / `LINT` / `FORMAT_CHECK` / `TYPE_CHECK` / `BUILD` commands from project manifests + CI config; reuses those slot names throughout.
- **Baseline gate:** establishes a test/lint baseline before building; if the test suite is already red it halts and asks whether to investigate, file a bug via `/bug-submit`, or stop — it never builds on a red suite.
- **Execution strategy:** asks up front whether to run every stage directly, one subagent per stage, or one subagent per three-stage chunk — always sequential, always one commit per stage.
- **Closes by offering the eval suite:** on consent, runs `evals-code-run` and `evals-e2e-run` in two parallel read-only subagents and relays their scores.
- **Step 0 confirmation is non-negotiable** because this skill writes code and creates commits.

### `/bug-submit`  *(standalone — not part of the feature chain)*
Files a bug report as a local folder under `bugs/` in the current repo, with a triage section in the report grounded in a quick read of the relevant code paths.

- **Use when:** you've just hit a bug and want a clean, triaged report tracked in the repo without leaving the terminal.
- **Accepts:** a bug description in `$ARGUMENTS` (or asked for if missing) and image attachments (paths in args, or screenshots already pasted into the conversation).
- **Outputs:** a `bugs/bug-N-<description>/` folder containing `bug-N-<description>.md` and any attached images copied in, plus a regenerated `bugs/bugs-tracker.html` — an HTML "Issues" view (built from the shared tracker template) listing open and closed bugs, each expandable to its full report and screenshots. The next bug number is allocated by scanning both `bugs/` and `bugs/archive/`. Nothing is sent to GitHub or pushed; resolve a bug by moving its folder into `bugs/archive/` (the tracker reflects it on the next run) — or run `/bug-fix`.
- **Step 0 confirmation is non-negotiable** because this skill writes files into your repo.

### `/bug-fix [bug number]`  *(standalone — not part of the feature chain)*
Diagnoses, fixes (test-first), and closes one open bug tracked under `bugs/`.

- **Use when:** you want to fix a filed bug, resolve the next open issue, or close out a defect from `/bug-submit`.
- **Accepts:** an optional bug number in `$ARGUMENTS`. With none, it takes the **lowest-numbered open** bug (a folder in `bugs/`); if there are no open bugs it stops and hands you over to `/bug-submit`.
- **How it works:** grounds in the codebase + last feature → clarifies the report (`AskUserQuestion`, with options + a recommendation) → establishes a **fact-based root cause before touching code** → explains the fix for your approval → implements it **TDD** (failing test first) → asks you to verify when it can't test automatically (UI etc.), looping back to diagnosis if it's not actually fixed.
- **Outputs:** the code fix + regression test, a `## Resolution` section (incl. lessons learned) appended to the bug's report, the bug folder moved to `bugs/archive/`, a regenerated `bugs/bugs-tracker.html`, and **one commit on the current branch** (never pushed — run `/push` when ready).
- **Step 1 confirmation is non-negotiable** because this skill modifies code and commits.

### `/evals-code-run [base-ref]`  *(standalone, read-only)*
Scores everything committed on the current branch but **not yet pushed** across four dimensions — **duplication** (against the rest of the repo, not just the diff), **bloat**, **inefficiency**, and **security** — via four parallel read-only subagents.

- **Use when:** you've just landed commits (typically via `/feature-implement` or `/bug-fix`) and want a quality read before pushing. Also offered automatically by `/feature-implement`'s closing step.
- **Accepts:** an optional base ref in `$ARGUMENTS` for when the branch has no upstream; otherwise diffs `@{u}...HEAD`.
- **Scoring:** each dimension is the percentage of added lines affected (0–100, **higher is worse**), plus a ≤100-word recommendation for improving `feature-implement` when issues are found.
- **Outputs:** four JSON entries per run appended to `~/.claude/evals/code.json`. Never modifies the repo, never commits, never pushes.

### `/evals-e2e-run [base-ref]`  *(standalone, read-only)*
Scores a **chain-implemented feature end-to-end**: artefact quality (storm / design / plan, rubric-based) and stage-to-stage consistency (storm→design, design→plan, and implementation vs each artefact) — up to eight evals run as parallel subagents, each included only when its inputs exist.

- **Use when:** `/feature-implement` has just finished and you want to know how well the pipeline held together. This is the expected initiator; it's also offered automatically by `/feature-implement`'s closing step.
- **Accepts:** an optional base ref in `$ARGUMENTS`; otherwise resolves the feature from the unpushed commit range.
- **Scoring:** every score is 0–100, **higher is better** (opposite polarity to `evals-code-run`); scores below 80 carry a ≤100-word recommendation targeting the responsible feature-* skill.
- **Outputs:** one JSON entry per eval appended to `~/.claude/evals/design.json`. Never modifies the repo, never commits, never pushes.

### `/diagram-update`  *(maintenance — runs only inside this repo)*
Regenerates `diagram/index.html`, the interactive architecture diagram linked above, from whatever is on disk: every skill, hook, and template is re-read in full and the page is rebuilt wholesale from `templates/workflow-diagram.html`.

- **Use when:** skills have been added or changed and the diagram is stale.
- **Refuses to run** outside the dev-skills plugin repo itself.
- **Writes only** `diagram/index.html`; never commits or pushes.

### `/push [message]`  *(maintenance, user-only)*
Commits all outstanding changes with a generated (or provided) commit message in the repo's existing style, and pushes to the remote. Adds obvious non-repo files to `.gitignore` first; the repo must be clean after the push.

### `/release [major|minor|patch]`  *(maintenance, user-only)*
Releases the current project: detects the language (Python, Swift, or generic manifest), bumps the semantic version in the right source(s), updates `CHANGELOG.md` (Keep a Changelog format), then commits, tags, and pushes. Defaults to `patch`.

### `/lessons-learn <skill-name>`  *(maintenance, user-only)*
Consolidates the lessons log accumulated by a given skill, presents filtered improvements via a picker, edits the target `SKILL.md`, then archives the active log as a UTC-stamped snapshot.

- **Use when:** the log for a skill has built up (typically after several runs) and you want to apply the high-signal improvements.
- **Filters out:** language- or framework-specific suggestions, since the skills are deliberately language-agnostic.
- **Never auto-commits** — leaves the edits for you to review and commit.

## Internal skills (not user-invocable)

You don't call these directly — the user-facing skills (or the model) delegate to them.

- **`feature-dispatch`** — model-only prompt router. Fires when your message looks like non-trivial feature work (roughly ≥75 lines of code) and asks once whether to route into `/feature-storm` (vague / high-level) or `/feature-design` (clear but undesigned), or continue without dispatch. Stays silent for small changes, bug reports, or when you already picked an entry skill.
- **`feature-resolve`** — single source of pathing. Computes the right `features/feature-v<N>-<desc>/` folder, creates it on first use, seeds the tracker from the plugin template, and returns the resolved paths back to the calling skill.
- **`bug-tracker-render`** — single source of bug-tracker rendering. Called by `bug-submit` and `bug-fix` whenever the set of bugs on disk changes; regenerates `bugs/bugs-tracker.html` wholesale from the shared template plus the current `bugs/` / `bugs/archive/` state.
- **`lessons-capture`** — single source of the reflection protocol. Called as the final step of the four feature-* skills and `bug-fix`; appends one improvement entry (or "none this run") to `~/.claude/dev-skills/lessons/<slug>.md`.

## Hooks

The plugin registers one hook script, `hooks/remote-check.sh`, on **SessionStart** and **UserPromptSubmit**. It fetches (throttled to once per 2 hours on prompts) and, if your branch is behind its upstream, prints a terminal warning and has Claude offer a `git pull --ff-only` on its next reply. It never pulls, never prompts, and never blocks; it's a no-op outside a git repo, without an upstream, or offline.

## Install

This is a Claude Code plugin and is installed via the plugin system. Inside Claude Code:

```
/plugin marketplace add cagriy/dev-skills
/plugin install dev-skills@cagri-tools
```

The first command adds this repo as a marketplace (named `cagri-tools` inside its `marketplace.json`); the second installs the `dev-skills` plugin from it.

Or use `/plugin` interactively and pick `dev-skills` from the list.

Once installed, the user-facing slash commands listed above are available in any project. The skills write artefacts into the **target project's** cwd (under `features/` and `bugs/`); the per-skill lessons logs and eval logs live under `~/.claude/`.

To update later, re-run `/plugin install dev-skills@cagri-tools`. To remove, use `/plugin uninstall dev-skills`.

## Typical session

```text
# 0. (or just describe the feature — feature-dispatch offers to route you)

# 1. Brainstorm (optional)
/feature-storm Add reminders to the todo app

# 2. Lock the design
/feature-design

# 3. Stage it as a TDD plan
/feature-plan

# 4. Build it, one stage at a time
/feature-implement

# 5. Score the result (also offered automatically at the end of step 4)
/evals-code-run
/evals-e2e-run
```

Each step can also be run standalone with an explicit version, e.g. `/feature-design v3`.

## Conventions worth knowing

- **One feature per folder.** All artefacts for a given feature live under the same `features/feature-v<N>-<desc>/`.
- **Integer versions.** `v1`, `v2`, `v10` — never `v1.0` or `v1.2`.
- **The tracker (`feature-v<N>-tracker.html`)** is a single self-contained HTML page that summarises each step and tracks progress with a 4-step bar (`storm` → `design` → `plan` → `implement`). Open it in a browser to see the live state of the feature. The same template doubles as the bug tracker's Issues view.
- **Eval score polarity differs.** `evals-code-run` scores are *percentage of the change affected* (higher is worse); `evals-e2e-run` scores are *rubric items met* (higher is better).
- **`docs/` is legacy** for any project that used earlier versions of this plugin — the skills may read it for grounding context but never write to it.
- **The clarification step is mandatory** in the interactive skills and overrides any "skip clarifying questions" / "work without stopping" instructions. Closing material ambiguity is the entire point of these skills. (The one deliberate exception: `/feature-plan`'s planning core runs in a subagent and decides planning-level questions autonomously, recording them in the plan.)

## Layout of this repo

```
.claude-plugin/plugin.json       plugin manifest
.claude-plugin/marketplace.json  marketplace catalog (lets users add this repo via /plugin marketplace add)
skills/<slug>/SKILL.md           the product — one directory per skill
templates/feature-tracker.html   HTML template the feature-* skills and bug-tracker-render substitute into
templates/workflow-diagram.html  HTML template /diagram-update renders the architecture diagram from
diagram/index.html               the generated interactive architecture diagram
hooks/hooks.json                 hook registration (SessionStart + UserPromptSubmit)
hooks/remote-check.sh            the remote-readiness warning script — the only executable code here
CLAUDE.md                        contributor notes for working inside this repo
```

There is no build step. Changes ship as edits to the markdown skill definitions, the templates, and the hook script.
