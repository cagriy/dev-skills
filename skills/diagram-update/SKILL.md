---
name: diagram-update
description: Regenerate diagram/index.html — a single-file, interactive HTML diagram of the end-to-end workflow provided by this plugin's skills, hooks, and scripts. Use when the user wants to create, update, refresh, or regenerate the plugin workflow diagram, typically after skills have been added or changed. Runs only inside the dev-skills plugin repo itself (manifest name "dev-skills") and refuses anywhere else. Re-derives the whole diagram from the files on disk every run and overwrites any existing diagram/index.html wholesale — never merges or patches. Read-only towards everything except diagram/index.html; never commits or pushes. Step 0 confirms with the user before doing any work when invoked proactively; the confirmation is skipped when the user explicitly typed /diagram-update.
model: opus
effort: high
user-invocable: true
disable-model-invocation: false
argument-hint: (no arguments)
allowed-tools: Read, Write, Grep, Glob, Bash(git *), Bash(ls *), Bash(find *), Bash(mkdir *), Bash(test *), Bash(date *), Bash(jq *), Bash(pwd)
---

# diagram-update — Regenerate the plugin workflow diagram

You are running the `diagram-update` skill. Your job is to analyse **everything the plugin ships** — every skill under `skills/`, the hook config and scripts under `hooks/`, and any other executable or template — and render one high-quality, self-contained, interactive HTML page that explains the end-to-end workflow, saved as `diagram/index.html` at the repo root.

The diagram is a **generated artefact**: it carries no state of its own, so this skill rebuilds it wholesale every run. "Create" and "update" are the same operation — if `diagram/index.html` already exists it is **overwritten entirely**, never merged. Never hardcode the current skill set into reasoning shortcuts: the whole point of this skill is that the diagram is re-derived from whatever is on disk *now*.

This skill has nine steps (Steps 0–8). Execute them in order.

## Step 0 — Confirm before proceeding (when invoked proactively)

Check the most recent user message for the literal tag `<command-name>/diagram-update</command-name>` (or, equivalently, a leading `/diagram-update` typed by the user). If present, skip this step and continue with Step 1.

Otherwise (proactive invocation from natural-language intent), ask once via `AskUserQuestion`:

- **Question**: "Regenerate the plugin workflow diagram? This overwrites `diagram/index.html` from the current skills/hooks on disk."
- **Options**: "Yes, regenerate" / "No, skip".

On anything other than an explicit yes, stop without touching the filesystem.

## Step 1 — Gate: dev-skills repo only

- `git rev-parse --show-toplevel` → `repo_root`. If it fails, stop: this skill only runs inside the dev-skills plugin repo.
- `jq -r .name "<repo_root>/.claude-plugin/plugin.json"` must output exactly `dev-skills`. If the file is missing or the name differs, stop with one line: `diagram-update: refused — this skill only runs inside the dev-skills plugin repo (manifest name "dev-skills").`
- Record `plugin_version` (`jq -r .version`) and `generated_at` (`date -u +"%Y-%m-%d %H:%M UTC"`) for the page header.

## Step 2 — Inventory the plugin

Enumerate, from `repo_root`:

- `skills/*/SKILL.md` — every skill, including internal ones and this skill itself.
- `hooks/hooks.json` and every script it references (e.g. shell scripts under `hooks/`).
- `templates/` and any other scripts or executables the plugin ships.

Read **every one of these files in full**. Do not work from `CLAUDE.md` summaries or memory of the plugin — the files are the source of truth, and the diagram must reflect skills added or changed since any summary was written.

## Step 3 — Extract the model

For each skill, extract:

- **Identity**: slug, one-line purpose (from the frontmatter description), and the invocation surface derived from frontmatter — `user-invocable: false` → *Agent only*; `disable-model-invocation: true` → *User only*; otherwise → *User + Agent*.
- **Steps**: the skill's own ordered procedure steps (its `## Step N` headings, or numbered process sections for skills without formal step headings). For each: a title of **at most three words** (e.g. "Confirm invocation", "Resolve paths", "Baseline tests") and a 2–4 sentence plain-language explanation of what the step does — written for a reader who has never opened the SKILL.md.
- **Approval gates**: every point where a human must answer before flow continues — Step 0 confirmation gates, `AskUserQuestion` decision points, plain-chat yes/no confirmations, verification handbacks.
- **Loop-backs**: every point where flow returns to an earlier step or another skill when something goes wrong — e.g. failed verification returning to diagnosis, a red test baseline halting into a bug-filing handover, a blocked plan returning to design.
- **Parallelism**: steps that fan out into concurrently running subagents, and which units run in parallel.
- **Delegation**: steps that run inside subagents rather than the main agent.
- **Cross-skill edges**: every reference from a step to another skill — internal-helper calls, chain-in/chain-out offers between stages, handovers, and hook-to-skill effects. Record the specific *step* each edge leaves from and (where determinable) arrives at.

For each hook: its trigger events, what the script actually does (read the script, not just the config), its throttling/no-op conditions, and any effect it has on skill flow.

## Step 4 — Derive the graph

- **Groups**: cluster the skills into workflow groups by their cross-references (e.g. a staged pipeline chained by chain-out offers; a bug workflow; eval scorers; reflection helpers; standalone utilities; hooks). Derive the groups from the edges — do not assume a fixed list.
- **Pipeline order**: where skills chain into one another, lay them out left-to-right in chain order as the dominant visual flow.
- **Shared services**: skills invoked by several others (resolvers, renderers, capture helpers) render as service boxes that multiple edges converge on.
- **Edge types**: distinguish *calls* (one skill invokes another), *chains into* (end-of-skill offer into the next stage), *hands over* (failure/handover path), and *loops back* (retry/return path). Every edge gets a source step, a target (step or skill), a type, and a short label.

## Step 5 — Design requirements for the HTML

One completely self-contained file: all CSS and JS inline, **no external requests of any kind** (no CDN scripts, fonts, or remote images). It must render correctly from `file://`. Build to this bar — the page is a presentable artefact, not a debug view:

- **Header**: plugin name, version, and generated date; a one-paragraph orientation sentence; a **legend** explaining every glyph, edge style, and pill used below.
- **Skill boxes**: one card per skill, grouped visually by workflow group with a distinct accent per group. Card header: skill name, invocation pills, one-line purpose. Internal (agent-only) skills are visually muted relative to user-facing ones.
- **Step boxes**: inside each card, the skill's steps in order as small boxes titled with the ≤3-word names. Steps that are approval gates carry a clearly visible gate badge (e.g. an amber "⏸ gate" chip); steps that fan out show their parallel units side-by-side inside a bracket labelled **parallel**; steps delegated to subagents are marked as such.
- **Click → floating window**: clicking any step box opens a floating pop-up (modal/popover) with: pills across the top — the parent skill's invocation surface (**User**, **Agent**, or both), plus contextual pills where they apply (**Approval gate**, **Subagent**, **Parallel**, **Commits**) — followed by the skill name, step number/title, and the 2–4 sentence explanation. Close on ✕, click-outside, and Escape. Only one pop-up open at a time.
- **Hover → dependency highlighting**: all edges render in an SVG overlay positioned over the boxes, faint by default so the page stays readable. Hovering a step box raises to full opacity every edge that step is a source or target of, highlights the connected boxes, and dims everything else; leaving restores the default. Edge positions are computed from the live DOM (`getBoundingClientRect`) and recomputed on window resize, so the lines stay glued to the boxes.
- **Edge styling**: normal flow edges solid; loop-back edges **dashed, in a warning colour, with an arrowhead and a short label** (e.g. "tests red → file bug"); handover/chain edges visually distinct per the legend.
- **Theme & polish**: respect `prefers-color-scheme` for light and dark; readable system-font typography; consistent spacing; the page may scroll but must not clip pop-ups or edges. No placeholder text, no lorem, no dead controls.

## Step 6 — Write the diagram

```bash
mkdir -p "<repo_root>/diagram"
```

Write the complete page to `<repo_root>/diagram/index.html` with `Write` — a full overwrite of whatever was there. Do not keep backups of the old file; git history is the record.

## Step 7 — Verify the output

Static sanity checks on the file just written (fix and re-verify on any failure):

- Every skill folder under `skills/` appears exactly once as a card (Grep the file for each slug).
- The number of step boxes per skill matches the steps extracted in Step 3.
- Every step box has corresponding pop-up content, and every edge references element ids that exist in the file.
- No `http://` or `https://` references anywhere in the file.
- The legend covers every edge style, badge, and pill actually used.

## Step 8 — Report

Output a short summary and stop:

```
diagram-update: diagram/index.html regenerated — <S> skills, <T> steps, <E> edges, <G> approval gates, <L> loop-backs, <P> parallel clusters
Open diagram/index.html in a browser to view.
```

## Constraints (non-negotiable)

- **Read-only except `diagram/index.html`.** Never modify skills, hooks, templates, or anything else; never write under `features/` or `bugs/`.
- **Never commit or push.** Leave the regenerated diagram as a working-tree change for the user.
- **Always regenerate wholesale.** Never patch the existing diagram in place — rebuild from the files so the diagram can never drift from reality.
- **Everything is re-derived.** No skill list, group, edge, or count is ever hardcoded from memory; a skill added yesterday must appear without this SKILL.md changing.
- **Fully self-contained output.** No external assets, no symlinks, no files other than the single `index.html`.
- This skill does **not** call `lessons-capture` — like `bug-submit`, it is a simple rendering skill and the reflection overhead isn't worth it.
