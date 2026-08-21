# Usage Report — Implementation Plan v1

**Status:** Draft
**Date:** 2026-08-21
**Design:** [feature-design-v1-usage-report.md](./feature-design-v1-usage-report.md)

## Overview

This plan builds the run usage report in eight stages, bottom-up: the transcript-parsing engine first (it is the only part that can be wrong invisibly), then its two rendering surfaces, then its CLI and side effects, then the tracker template's new tokens, then the `usage-report` skill, then the two halves of the call-site wiring across the four chain skills, and finally the documentation the change obliges. Stages 1–3 deliver **C1** (`scripts/usage_report.py`), Stage 4 delivers **C4** (eight template tokens) together with **C6** (`bug-tracker-render`'s blanking list, the template's second consumer), Stage 5 delivers **C2** (`skills/usage-report/SKILL.md`), Stages 6–7 deliver **C3** (the start and report blocks in `feature-storm`, `feature-design`, `feature-plan`, `feature-implement`), and **C5**'s tests are written per stage alongside the thing they assert rather than as one block at the end. The order follows design §9's rollout sequence, and Stage 4's position ahead of Stage 5 is not merely conventional — the repo's existing `tests/test_static.py::test_skill_tokens_exist_in_templates` asserts that every `{{TOKEN}}` named in any `SKILL.md` exists in a template, so the tokens must land no later than the skill that names them.

## Development strategy — Test-Driven Development

Every behavior-changing stage in this plan follows the TDD cycle:

1. **Write the test first.** Add the test(s) that describe the new behavior.
2. **Run the test and confirm it fails.** Capture the failure to prove the test exercises the new behavior.
3. **Write the implementation.** The minimum code needed to satisfy the test.
4. **Run the test and confirm it passes.** Plus the surrounding suite, to catch regressions.

Stages that fit a sanctioned non-red-first category — non-TDD (scaffolding | config-only | integration-verified), behaviour-preserving refactor/deletion, characterization/guard tests, platform-only/UI wiring — are labeled with that category and a one-line justification.

The runner is **pytest via `uv run pytest`** (the repo default excludes the `llm` marker). Every test this plan adds is free/static — none carries the `llm` marker. New Python unit tests live in `tests/test_usage_report.py` (sibling: `tests/test_static.py`); new fixtures live in `tests/fixtures/` (siblings: `tests/fixtures/design-flawless.md`, `tests/fixtures/plan-flawed.manifest.json`). New cross-file assertions extend `tests/test_static.py` as `TestUsageReportLifecycle`, modelled on the existing `TestHerdrLabelLifecycle`.

## Requirements coverage map

| Design req | Delivered by stage(s) |
| --- | --- |
| R1: `start` records the run's start timestamp, keyed by session + slug, before substantive work | Stage 3, Stage 6 |
| R2: `report` computes the window from that marker to now and emits the report | Stage 3, Stage 7 |
| R3: full token breakdown across `main` / `subagents` / `total`, plus request count | Stage 1, Stage 2 |
| R4: `elapsed` and `run time` as total-column figures | Stage 1, Stage 2 |
| R5: `output tok/s`, computed once across main + subagent requests | Stage 1, Stage 2 |
| R6: footer line with `service_tier`, `speed`, subagent count, outcome | Stage 2 |
| R7: chat output is a markdown table titled `Run usage`, matching the accepted mockup | Stage 2 |
| R8: exactly one JSONL entry per run appended to the usage log | Stage 3 |
| R9: the stage's tracker panel receives the same figures as an HTML table plus a headline chip | Stage 2, Stage 3, Stage 4 |
| R10: re-running a stage replaces that stage's tracker usage content | Stage 3, Stage 4 |
| R11: a run that halts early still reports and logs, marked `halted` | Stage 3, Stage 7 |
| R12: every assistant entry counted exactly once despite repeated snapshots | Stage 1 |
| R13: a reporting failure never fails, blocks or aborts the calling skill | Stage 3, Stage 5 |
| R14: no conversation content reaches the log or stdout | Stage 2, Stage 3 |
| R15: concurrent runs in parallel sessions never lose each other's log entries | Stage 3 |
| R16: reporting adds no more than a few seconds on multi-megabyte transcripts | Stage 1, Stage 7 |

Component coverage: **C1** → Stages 1–3; **C2** → Stage 5; **C3** → Stages 6–7; **C4** → Stage 4; **C5** → Stages 1–7 (per stage); **C6** → Stage 4.

## Stages

### Stage 1 — Transcript aggregation core

**Goal:** A pure, schema-aware core that turns a session's transcripts into a `RunMetrics`, unit-tested against synthetic JSONL fixtures.
**Design references:** §3 R3–R5, R12, R16; §4 *Where the data lives*; §5 *Architecture / components* (C1), §5 *Performance*, §5 *Testing strategy*.
**Touches:**
- `pyproject.toml` (modify — add `pythonpath` to `[tool.pytest.ini_options]`)
- `scripts/usage_report.py` (create)
- `tests/test_usage_report.py` (create)
- `tests/fixtures/usage-main.jsonl`, `tests/fixtures/usage-subagent.jsonl`, `tests/fixtures/usage-subagent-depth2.jsonl`, `tests/fixtures/usage-malformed.jsonl` (create)

**Steps (TDD):**
1. Add `pythonpath = ["."]` to `[tool.pytest.ini_options]` in `pyproject.toml`. This is a verified prerequisite, not a preference: `uv run pytest` puts only `<repo>/tests` on `sys.path` (there is no `tests/__init__.py` and no root `conftest.py`), so without it every test in this stage fails at collection with `ModuleNotFoundError: No module named 'scripts'`. No `scripts/__init__.py` is needed — namespace-package import resolves once the repo root is on the path.
2. Write the fixtures, copying the `message.usage` block shape field-for-field from a live transcript so they pin the real schema: `input_tokens`, `output_tokens`, `output_tokens_details.thinking_tokens`, `cache_creation_input_tokens`, `cache_creation.ephemeral_1h_input_tokens`, `cache_creation.ephemeral_5m_input_tokens`, `cache_read_input_tokens`, `server_tool_use.web_search_requests`, `server_tool_use.web_fetch_requests`, `service_tier`, `speed`; entry-level `type`, `timestamp` (ISO-8601 with milliseconds and a trailing `Z`, e.g. `2026-08-21T14:18:57.924Z`), `requestId`, `message.model`. Include: one `requestId` repeated across four snapshots with identical usage; a `>30s` gap terminating at a `user` entry; entries either side of the window boundary; one malformed line between two valid ones; and a depth-2 subagent file.
3. Write test: `tests/test_usage_report.py` covering `iter_entries` (a malformed line is skipped, neighbours still parse), `window_entries` (boundary timestamps inclusive, entries outside excluded), `aggregate` (four snapshots of one `requestId` count once — R12; absent optional fields default to 0), `timings` (a `>30s` gap ending at a `user` entry is excluded from `run_seconds` but not `elapsed`; a backwards clock clamps to 0), `throughput` (returns `None` at zero request time), `collect` (main and subagent columns split correctly across a `subagents/` directory including the depth-2 file), and `resolve_transcript` (returns `None` when the file is absent). Expected initial failure: pytest collection error `ModuleNotFoundError: No module named 'scripts.usage_report'`.
4. Run `uv run pytest tests/test_usage_report.py` — confirm it fails with that error.
5. Implement `scripts/usage_report.py`: stdlib only (it is invoked as the system `python3`, which is not the project venv), a `Usage` and a `RunMetrics` dataclass, and the pure functions `resolve_transcript`, `iter_entries`, `window_entries`, `aggregate`, `timings`, `throughput`, `collect`. Add a private `_parse_ts` that maps a trailing `Z` to `+00:00` before `datetime.fromisoformat` — the repo declares `requires-python = ">=3.10"` and 3.10 rejects the `Z` form the transcript actually uses. `timings` computes `request_seconds` as the sum, over main **and** subagent requests, of the span from the entry preceding a request to that request's last entry (design §5 *Interfaces*, and the accepted mockup's throughput note).
6. Run `uv run pytest tests/test_usage_report.py` — confirm pass. Run `uv run pytest` — confirm no regressions in `tests/test_static.py`.

**Definition of done:**
- `uv run pytest` is green, including the new module's tests.
- `scripts/usage_report.py` imports nothing outside the standard library.
- Every field of the `message.usage` block listed in design §4 is pinned by at least one fixture.
- Deduplication by `requestId` is asserted directly (R12).

**Risks specific to this stage:** The fixtures are synthetic, so a live schema change could keep them green while the field breaks — mitigated by copying the shapes field-for-field from a real transcript now, and by Stage 7's integration check against the live one. Note for the implementer: the live transcript shows **1–5** snapshots per `requestId` (mode 2), not the "roughly four" of design §4 — dedup by `requestId` is unaffected, but no test may assert an exact snapshot count.

### Stage 2 — Rendering and the log entry

**Goal:** The chat table, the tracker fragment and the log dict, each rendered from a `RunMetrics` and pinned by golden-string tests.
**Design references:** §3 R3–R7, R14; §5 *Architecture / components* (C1), §5 *Data model*, §5 *Security*, §5 *Testing strategy*; the accepted mockup [grouped-columns](./mockups/mockup-v1-grouped-columns.html).
**Touches:**
- `scripts/usage_report.py` (modify)
- `tests/test_usage_report.py` (modify)

**Steps (TDD):**
1. Write test: extend `tests/test_usage_report.py` with `render_markdown` (golden string — title `Run usage`; the mockup's exact row order `elapsed`, `run time`, `input_tokens`, `output_tokens`, `thinking_tokens`, `cache_write`, `ephemeral_1h`, `ephemeral_5m`, `cache_read`, `model`, `web_search`, `web_fetch`, `output tok/s`; the group rows `time` / `tokens` / `requests` / `throughput`; thousands separators; `—` in cells with no per-column meaning; and the footer `<tier> tier · <speed> speed · <n> subagents · outcome <outcome>`), `render_tracker_html` (golden string — a `<span class="chip usage">` whose text is `<elapsed> · <output> out · <tok/s> tok/s` and which contains **no** `Updated` followed by a date, plus a `<table class="usage">` with the same row order), and `log_entry` (the exact field set of design §5 *Data model*, `feature_version` `null` when unresolved, `evals_included` always present, the serialised entry under 2048 bytes, and — fed a fixture containing a secret-shaped string — that string absent from both the entry and the rendered table, R14). Expected initial failure: `AttributeError: module 'scripts.usage_report' has no attribute 'render_markdown'`.
2. Run `uv run pytest tests/test_usage_report.py` — confirm it fails with that error.
3. Implement `render_markdown`, `render_tracker_html` and `log_entry` in `scripts/usage_report.py`. `log_entry` builds its dict from an **explicit field list** — never by copying and filtering an entry — so no conversation content can reach it by omission; both renderers take only a `RunMetrics` and a footer context, never raw entries. Throughput renders `—` rather than dividing by zero, and clamped-to-zero durations render as `0s`.
4. Run `uv run pytest tests/test_usage_report.py` — confirm pass. Run `uv run pytest` — confirm no regressions.

**Definition of done:**
- Both rendered surfaces match the accepted mockup's row order and labels, asserted as golden strings.
- The usage chip provably cannot be mistaken for a `feature-list` timestamp chip (no `Updated <date>`).
- A secret-shaped fixture string appears in neither renderer's nor `log_entry`'s output.
- `uv run pytest` green.

**Risks specific to this stage:** Golden strings are brittle by design; keep them as whole-output comparisons so a row-order change fails loudly rather than a substring check that silently tolerates drift from the mockup.

### Stage 3 — CLI, start marker, log append, tracker application

**Goal:** The `start` / `report` CLI and the four side-effecting functions, each failing soft so the caller is never blocked.
**Design references:** §3 R1, R2, R8, R10, R11, R13–R15; §5 *Data model*, §5 *Interfaces*, §5 *Failure and edge cases*, §5 *Security*.
**Touches:**
- `scripts/usage_report.py` (modify)
- `tests/test_usage_report.py` (modify)
- `tests/fixtures/usage-tracker-min.html` (create — a minimal tracker carrying the eight tokens)

**Steps (TDD):**
1. Write test: extend `tests/test_usage_report.py` with `write_start` / `read_start` (round-trip through `tmp_path`; an absent marker returns `None`; a slug failing `^[a-z][a-z0-9-]{0,63}$` is rejected before it can reach a filename), `append_log` (two interleaved appends both survive; a pre-existing file is not truncated), `apply_tracker` (fills its own stage's two tokens; blanks the other six while they are still literal; on a second call **replaces** the previously rendered content between the same anchors rather than skipping — R10; a missing or unreadable tracker is a silent no-op), and `main(argv)` (`start` writes a marker; `report` prints the table, appends exactly one line, deletes the marker and exits 0; each failure case in design §5's table prints at most one line prefixed `usage report skipped —` and still exits 0; `CLAUDE_CODE_SESSION_ID` unset makes `start` a silent no-op). Expected initial failure: `AttributeError: module 'scripts.usage_report' has no attribute 'write_start'`.
2. Run `uv run pytest tests/test_usage_report.py` — confirm it fails with that error.
3. Implement in `scripts/usage_report.py`: `write_start`, `read_start`, `append_log` (a single `os.open(..., O_APPEND|O_CREAT|O_WRONLY)` write of one line — R15), `apply_tracker(tracker_path, slug, chip_html, table_html)` plus a module-level `TRACKER_TOKENS` mapping each stage slug to its `(chip_token, table_token)` pair, and `main(argv)` dispatching `start` / `report` with the flags from design §5 *Interfaces* (`--slug`, `--tracker`, `--feature-version`, `--outcome`, `--evals-included`). `main` resolves `<config-dir>` as `$CLAUDE_CONFIG_DIR` when set, else `~/.claude`. `repo_name` is the basename of the start marker's recorded `cwd` — not a `git` subprocess, which design §5 *Security* rules out. Wrap the whole of `report` so any unexpected exception degrades to one `usage report skipped — …` line and exit code 0 (R13).
4. Run `uv run pytest tests/test_usage_report.py` — confirm pass. Run `uv run pytest` — confirm no regressions.

**Definition of done:**
- `python3 scripts/usage_report.py report --slug feature-plan` with no marker present prints exactly one line and exits 0.
- No code path can raise out of `main`.
- The only paths written are under `<config-dir>/dev-skills/usage/` and an explicitly passed `--tracker`.
- `uv run pytest` green.

**Risks specific to this stage:** `apply_tracker` is tested against `tests/fixtures/usage-tracker-min.html`, not the shipped template, so the script and the template can drift — Stage 4 closes that gap with a test pinning `TRACKER_TOKENS` against `templates/feature-tracker.html`.

### Stage 4 — Tracker template tokens, chip and table styling, and the bug tracker's blanking list

**Goal:** The eight usage tokens exist in the shared template with their CSS, and the template's *second* consumer blanks all twenty feature-panel tokens.
**Design references:** §5 *Architecture / components* (C4, C6), §5 *Data model* (tracker tokens), §5 *Compatibility / migration*, §7 (the template-second-consumer risk).
**Touches:**
- `templates/feature-tracker.html` (modify)
- `skills/bug-tracker-render/SKILL.md` (modify — Step 3)
- `tests/test_static.py` (modify — new `TestUsageReportLifecycle`)

**Steps (TDD):**
1. Write test: add `TestUsageReportLifecycle` to `tests/test_static.py` with `test_eight_usage_tokens_exist_in_the_template` (all eight of `{{BRAINSTORMING_USAGE_CHIP}}`, `{{BRAINSTORMING_USAGE}}`, `{{DESIGN_USAGE_CHIP}}`, `{{DESIGN_USAGE}}`, `{{PLAN_USAGE_CHIP}}`, `{{PLAN_USAGE}}`, `{{IMPLEMENTATION_USAGE_CHIP}}`, `{{IMPLEMENTATION_USAGE}}` appear in `templates/feature-tracker.html`, each in its own panel), `test_script_token_map_matches_the_template` (the token names in `scripts/usage_report.py`'s `TRACKER_TOKENS`, read as text, are exactly those eight), and `test_bug_tracker_render_blanks_twenty_tokens` (`skills/bug-tracker-render/SKILL.md` Step 3 names all twenty feature-panel tokens and no longer says "twelve"). Expected initial failure: `AssertionError: {{BRAINSTORMING_USAGE_CHIP}} not in templates/feature-tracker.html`.
2. Run `uv run pytest tests/test_static.py -k UsageReport` — confirm it fails with that assertion.
3. Implement, **template first**: in `templates/feature-tracker.html` add `{{<STAGE>_USAGE_CHIP}}` immediately after each panel's `<p class="section-timestamp">…</p>` element and `{{<STAGE>_USAGE}}` immediately after that panel's `<div class="bullets">…</div>`, for all four panels; add a `.chip.usage` rule beside the existing `.section-timestamp` rule (which is already `display: inline-block`, so a following inline `<span>` sits beside it) and a `table.usage` rule mirroring the existing `.prose table` / `.prose th` / `.prose td` rules, since the fragment sits outside `.prose`; extend the template's opening documentation comment with the eight token names. **Then** in `skills/bug-tracker-render/SKILL.md` Step 3, change "twelve feature-panel tokens" to "twenty" and add the eight names to the list. Doing it in that order keeps `test_skill_tokens_exist_in_templates` green throughout the stage.
4. Run `uv run pytest tests/test_static.py -k UsageReport` — confirm pass. Run `uv run pytest` — confirm no regressions, in particular the pre-existing `test_skill_tokens_exist_in_templates`.

**Definition of done:**
- All eight tokens present in the template, each in its correct panel, with CSS for both the chip and the table.
- `bug-tracker-render` Step 3 lists twenty tokens.
- `uv run pytest` green.

**Risks specific to this stage:** From this commit until Stage 7 lands, a **newly seeded** tracker carries eight literal `{{…}}` tokens with nothing yet substituting them, so a feature started during that window renders them visibly. The window is three commits, it does not affect trackers seeded before this stage (design §5 *Compatibility*), and the first `usage-report report` on any affected feature repairs it, because the skill blanks literal tokens as well as filling its own. Recorded rather than mitigated: reordering cannot remove the window, since a token must exist before the skill that names it (`test_skill_tokens_exist_in_templates`).

### Stage 5 — The `usage-report` skill

**Goal:** `skills/usage-report/SKILL.md` exists as an internal helper that runs C1 and relays its output, holding no schema knowledge of its own.
**Design references:** §3 R13; §5 *Architecture / components* (C2), §5 *Interfaces*, §5 *Failure and edge cases*, §5 *Not modified: `feature-list`*.
**Touches:**
- `skills/usage-report/SKILL.md` (create)
- `tests/test_static.py` (modify — extend `TestUsageReportLifecycle`)

**Steps (TDD):**
1. Write test: extend `TestUsageReportLifecycle` with `test_usage_report_is_internal_only` (frontmatter carries `user-invocable: false` and not `disable-model-invocation: true`), `test_usage_report_owns_the_usage_tokens` (the eight tokens appear in `skills/usage-report/SKILL.md` and in no other `SKILL.md` — sole ownership), `test_usage_chip_is_never_a_timestamp_chip` (the skill states the chip must never contain `Updated` followed by a date, so `feature-list`'s `last_activity` parsing at `skills/feature-list/SKILL.md:89-91` is unaffected), and `test_usage_report_never_calls_feature_resolve` (it takes its pathing as input; `feature-resolve` appears only in a "never calls" sentence). Expected initial failure: `FileNotFoundError: … skills/usage-report/SKILL.md`.
2. Run `uv run pytest tests/test_static.py -k UsageReport` — confirm it fails with that error.
3. Implement `skills/usage-report/SKILL.md`: frontmatter `user-invocable: false`, model-invocable, `allowed-tools: Read, Bash(python3 *), Bash(test *), Bash(find *), Bash(date *), Bash(pwd), Bash(printf *)` — deliberately no `Edit`, because the script owns the tracker write. Body: parse `start <slug>` / `report <slug>[, tracker_file=…][, feature_version=…][, outcome=…][, evals_included=…]`; locate `scripts/usage_report.py` relative to the skill's announced base directory first (`<base>/../../scripts/usage_report.py`), falling back to `find ~ -path "*dev-skills*/scripts/usage_report.py"` — the same two-step technique, including the deliberate `*dev-skills*` form, that `feature-resolve` Step 6 uses for the tracker template, and necessary because `CLAUDE_PLUGIN_ROOT` is not set in the session environment (design §4); run it; relay stdout verbatim to chat; carry the inline-execution guard (**do not end your turn** — carry on with the caller's next step); enumerate the skip lines from design §5's failure table; and state the `feature-list` chip constraint plus the "never calls `feature-resolve`, never calls `lessons-capture`" scope notes.
4. Run `uv run pytest tests/test_static.py -k UsageReport` — confirm pass. Run `uv run pytest` — confirm no regressions (`test_frontmatter_contract` and `test_skill_tokens_exist_in_templates` both now see the new skill).

**Definition of done:**
- The skill passes `test_frontmatter_contract` and every token it names exists in the template.
- It contains no transcript field names — all schema knowledge stays in C1.
- `uv run pytest` green.

**Risks specific to this stage:** None.

### Stage 6 — Start call sites in the four chain skills

**Goal:** Each chain skill opens its run by starting the usage window, mirrored across all four exactly as the `set-herdr-label` block beside it.
**Design references:** §3 R1; §5 *Architecture / components* (C3), §5 *Control flow* (**Start**), §5 *Testing strategy*.
**Touches:**
- `skills/feature-storm/SKILL.md`, `skills/feature-design/SKILL.md`, `skills/feature-plan/SKILL.md`, `skills/feature-implement/SKILL.md` (modify — Step 1 in each)
- `tests/test_static.py` (modify — extend `TestUsageReportLifecycle`)

**Steps (TDD):**
1. Write test: extend `TestUsageReportLifecycle` with `test_each_skill_starts_usage_with_its_own_slug` (a `**Start the usage window.**` block naming that skill's own slug exists in each of the four), `test_start_lives_in_step_1_not_step_0` (reusing `TestHerdrLabelLifecycle`'s `step_span` technique — a marker written inside the Step 0 gate would outlive a declined run), and `test_start_blocks_are_mirrored` (the four blocks are identical modulo the slug). Expected initial failure: `AssertionError: feature-storm: no usage-start block`.
2. Run `uv run pytest tests/test_static.py -k UsageReport` — confirm it fails with that assertion.
3. Implement: add an identical `**Start the usage window.**` block to Step 1 of each of the four skills, as a whole new paragraph immediately after the existing `**Label the herdr pane.**` block — invoke `usage-report` via the `Skill` tool with the argument `start <slug>`, note that it runs inline and is a silent no-op when `CLAUDE_CODE_SESSION_ID` is unset, carry the **do not end your turn** guard, and state the Step 1-not-Step 0 rationale in the same words the label block uses. No frontmatter change is needed — all four already grant the `Skill` tool.
4. Run `uv run pytest tests/test_static.py -k UsageReport` — confirm pass. Run `uv run pytest` — confirm no regressions, especially `TestHerdrLabelLifecycle`, whose `step_span` and mirrored-block assertions run over the same Step 1 text.

**Definition of done:**
- All four skills carry the start block, in Step 1, mirrored verbatim modulo slug.
- `TestHerdrLabelLifecycle` still passes unchanged.
- `uv run pytest` green.

**Risks specific to this stage:** Two intermediate-state notes. (a) Between this commit and Stage 7, every chain run writes a start marker that nothing consumes; this is bounded and self-correcting — markers are keyed on session **and** slug and a later `start` overwrites, exactly the stale-marker case design §5 *Data model* already sanctions. (b) The new block sits adjacent to the herdr label block whose verbatim mirroring is separately asserted, so add it as a whole paragraph and never reflow the label block's line.

### Stage 7 — Report call sites, placement asymmetry, and early-exit catch-alls

**Goal:** Each chain skill closes its run by reporting — the three chaining skills **before** their offer, `feature-implement` **after** its eval relay — with every early exit covered.
**Design references:** §3 R2, R11, R16; §5 *Control flow* (**Report**, the placement table, **Early exits**); §7 (the "tidying" risk); §9 *Verification*.
**Touches:**
- `skills/feature-storm/SKILL.md` (Step 9 + *Constraints*), `skills/feature-design/SKILL.md` (Step 11 + *Constraints*), `skills/feature-plan/SKILL.md` (Step 11, Step 2's `BLOCKED:` relay, + *Constraints*), `skills/feature-implement/SKILL.md` (Step 11, Step 3 sub-point 9, Step 6, + *Constraints*) (modify)
- `tests/test_static.py` (modify — extend `TestUsageReportLifecycle`)

**Category:** **Hybrid** — full TDD for the static assertions in steps 1–4 and 6, plus an *integration-verified remainder* (step 5) for what no host test can reach: that the script runs against a real multi-megabyte transcript within a few seconds, that a real log line lands, and that the chip renders beside the timestamp chip in a browser.

**Steps (TDD):**
1. Write test: extend `TestUsageReportLifecycle` with `test_each_skill_reports_with_its_own_slug` (a `**Report the run usage.**` block naming that skill's slug in its final step), `test_report_precedes_the_offer_for_the_three_chaining_skills` (in `feature-storm`, `feature-design` and `feature-plan` the report block's offset precedes the final step's first `AskUserQuestion`), `test_implement_reports_after_the_eval_relay` (in `feature-implement` the report block's offset is *after* Step 11's `AskUserQuestion` and after the eval-relay sentence — the one deliberate asymmetry, which this test exists to defend), `test_reporting_before_any_stop_is_a_constraint` (each of the four carries a `**Report the run usage before you stop.**` catch-all in its *Constraints* section), and `test_early_exits_report_halted` (`feature-plan` Step 2's `BLOCKED:` relay and `feature-implement` Step 3 sub-point 9 and Step 6 each name `outcome=halted`). Expected initial failure: `AssertionError: feature-storm: no usage-report block in its final step`.
2. Run `uv run pytest tests/test_static.py -k UsageReport` — confirm it fails with that assertion.
3. Implement the three chaining skills: add `**Report the run usage.**` to `feature-storm` Step 9, `feature-design` Step 11 and `feature-plan` Step 11, placed **before** the `AskUserQuestion` offer and beside the existing `**Clear the herdr pane label.**` block, invoking `usage-report` with `report <slug>, tracker_file=<tracker_file>, feature_version=<N>` taken from that skill's own resolver block. State the placement rationale inline in each: on acceptance the skill hands over through the `Skill` tool and never returns to the step. Add the catch-all constraint to each *Constraints* section, and `outcome=halted` to `feature-plan` Step 2's `BLOCKED:` relay.
4. Implement `feature-implement`: add the same block to Step 11 but placed **after** the eval results are relayed (and immediately after a decline), with its own inline rationale — its final question hands over to nothing and control returns on every branch, and the user chose to have the eval subagents inside the measured window — passing `evals_included=true` on the accepted branch and `false` on the declined one. Add `report … outcome=halted` to Step 3 sub-point 9's stopping branches and to Step 6's stop conditions, and the catch-all to its *Constraints*.
5. **Integration-verified remainder.** With the working tree at this stage, run in one shell: `python3 scripts/usage_report.py start --slug feature-plan`; then `cp features/feature-v1-usage-report/feature-v1-tracker.html /tmp/usage-check.html` and `python3 scripts/usage_report.py report --slug feature-plan --tracker /tmp/usage-check.html --feature-version 1`. Confirm: a `Run usage` markdown table on stdout with non-zero totals; exactly one new line in `"${CLAUDE_CONFIG_DIR:-$HOME/.claude}"/dev-skills/usage/runs.jsonl` that parses as JSON and carries only design §5's field set; the start marker gone; the whole `report` invocation completing in a few seconds (R16); and `/tmp/usage-check.html` opened in a browser showing the usage chip beside the timestamp chip and the usage table below the plan panel's bullets. Delete `/tmp/usage-check.html` afterwards. The tracker under `features/` is deliberately **not** the file edited — a live check must not mutate this feature's own artefact.
6. Run `uv run pytest tests/test_static.py -k UsageReport` — confirm pass. Run `uv run pytest` — confirm no regressions, especially `TestHerdrLabelLifecycle::test_clear_precedes_the_final_offer`, which measures offsets in the same final steps this stage edits.

**Definition of done:**
- All four skills report; three before their offer, `feature-implement` after its eval relay.
- All four carry the catch-all constraint; all three enumerated early exits pass `outcome=halted`.
- The integration check produced a table, exactly one well-formed log line, and a correctly rendered tracker panel.
- `uv run pytest` green.

**Risks specific to this stage:** The asymmetric placement is the single most "tidyable" part of this feature (design §7). `test_implement_reports_after_the_eval_relay` and `test_report_precedes_the_offer_for_the_three_chaining_skills` are the guard; never weaken either into a mere presence check.

### Stage 8 — Documentation

**Goal:** `CLAUDE.md`, the README and the wiki describe the new script, the new skill, the twenty-token contract and the two-consumer rule.
**Design references:** §9 *Rollout plan* (the documentation list).
**Touches:** `CLAUDE.md`, `README.md`, `../dev-skills.wiki/Skills-Reference.md`, `../dev-skills.wiki/Architecture.md`, `../dev-skills.wiki/Conventions.md` (modify, as applicable)

**Category:** **Non-TDD (config-only)** — prose only; nothing host-assertable changes, and no test in the repo reads these files' content.

**Steps:**
1. `CLAUDE.md`: add a `scripts/usage_report.py` entry to *Files* (noting it is the plugin's second piece of executable code, alongside `hooks/remote-check.sh`); add `usage-report` to the skill-group list as an internal helper; extend the `templates/feature-tracker.html` *Files* entry and the tracker-token invariant with the eight usage tokens, their single owner, and the explicit statement that the template has **two** consumers (`usage-report` and `bug-tracker-render`) so a token change is always a two-skill change; extend the *Editing workflow* mirrored-blocks note to the two `usage-report` blocks alongside the two `set-herdr-label` ones; and record the asymmetric report placement as a non-negotiable invariant.
2. `README.md`: read it first, then edit only if it enumerates skills or outputs — it currently does not, so a new section may well be wrong; do not invent one.
3. `../dev-skills.wiki/`: update `Skills-Reference.md` with the `usage-report` entry and its two call-site blocks, `Architecture.md` with the script, the skill and the tracker's two consumers, and `Conventions.md` with the usage-log location and the JSONL-vs-array rationale. Per repo convention these edits are made in the same change but publish only when the wiki repo is committed and pushed separately.
4. Verify: `uv run pytest` still green (nothing here should affect it), and `grep -c "usage-report" CLAUDE.md` returns a non-zero count.

**Definition of done:**
- `CLAUDE.md` names the script, the skill, the twenty tokens, the two consumers and the placement asymmetry.
- The three wiki pages describe the feature.
- `uv run pytest` green.

**Risks specific to this stage:** The static suite cannot see the wiki, so this stage is the only mechanism keeping it honest — do not defer it to a later change.

## Cross-cutting concerns

- **Security** — `log_entry` builds its dict from an explicit field list rather than by copying and filtering, so conversation content cannot leak by omission (Stage 2, asserted with a secret-shaped fixture string). `slug` is validated against `^[a-z][a-z0-9-]{0,63}$` before it reaches a filename (Stage 3), in the same stage as the first write, so no ordering window exists where a path is built from an unvalidated value. The module is stdlib-only, makes no network calls and spawns no subprocesses — which is why `repo_name` comes from the marker's `cwd` rather than a `git` call — and writes only under `<config-dir>/dev-skills/usage/` plus an explicitly passed `--tracker` (Stage 3). The skill's tool grant omits `Edit`, so it cannot write files at all.
- **Performance** — `iter_entries` streams line by line and `window_entries` discards non-matching entries before aggregation (Stage 1); subagent files are filtered by directory listing and mtime before parsing (Stage 3). R16 is checked concretely in Stage 7 step 5 against a real multi-megabyte transcript.
- **Observability** — the report itself is the surface. Each failure path prints exactly one `usage report skipped — <cause>` line naming its cause (Stage 3), and the log's `outcome` field separates completed from halted runs (Stages 3 and 7).
- **Compatibility / migration** — purely additive. Trackers seeded before Stage 4 contain none of the eight tokens and are a no-op for `apply_tracker`. Between Stage 4 and Stage 7 a newly seeded tracker can show literal tokens (Stage 4's risks), and between Stage 6 and Stage 7 a run can leave an unconsumed start marker (Stage 6's risks); both are bounded, cosmetic and self-correcting. Rollback is deletion — the script, the skill, the eight tokens, the CSS rules and the call-site blocks — with no persisted state to migrate.

## Verification

Once all eight stages are complete, verify against design §3's acceptance statement (§9 *Verification*): run a real chain on a throwaway feature — `/feature-storm`, then `/feature-design`, then `/feature-plan`, then `/feature-implement` — and confirm, for each of the four:

1. A markdown table titled **Run usage** printed in chat at the end of the run, with the mockup's row order and a footer line carrying tier, speed, subagent count and outcome (R6, R7).
2. Exactly one new line in `<config-dir>/dev-skills/usage/runs.jsonl` per run — four lines total — each parsing as JSON, carrying only design §5's field set, and containing no conversation text (R8, R14).
3. The corresponding tracker panel showing the usage chip beside its timestamp chip and the usage table below its bullets (R9).
4. `feature-plan`'s entry showing a non-zero `subagents` column (its planning core is a subagent), and `feature-implement`'s entry carrying an `evals_included` value matching the choice made at its eval offer.

Then re-run one stage on the same feature and confirm its tracker panel shows the **new** run's figures rather than a second table (R10); confirm a deliberately halted run logs `outcome: "halted"` (R11); and confirm `/feature-list` still reports that feature's last-activity date correctly (design §5, *Not modified: `feature-list`*).

## Risks and open issues

| Risk | Mitigation |
| --- | --- |
| Synthetic fixtures can stay green while the live transcript schema drifts, silently zeroing every figure. | Fixtures are copied field-for-field from a live transcript in Stage 1, missing fields default to 0 rather than raising, and Stage 7 step 5 exercises the real transcript before the feature is called done. |
| Between Stage 4 and Stage 7 a newly seeded tracker renders eight literal `{{…}}` tokens; between Stage 6 and Stage 7 a run leaves an unconsumed start marker. | Both bounded and self-correcting: the tokens are repaired by the first report on that feature, and markers are keyed on session + slug so a later `start` overwrites. Neither is removable by reordering — a token must exist before the skill that names it. |
| The chip's placement and the usage table's styling are not host-testable — a wrong selector renders badly without failing a test. | Stage 7 step 5 opens a rendered tracker copy in a browser as an explicit, named verification. |
| `python3` on `PATH` is the system interpreter, not the project venv (3.14 vs 3.13 on the author's machine), so a third-party import would pass under pytest and fail in production. | The module is stdlib-only by construction (Stage 1 DoD), and Stage 7 step 5 runs it through the system `python3`, not through `uv`. |
| Stages 4–7 each edit `tests/test_static.py`, and Stages 6–7 edit text adjacent to the separately-asserted `set-herdr-label` blocks; a reflow breaks `TestHerdrLabelLifecycle`'s exact-match tests. | Every stage's final step runs the whole suite, not just its own `-k` selection, and the stage steps require adding whole paragraphs rather than rewriting neighbouring lines. |
| Design §4 states each request appears "roughly four times"; the live transcript shows 1–5 (mode 2). | Dedup is by `requestId` and is unaffected; recorded in Stage 1's risks so no test asserts an exact snapshot count. |

## Planning decisions taken

1. **`pythonpath = ["."]` is added to `[tool.pytest.ini_options]` in Stage 1.** A verified prerequisite, not a preference: `uv run pytest` puts only `<repo>/tests` on `sys.path`, so `import scripts.usage_report` raises `ModuleNotFoundError: No module named 'scripts'` without it. No `scripts/__init__.py` is added — namespace-package import resolves once the root is on the path.
2. **The script, not the skill, applies the tracker edits.** Design §5 *Architecture* (C2) says the skill "applies the tracker edits C1 emitted" while §5 *Interfaces* says `report` "applies the tracker edits itself when `--tracker` is given"; taking the *Interfaces* reading, because requirement 10 needs a deterministic anchored replacement on re-runs, which is unit-testable in Python and fragile as an LLM `Edit`. `apply_tracker(...)` and a `TRACKER_TOKENS` constant therefore join C1's function set, and the skill's `allowed-tools` deliberately omits `Edit` so the split is structurally enforced. The external CLI contract is unchanged either way.
3. **`main()` resolves `<config-dir>` as `$CLAUDE_CONFIG_DIR`, falling back to `~/.claude`.** Verified: on the author's machine the config directory is an iCloud path, so hardcoding `~/.claude` (the `lessons-capture` convention) would find no transcript and write the log in the wrong place.
4. **Timestamps are parsed through a tolerant `_parse_ts` that maps a trailing `Z` to `+00:00`.** The repo declares `requires-python = ">=3.10"` and 3.10's `datetime.fromisoformat` rejects the `2026-08-21T14:18:57.924Z` form the transcript actually uses.
5. **`repo_name` is the basename of the start marker's `cwd`, not a `git` call.** Design §5 *Security* forbids subprocess execution beyond the script itself, and the marker already records `cwd` — otherwise an unused field.
6. **Stage order follows design §9, for a reason §9 did not state:** the repo's existing `test_skill_tokens_exist_in_templates` asserts every `{{TOKEN}}` named in a `SKILL.md` exists in a template, so C4's tokens must land no later than C2's skill.
7. **`apply_tracker`'s unit tests run against `tests/fixtures/usage-tracker-min.html`, not the shipped template**, so Stage 3 does not depend on Stage 4; the drift that creates is closed in Stage 4 by a test pinning `TRACKER_TOKENS` against `templates/feature-tracker.html`.
8. **C5's static assertions are written per stage alongside their subject**, rather than as one class after all call sites exist (design §9 item 6). Written §9's way the suite would be red for three commits; written this way every commit is green.
9. **C1 is split across three stages and C3 across two.** §9 treats C1's pure half as one unit and suggests C3 one skill at a time; splitting C1 into core / rendering / side-effects keeps each stage reviewable in one sitting, and splitting C3 into start-blocks then report-blocks keeps every commit green, which a per-skill split would not (the four-skill static assertions would be red for three commits).
10. **`usage-report`'s `allowed-tools` is `Read, Bash(python3 *), Bash(test *), Bash(find *), Bash(date *), Bash(pwd), Bash(printf *)`** — modelled on `bug-tracker-render`'s narrow grant plus the `Bash(python3 *)` slot `evals-code-run` already carries, minus `Edit` per decision 2.
11. **The skill locates the script with `feature-resolve` Step 6's two-step technique** — the running plugin's announced base directory first, then `find ~ -path "*dev-skills*/scripts/usage_report.py"` — because `CLAUDE_PLUGIN_ROOT` is not set in the session environment (design §4) and this repo already has exactly one solved instance of that problem.
12. **Corrected the design in place (a factual grounding error, not a deviation).** §5's tracker-token table said the usage chip sits "inside the panel's existing `.chiprow`". `templates/feature-tracker.html` has **no** `.chiprow` — that wrapper exists only in the mockup. Corrected fact, now recorded in the design: the chip follows the panel's `<p class="section-timestamp">` element, which is already `display: inline-block`, and the `.chip.usage` and `table.usage` CSS rules are added in Stage 4 beside the existing `.section-timestamp` and `.prose table` rules.

## Deviations from the design

None — plan matches design v1 exactly.

## Deviations from plan

Recorded during implementation; each is a refinement within the stage's intent,
not a change of contract.

1. **Stage 3 — `apply_tracker` blanks the other six tokens to an *empty anchored
   region*, not to a bare empty string.** Design §5 *Data model* says the
   reporter "blanks any of the other six that are still literal (to the empty
   string)". Taken literally, the first stage to report would delete the other
   three stages' tokens outright, and those stages could never fill them when
   they later ran — the tracker would only ever show one stage's usage. The
   implementation therefore replaces a still-literal foreign token with
   `<!-- usage:TOKEN --><!-- /usage:TOKEN -->`, which renders as nothing (the
   design's requirement) while leaving the anchor its owning stage fills on its
   own run. A foreign token that is *already* anchored is never touched, whether
   it holds figures or is empty. `tests/test_usage_report.py::TestApplyTracker`
   pins both halves.
2. **Stage 3 — the session id is validated alongside the slug.** Design §5
   *Security* requires `slug` to be checked against `^[a-z][a-z0-9-]{0,63}$`
   before it reaches a filename. `session_id` reaches the same filename and
   comes from the environment, so it is checked the same way against
   `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`.
3. **Stage 3 — `write_start` takes an optional trailing `cwd=` argument.** The
   design's signature is `write_start(slug, session_id, started, state_dir)` and
   the marker records `cwd`; the keyword defaults to `os.getcwd()`, so the
   documented call is unchanged and the tests get a deterministic value.
4. **Stage 2 — `RunMetrics` carries `subagent_count` and a
   `output_tokens_per_second` property beyond the design's
   `RunMetrics(main, subagents, total, timings)`.** The footer line and the log
   entry both need the subagent count, and it is derived where the subagent
   files are counted. `RunContext` is the "footer context" the plan's Stage 2
   step 3 refers to, shared by `render_markdown` and `log_entry`.
