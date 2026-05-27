# dev-skills

A Claude Code plugin that ships a **TDD-driven feature workflow** plus a few standalone helper skills. Use it to brainstorm a feature, design it, plan it as a sequence of test-first stages, and execute the plan stage-by-stage — all from inside Claude Code.

There is no application code, no build step, no test suite. The artifact **is** the set of `SKILL.md` files under `skills/` plus the `templates/feature-tracker.html` template.

## What it gives you

- A single, opinionated workflow for taking a feature from idea → design → plan → implementation, with **clarification gates at every step** so the skill refuses to drift past unclear requirements.
- A **per-feature output folder** (`features/feature-v<N>-<description>/`) in the target project that collects the brainstorm, design, plan, and a live HTML tracker.
- A **standalone bug-submit** skill that files a triaged bug report as a local folder under `bugs/` (with optional image attachments copied in) and a triage section grounded in a quick read of the codebase.
- A lightweight **lessons-learned loop**: every skill appends improvement observations to a per-skill log; you periodically apply them with one command.

## The skill chain

```
/feature-storm  →  /feature-design  →  /feature-plan  →  /feature-implement
       │                │                  │                   │
       │                │                  │                   │
       ├────────────────┴──────────────────┴───────────────────┤
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
Maps the design 1:1 to a staged, **test-first** implementation plan. Each stage names the files it will touch, the test(s) to write first, the implementation steps, and a definition of done.

- **Use when:** the design is locked and you want a concrete, executable roadmap.
- **Outputs:** `feature-plan-v<N>-<desc>.md` and updates to the tracker's *Plan* section.
- **Refuses to run** without a design file, or if the design has unresolved §8 questions.
- **Chains into:** `/feature-implement`.

### `/feature-implement`
Executes the plan stage-by-stage on the **current branch**. Never creates branches, never pushes; one commit per green stage. After each stage: coverage check → self-review (bloat / functional issues / inefficiency / security) → run tests → commit. Resumes from the last committed stage on re-runs.

- **Use when:** the plan is approved and you want to actually build the feature.
- **Outputs:** code, tests, and one commit per stage on the current branch; updates to the tracker's *Implementation* section.
- **Tooling autodetect:** picks up `TEST` / `LINT` / `FORMAT_CHECK` / `TYPE_CHECK` / `BUILD` commands from project manifests + CI config; reuses those slot names throughout.
- **Step 0 confirmation is non-negotiable** because this skill writes code and creates commits.

### `/bug-submit`  *(standalone — not part of the feature chain)*
Files a bug report as a local folder under `bugs/` in the current repo, with a triage section in the report grounded in a quick read of the relevant code paths.

- **Use when:** you've just hit a bug and want a clean, triaged report tracked in the repo without leaving the terminal.
- **Accepts:** a bug description in `$ARGUMENTS` (or asked for if missing) and image attachments (paths in args, or screenshots already pasted into the conversation).
- **Outputs:** a `bugs/bug-N-<description>/` folder containing `bug-N-<description>.md` and any attached images copied in, plus a regenerated `bugs/bugs-tracker.html` — an HTML "Issues" view (built from the shared tracker template) listing open and closed bugs, each expandable to its full report and screenshots. The next bug number is allocated by scanning both `bugs/` and `bugs/archive/`. Nothing is sent to GitHub or pushed; resolve a bug by moving its folder into `bugs/archive/` (the tracker reflects it on the next run).
- **Step 0 confirmation is non-negotiable** because this skill writes files into your repo.

### `/lessons-learn <skill-name>`  *(maintenance, user-only)*
Consolidates the lessons log accumulated by a given skill, presents filtered improvements via a picker, edits the target `SKILL.md`, then archives the active log as a UTC-stamped snapshot.

- **Use when:** the log for a skill has built up (typically after several runs) and you want to apply the high-signal improvements.
- **Filters out:** language- or framework-specific suggestions, since the skills are deliberately language-agnostic.
- **Never auto-commits** — leaves the edits for you to review and commit.

## Internal skills (not user-invocable)

You don't call these directly — the user-facing skills delegate to them.

- **`feature-resolve`** — single source of pathing. Computes the right `features/feature-v<N>-<desc>/` folder, creates it on first use, seeds the tracker from the plugin template, and returns the resolved paths back to the calling skill.
- **`lessons-capture`** — single source of the reflection protocol. Called as the final step of every other skill in this plugin; appends one improvement entry (or "none this run") to `~/.claude/dev-skills/lessons/<slug>.md`.

## Install

This is a Claude Code plugin and is installed via the plugin system. Inside Claude Code:

```
/plugin marketplace add cagriy/dev-skills
/plugin install dev-skills@cagri-tools
```

The first command adds this repo as a marketplace (named `cagri-tools` inside its `marketplace.json`); the second installs the `dev-skills` plugin from it.

Or use `/plugin` interactively and pick `dev-skills` from the list.

Once installed, the user-facing slash commands listed above are available in any project. The skills write artefacts into the **target project's** cwd under `features/feature-v<N>-<desc>/`, and the per-skill lessons log lives under `~/.claude/dev-skills/lessons/`.

To update later, re-run `/plugin install dev-skills@cagri-tools`. To remove, use `/plugin uninstall dev-skills`.

## Typical session

```text
# 1. Brainstorm (optional)
/feature-storm Add reminders to the todo app

# 2. Lock the design
/feature-design

# 3. Stage it as a TDD plan
/feature-plan

# 4. Build it, one stage at a time
/feature-implement
```

Each step can also be run standalone with an explicit version, e.g. `/feature-design v3`.

## Conventions worth knowing

- **One feature per folder.** All artefacts for a given feature live under the same `features/feature-v<N>-<desc>/`.
- **Integer versions.** `v1`, `v2`, `v10` — never `v1.0` or `v1.2`.
- **The tracker (`feature-v<N>-tracker.html`)** is a single self-contained HTML page that summarises each step and tracks progress with a 4-step bar (`storm` → `design` → `plan` → `implement`). Open it in a browser to see the live state of the feature.
- **`docs/` is legacy** for any project that used earlier versions of this plugin — the skills may read it for grounding context but never write to it.
- **The clarification step is mandatory in every skill** and overrides any "skip clarifying questions" / "work without stopping" instructions. Closing material ambiguity is the entire point of these skills.

## Layout of this repo

```
.claude-plugin/plugin.json       plugin manifest
.claude-plugin/marketplace.json  marketplace catalog (lets users add this repo via /plugin marketplace add)
skills/<slug>/SKILL.md           the product — one directory per skill
templates/feature-tracker.html   HTML template the feature-* skills substitute into
CLAUDE.md                        contributor notes for working inside this repo
```

There is no build step. Changes ship as edits to the markdown skill definitions plus the template.
