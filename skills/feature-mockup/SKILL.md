---
name: feature-mockup
description: Internal helper invoked only by other skills in this plugin (currently feature-design) to mock up the user-visible surface of the feature being designed and return the user's chosen direction as a parseable design decision. Builds self-contained static HTML mockup pages under features/feature-v<N>-<description>/mockups/, grounded in the host project's existing design language when it has one. A brand-new surface gets one overall view of how the feature would look, presented for the user's opinion; a modification to an existing surface (a new section or element, adjusted fonts or colours) gets a few uniquely named alternatives for the user to choose between or give feedback on. Iterates with the user until they are happy, then returns the accepted mockup, the alternatives considered, and the concrete UI decisions for the calling skill to fold into its design document. Accepts optional user-supplied visual references, which outrank the project's own conventions and bound the alternatives offered; the caller skips this skill entirely when the user already specified the whole surface, so references arriving here are partial by construction. Never writes application code, never wires a mockup into the project, and never calls feature-resolve or lessons-capture. Not user-invocable.
user-invocable: false
allowed-tools: Read, Grep, Glob, Write, Edit, AskUserQuestion, WebFetch, Bash(ls *), Bash(find *), Bash(mkdir -p *), Bash(test *), Bash(pwd), Bash(date *)
---

# feature-mockup — Visual mockup, iterated to a decision

Invoked as the mockup step of another skill in this plugin (currently `feature-design`, before it writes the design document). Your job is to show the user what the feature will *look* like, iterate on it with them until they are happy, and return the resulting UI decisions in a form the calling skill can design against.

**You are running inline, inside the calling skill's own turn.** The `Skill` tool loads these instructions into the caller's context — it does not delegate to a subagent. There is no second agent on the other side of this: the model reading this text is the same model that will carry on with the caller's remaining steps once the result block is out. Read every "the caller" below as "you, a few steps from now".

The point of externalising this is that a UI decision made in prose ("a panel on the right, roughly card-shaped") is a decision nobody actually took. A rendered page turns it into something the user can accept, reject, or redirect in one round — and the accepted page is a durable reference for `/feature-plan` and `/feature-implement` later.

## Input

The caller passes a comma-separated argument string with these slots:

- `feature_folder=<absolute path>` — **required**. The feature folder the caller received from `feature-resolve`. Use it verbatim.
- `version=<N>` — **required**. The integer feature version from the caller's resolution block; used in mockup filenames.
- `feature=<one-line statement of the surface to mock up>` — **required**. What the user will see, in the caller's words.
- `kind=<new|modify>` — optional. Pass it when the caller already knows; Step 3 classifies when it is absent, and sanity-checks an explicit value against the grounding.
- `references=<path-or-URL>[; <path-or-URL>…]` — optional, semicolon-separated. Visual references the **user themselves** supplied and that cover only part of the surface: an image path from the conversation, a design-tool or documentation URL, or a path to an existing page in the repo to follow. When the user's reference covers the *whole* surface, the caller skips this skill entirely and cites the reference directly — so anything arriving here is partial by construction, and this skill's job is to extend the user's direction rather than reinvent it.

Example:

```
feature_folder=/Users/x/proj/features/feature-v3-Add-Reminders, version=3, feature=reminder list and per-item reminder editor on the todo detail screen, references=bugs/bug-4-reminders/screenshot.png
```

If `feature_folder` is missing or does not exist on disk, or `feature=` is missing, stop with a one-line error naming the missing slot and ask the caller to retry. Do not guess from conversation context, do not create the feature folder, and never compute the folder yourself — `feature-resolve` owns pathing and the caller already ran it.

## Step 1 — Confirm there is a surface worth mocking up

Mockups are for **user-visible surfaces**: a GUI screen, a web page or component, a terminal UI, the shape of CLI output, a report or document layout, a notification / email template.

If the feature has no user-visible surface — a library or API-only change, a background job, a schema migration, an infrastructure or tooling change — emit the result block (Step 7) with `status: not-applicable` and a one-line reason, then continue with the caller's next step. **Do not invent a UI to justify running.**

If it is genuinely unclear whether the feature has a surface, ask once via `AskUserQuestion` ("Does this feature have a user-visible surface worth mocking up first?") with a recommended option, and honour the answer.

There is no proactive-invocation confirmation gate in this skill: the caller already gated its own run with the user, and asking twice for the same work is friction, not safety.

## Step 2 — Ground in the project's existing design language

Bounded, read-only exploration — enough to make the mockup look like it belongs in *this* project, not a wide audit.

**Anything passed in `references=` is read first and takes precedence.** `Read` each supplied path (images included) and fetch each supplied URL. Where a reference and the project's own conventions conflict on a *visual* choice, the reference wins and the mockup follows it — the user showed you what they want, and quietly overriding it with a grounded digest is the failure mode this rule exists to prevent. Where the reference is silent, the project's conventions fill the gap. If a reference cannot be read or fetched, say so in one line and carry on with the grounding rather than guessing at its content.

Look for, and read, whichever of these the project has:

- **The UI layer** — page/template/component/view files and their styles (in whatever form the project uses: markup templates, component files, stylesheets, style modules, native view definitions, terminal-render modules).
- **The design system** — design-token or theme files, style/theme configuration, a component library or pattern gallery, brand assets already committed to the repo.
- **Prior mockups** — sibling `features/feature-v*/mockups/*.html`. A direction the user already accepted is a constraint on this one; do not contradict it silently.
- **This feature's own artefacts** — the storm and design files in `feature_folder`, if present. They carry the requirement, the scope boundary and the constraints the mockup must respect.

From those, extract a **design-language digest** of at most 8 bullets: palette (actual values in use), typography (families, scale, weights), spacing / radius / shadow conventions, component patterns (buttons, cards, tables, form controls, nav), layout grid and density, light/dark handling, iconography, tone of the copy. Cite where each came from (`path:line`) so the mockup is traceable rather than invented. This digest is what the `design_language` line of the result block reports.

If the feature sits inside a third-party product's surface whose conventions matter, consult that product's official documentation for the conventions — docs-MCP servers first (`context7` for libraries and frameworks, vendor-specific servers for their own surfaces), `WebFetch` against official documentation only as a fallback. Invent nothing about an external surface.

**Greenfield projects (no UI to copy).** Ask the user once via `AskUserQuestion` (up to 4 questions in the one call) for direction before drawing anything: platform (web / desktop / mobile / terminal), a reference product or style they like, any brand or palette constraint, and density (spacious vs compact). Give concrete options with a recommendation on each. Never invent a brand identity silently and never adopt another company's identity as the project's own.

## Step 3 — Classify: new surface or modification

- **new** — the feature introduces a surface that does not exist yet.
- **modify** — the feature adds a section or element to an existing surface, or changes how an existing surface looks (fonts, colours, spacing, the arrangement of elements already there).

Decide from the Step 2 grounding: if the surface the feature lands on already exists in the codebase, it is a modification even when the addition is large. If the feature is genuinely both (a new screen plus a change to an existing one), take the dominant part as `kind` and cover the secondary part inside the same mockup, saying so in one line.

`kind` decides the shape of Step 4. Record it.

## Step 4 — Build the mockup page(s)

Run `mkdir -p <feature_folder>/mockups` first. Every file this skill writes lives in that directory and nowhere else — never in the application's own template, asset or style tree.

**Rules for every mockup file:**

- **Self-contained and offline.** One HTML file per mockup: inline `<style>`, inline SVG for icons, no CDN links, no remote fonts / images / scripts, no network requests at view time, no build step. It must render correctly opened straight from the filesystem. When the project's real font is not available locally, use the closest system font stack and name the intended family in the page banner.
- **Non-functional.** No real API calls, no credentials, no live data. Inline vanilla JS only for what makes the mockup legible (tab switching, a toggle, a hover state).
- **Obviously placeholder content.** Sample data that is realistic in shape and clearly fake in substance. Never paste real user data, real customer records, or any secret into a mockup.
- **A banner at the top of the page** carrying: `Mockup — not shipping code`, the feature version, the mockup's name, a one-line statement of what it shows, what distinguishes it from the other alternatives (when there are any), and the design language it follows.
- **Match the host project's behaviour** on responsiveness and light/dark theming where the project has it; do not add either as a novelty the project does not have.
- **File naming:** `<feature_folder>/mockups/mockup-v<N>-<name>.html`, where `<name>` is lowercase-hyphenated and unique within the folder.

**`kind=new` → one overall view.** A single page, `mockup-v<N>-overview.html`, showing how the whole feature would look: the primary screen (or screens) as labelled sections, the states that matter (empty, populated, error or loading, and the key interaction mid-flight), and how the feature slots into the existing navigation and layout. Do not fan out alternatives here — the ask is an overall view of the feature, and a single coherent page is what invites a useful opinion.

**`kind=modify` → a few named alternatives.** Produce 2–3 genuinely different options (never more than 4), each in its own file with a **unique, descriptive name** — `inline-panel`, `sidebar-drawer`, `stacked-cards` for placement choices; `warm-serif`, `high-contrast`, `compact-sans` for type and colour choices. Each page renders the existing surface as it is *today* plus the proposed change, so the delta is visible in context. Every alternative must differ on a real axis (placement, information hierarchy, density, type or colour system) and state its trade-off in the banner — three recolours of one idea is one alternative, not three.

**When `references=` were supplied, they bound the fan-out.** Every alternative honours what the reference already settles; the alternatives explore only what it leaves open. Never offer an option that contradicts the user's own reference — reopening a decision they already made with a picture is worse than offering one option.

## Step 5 — Present, and iterate until the user is happy

In chat, output a compact block: one line per mockup (name — absolute path — one-line intent), the axis the alternatives differ on, and a line on how to open them (a file path the user can click, or their platform's default opener). Keep it under ~25 lines and **never paste mockup HTML into chat** — the files are the artefact.

Then call `AskUserQuestion` exactly once per round:

- **`kind=new`** — question: `"How does this mockup of <feature> look?"`, header: `"Mockup"`; options: `{"label": "Looks right", "description": "Carry this into the design."}` (mark Recommended), `{"label": "Revise it", "description": "Tell me what to change and I'll re-render."}`, `{"label": "Show alternatives", "description": "Draw 2–3 named directions to choose between instead."}`.
- **`kind=modify`** — question: `"Which mockup direction should the design follow?"`, header: `"Mockup choice"`; one option per named alternative, the one that best fits the Step 2 digest listed first and marked Recommended with a one-line why, plus `{"label": "None — revise", "description": "None of these; here's what to change."}`.

**This step is mandatory even in auto / non-interactive mode.** If the user or the harness has told you to work without stopping or to skip clarifying questions, that instruction does **not** apply here — the user's opinion *is* the output of this skill, and a mockup nobody chose yields no decision to return. If there is genuinely no user channel at all, stop with `status: declined` and `notes: no user channel — mockup left unaccepted` rather than accepting one on the user's behalf.

Iterating on feedback:

- A **revision** of an existing direction overwrites the same file, so the folder always holds the live candidates. Record the revision round and what changed in that page's banner.
- A **genuinely new direction** gets a new unique name and its own file. Never repurpose a name the user has already been comparing — it invalidates the comparison they were making.
- Re-present and re-ask every round. Apply the feedback literally: if the user asked for a smaller heading, change the heading, not the layout.
- After **three rounds** without convergence, ask once whether to settle on the current best, hand the open UI question back to the caller's clarification loop (`open_ui_questions` in the result block), or drop the mockup (`status: declined`). Never loop silently.

Stop when the user accepts exactly one mockup, or explicitly declines them all.

## Step 6 — Record the outcome on disk

- **Keep every alternative file.** They are the record of what was considered and feed the caller's *Alternatives considered* section. Do not delete the rejected ones.
- In the accepted file's banner, mark `Accepted <YYYY-MM-DD>` (from `date -u +%Y-%m-%d`); in each rejected file's banner, mark `Not chosen`.
- Write no separate decision document. The design document the caller is about to write is the single place UI decisions live; a second record would drift from it.

## Step 7 — Return the decision to the caller

Echo a single block to chat. Use exactly this shape so the caller can parse it line-by-line:

```
feature-mockup result
---
status: <accepted | declined | not-applicable>
kind: <new | modify | n/a>
mockup_dir: <absolute path, or "n/a">
chosen_mockup: <filename of the accepted mockup, or "n/a">
alternatives: <comma-separated names offered, accepted one first; or "none">
design_language: <single line — what the mockup follows, and where it came from>
decisions: <semicolon-separated concrete UI decisions the caller must carry into the design>
open_ui_questions: <semicolon-separated UI questions left unresolved, or "none">
notes: <single line — greenfield direction taken, revision rounds, secondary surface covered, etc.; or "none">
```

`decisions` is the payload of this whole skill. Each item must be specific enough to design and implement against — placement and layout, which existing components are reused, which states are covered, palette and typography deltas, the key interaction. `"reminder list renders as a 320px right-hand drawer reusing the existing card component; empty state shows the illustration used on the todo list; accent stays #2F6FED"` is a decision; `"looks good"` is not. Never write a decision the user did not actually agree to.

**Do not end your turn here.** Nothing is waiting to pick this block up — you were loaded inline, so emitting the block is not a hand-off and there is no "return" to make. Emit it, then continue immediately, in the same turn, with the calling skill's next step: for `feature-design`, Step 6 (write the design document), carrying `decisions` into §5 (Interfaces / UI surfaces and Architecture), the rejected `alternatives` into §6, and a relative-path reference to `chosen_mockup` into §4 or §5. Any `open_ui_questions` go back through the caller's clarification loop — they must never be parked in the design's §8, which has to stay empty.

The only paths that end the turn are the explicit input errors in *Input*. A `not-applicable` or `declined` outcome still continues into the caller's next step — neither is a failure, and neither blocks the design.

## Constraints (non-negotiable)

- **Mockups only, never application code.** Never edit project source, templates, styles, configuration or dependencies; never wire a mockup into the app or its build; never leave a mockup where the application could serve it. The mockup is a throwaway reference artefact under `features/`.
- **Write only under `<feature_folder>/mockups/`.** Nowhere else, ever. Never create the feature folder itself — `feature-resolve` does that, via the caller.
- **Never call `feature-resolve` or `lessons-capture`.** Pathing arrives as input (the resolver creates folders and seeds trackers, so a mockup step must not touch it), and reflection belongs to the calling skill's own lessons step. Structurally enforced: this skill holds no `Skill` tool.
- **Self-contained, offline, no symlinks.** No CDN, no remote fonts / images / scripts, no build step, no external network requests at view time.
- **Placeholder data only.** Never real user or customer data, never secrets, keys or tokens, never a real private individual's details inside a mockup.
- **The host project's identity, not someone else's.** Follow the project's own design language; never reproduce a third-party product's branding, logos or byline as if it were the project's.
- **Alternatives are for modifications.** A brand-new surface gets one overall view; a modification gets 2–4 uniquely named alternatives that differ on a real axis. Never fan out for its own sake, and never offer two variants of the same idea.
- **The user's choice is the output.** Never pick on the user's behalf, never accept a mockup without an explicit answer, and never fabricate a `decisions` line.
- **A settled appearance is not reopened.** Anything in `references=` outranks the grounded digest on visual choices, bounds the alternatives, and is never drawn over. The caller skips this skill outright when the user's own artefact or description already specifies the whole surface; when you are running, the surface is only partly specified.
- **Iteration is mandatory**, including under autonomous instructions — see Step 5.
- **A successful run never ends the turn.** Emitting the Step 7 block is a checkpoint in the caller's run, not a stopping point.
- **The chat is the pointer, the files are the artefact.** Keep each round under ~25 lines of chat; never paste mockup HTML.
