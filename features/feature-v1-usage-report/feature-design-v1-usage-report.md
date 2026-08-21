# Usage Report — Design v1

**Status:** Draft
**Date:** 2026-08-21

## 1. Summary

Each of the four feature-chain skills (`feature-storm`, `feature-design`, `feature-plan`, `feature-implement`) currently ends without telling the user what the run cost. This feature adds a **run usage report**: elapsed time, active run time, a full token breakdown split between the main agent and its subagents, and output throughput — printed as a markdown table at the end of every chain-skill run, appended to a durable JSONL log, and mirrored into the feature tracker panel for that stage.

The numbers are derived from Claude Code's own session transcripts, which already record per-request `usage` blocks and timestamps. Nothing new is instrumented; the feature reads what the harness already writes. It is for the developer running the chain (the plugin's author and users), who currently has no way to see whether a stage cost thirty seconds or forty minutes, or whether a skill is getting more expensive as it is edited.

## 2. Goals and non-goals

**Goals**

- Report elapsed time, active run time, the complete token breakdown, request counts and output throughput at the close of each of the four chain skills.
- Attribute cost correctly when work is delegated: `feature-plan` runs its core in a subagent and `feature-implement` delegates stage chunks, so main-agent and subagent usage are counted separately and totalled.
- Persist every run to a log that survives the terminal scrollback, so per-skill cost is comparable over time.
- Surface the same figures in the feature tracker, beside the artefact the run produced.
- Never fail, block, or slow a chain-skill run because reporting went wrong.

**Non-goals**

- **Currency cost estimates.** The requirement names token fields; converting to money needs a price table that varies by model, tier and contract, and would go stale silently. Out of scope for v1.
- **Instrumenting skills outside the chain.** `bug-fix`, `bug-submit`, the eval skills and the diagram skills are explicitly not covered — the requirement names four skills.
- **Per-request or per-step detail.** The report is one aggregate per run. A request-level breakdown is a different tool.
- **Backfilling historical runs.** The log starts empty; past runs are not reconstructed, even though their transcripts exist.
- **Measuring the reporter's own cost.** The `usage-report` skill's own token consumption is inside the window it measures and is not separated out.

## 3. Requirements

Functional:

1. A `start` call records the run's start timestamp, keyed by session and skill slug, before any of the skill's substantive work.
2. A `report` call computes the window from that start timestamp to the moment of the call, and emits the report.
3. The report includes, split across `main` / `subagents` / `total` columns: `input_tokens`, `output_tokens`, `thinking_tokens`, `cache_write`, `ephemeral_1h`, `ephemeral_5m`, `cache_read`, `web_search`, `web_fetch`, and model request count.
4. The report includes `elapsed` (wall clock) and `run time` (elapsed minus time spent waiting on the user) as total-column figures.
5. The report includes `output tok/s` throughput, computed once across main and subagent requests combined.
6. The report includes a footer line carrying `service_tier`, `speed`, subagent count and run outcome.
7. Chat output is a markdown table titled `Run usage`, matching the accepted mockup.
8. Exactly one JSONL entry per run is appended to the usage log.
9. The stage's tracker panel receives the same figures as an HTML table plus a headline chip.
10. Re-running a stage replaces that stage's tracker usage content with the latest run's figures.
11. A run that halts early still reports and still logs, marked with outcome `halted`.
12. Every assistant entry is counted exactly once, despite the transcript writing four snapshots per request.

Non-functional:

13. A failure anywhere in reporting never fails, blocks or aborts the calling skill.
14. No conversation content — prompts, replies, file contents, tool arguments — is written to the log or printed. Only numeric usage, timestamps and identifiers.
15. Concurrent runs in parallel herdr sessions must not lose each other's log entries.
16. Reporting adds no more than a few seconds to a run, on transcripts of several megabytes.

## 4. Background and context

**Where the data lives.** Claude Code writes a JSONL transcript per session at `<config-dir>/projects/<encoded-cwd>/<session-id>.jsonl`. Verified properties:

- `CLAUDE_CODE_SESSION_ID` is exported into the session environment and equals the transcript's basename. `CLAUDE_PLUGIN_ROOT` is **not** set in the session environment, so plugin-relative paths must be derived from a skill's announced base directory (the technique `feature-resolve` Step 6 already uses to find the tracker template).
- Every `type: "assistant"` entry carries `timestamp`, `requestId`, `message.model` and a full `message.usage` block: `input_tokens`, `output_tokens`, `output_tokens_details.thinking_tokens`, `cache_creation_input_tokens`, `cache_creation.ephemeral_1h_input_tokens`, `cache_creation.ephemeral_5m_input_tokens`, `cache_read_input_tokens`, `server_tool_use.web_search_requests`, `server_tool_use.web_fetch_requests`, `service_tier`, `speed`.
- **Each request appears roughly four times** with identical usage and differing timestamps — streaming snapshots, not increments. Deduplication by `requestId` is mandatory; without it every figure is inflated ~4×.
- **Subagent transcripts live flat** in `<config-dir>/projects/<encoded-cwd>/<session-id>/subagents/agent-*.jsonl`, each with an `agent-*.meta.json` carrying `agentType`, `toolUseId` and `spawnDepth`. Depth-2 agents (subagents spawning subagents) exist — 84 of 271 on the author's machine — but because the directory is **flat**, a time-window scan captures every depth with no traversal.
- The transcript is **flushed live**: a marker written by one tool call is readable by the next call in the same turn. Start and report can therefore both run inside a single skill run.
- Compaction **appends**; it does not truncate. One transcript spans Aug 7 → Aug 13 across 707 lines continuously.

**Why the boundary is not inferred.** Scanning for `<command-name>/feature-storm</command-name>` is unreliable in two independent ways: skills that print skill names (`feature-list`, `lessons-learn`, both eval skills) write those strings into the transcript as ordinary tool output, and chained or model-initiated invocations emit no such tag at all — they appear as a `Skill` tool_use with `input.skill`. Hence the explicit start marker.

**Existing conventions this follows.**

- `hooks/remote-check.sh` — the plugin's only executable code today; establishes that shipping a script is acceptable, and that such code degrades silently rather than failing the session.
- `skills/lessons-capture/SKILL.md` — appends to a per-slug log under `~/.claude/dev-skills/` with a single atomic append. Establishes both the log location and the append-only pattern.
- `skills/evals-code-run/SKILL.md:111-155` — the eval log's field shape (`repo_name`, shared `timestamp`), and its corrupt-file-moved-aside handling.
- `skills/set-herdr-label/SKILL.md` — an internal helper called from Step 1 and the final step of all four chain skills, guarded by `tests/test_static.py::TestHerdrLabelLifecycle`. This feature's call sites mirror those positions exactly.
- `templates/feature-tracker.html:138-152` — design tokens; `:939-946` — the per-stage panel shape (`.section-timestamp` chip, `.bullets`, `.prose`).

**Accepted mockup:** [grouped-columns](./mockups/mockup-v1-grouped-columns.html) (accepted 2026-08-21).

## 5. Design

### Architecture / components

Five components with explicit seams. The compute lives in a Python module because the repo's test harness is already pytest (`tests/`, run via `uv run pytest`), so pure functions are unit-testable by the existing suite with no new harness; the work is JSON aggregation, which Python does natively.

**C1 — `scripts/usage_report.py`** (new). The compute engine and the only place that knows the transcript schema. Importable module plus a `main(argv)` CLI. Public functions, each independently testable with synthetic JSONL fixtures and no filesystem beyond a `tmp_path`:

| Function | Responsibility |
|---|---|
| `resolve_transcript(session_id, config_dir)` | Locate the main transcript; return `None` if absent. |
| `write_start(slug, session_id, started, state_dir)` | Serialise the start marker; return its path. |
| `read_start(slug, session_id, state_dir)` | Return the marker dict, or `None`. |
| `iter_entries(path)` | Stream parsed entries; skip malformed lines without raising. |
| `window_entries(entries, start, end)` | Filter to the run window by `timestamp`. |
| `aggregate(entries)` | Dedupe by `requestId`, sum every usage field, return a `Usage`. |
| `timings(entries)` | Return `elapsed`, `run_seconds` (excluding user waits), `request_seconds`. |
| `throughput(output_tokens, request_seconds)` | Output tokens per second, or `None` when `request_seconds` is 0. |
| `collect(transcript, subagent_dir, start, end)` | Orchestrate the above into a `RunMetrics(main, subagents, total, timings)`. |
| `render_markdown(metrics, footer)` | The chat table, as a string. |
| `render_tracker_html(metrics)` | The tracker table fragment and headline chip, as strings. |
| `log_entry(metrics, context)` | Build the log dict. |
| `append_log(entry, log_path)` | One atomic append. |

`main(argv)` is a thin dispatcher over `start` and `report`; all logic above it is pure and side-effect free except the four functions whose names say otherwise.

**C2 — `skills/usage-report/SKILL.md`** (new). Internal helper, `user-invocable: false`, model-invocable. It parses its argument string, locates C1 relative to its own announced base directory, runs it, relays stdout to chat, and applies the tracker edits C1 emitted. It holds no domain logic — the schema knowledge stays in C1, so a transcript-format change is a one-file fix.

**C3 — Call sites** in the four chain `SKILL.md`s. Two blocks each, mirroring the `set-herdr-label` blocks they sit beside.

**C4 — `templates/feature-tracker.html`** gains eight tokens, all owned by `usage-report` (§ *Data model*).

**C6 — `skills/bug-tracker-render/SKILL.md`** (modified). The tracker template is shared with the bug tracker, and this skill **enumerates the feature-panel tokens by name** to blank them (`SKILL.md:52`, "each of the twelve feature-panel tokens → empty string"). Adding eight tokens makes that twenty; without the change, `bugs/bugs-tracker.html` renders literal `{{DESIGN_USAGE}}` text on every bug-tracker regeneration. This is the second site of the same mechanism and is easy to miss because nothing in the bug workflow refers to usage.

**C5 — `tests/test_static.py::TestUsageReportLifecycle`** plus `tests/test_usage_report.py` for C1's unit tests.

**Not modified: `feature-list`.** It reads the tracker to derive `last_activity`, matching the chip shape `Updated <YYYY-MM-DD HH:MM UTC>` and ignoring `Awaiting /feature-<stage>` (`skills/feature-list/SKILL.md:89-91`). The usage chip sits in the same `.chiprow` and would corrupt that reading if it looked like a timestamp chip. It does not — its content is `8m 08s · 25,924 out · 76.0 tok/s`. **Constraint: the usage chip must never contain the literal `Updated` followed by a date**, or `feature-list` will report the wrong last-activity date for every feature. Asserted by `TestUsageReportLifecycle`.

### Data model

**Start marker** — `<config-dir>/dev-skills/usage/state/<session-id>-<slug>.json`:

```json
{"slug": "feature-design", "session_id": "e524cfb5-…", "started": "2026-08-21T13:05:41Z", "cwd": "/Users/cagri/Git/dev-skills"}
```

Keyed on session **and** slug, so parallel herdr sessions in one repo never collide and a chain hand-over (storm → design) keeps two independent markers. A second `start` for the same key overwrites; an abandoned run leaves a stale marker that the next run replaces. The marker is deleted by its own `report`.

**Log** — `<config-dir>/dev-skills/usage/runs.jsonl`, one JSON object per line:

```json
{"repo_name":"dev-skills","timestamp":"2026-08-21T13:14:09Z","slug":"feature-design",
 "feature_version":1,"outcome":"completed","evals_included":false,
 "elapsed_seconds":488,"run_seconds":332,"request_seconds":286,"output_tokens_per_second":76.0,
 "subagent_count":3,"service_tier":"standard","speed":"standard","models":["claude-opus-5"],
 "requests":{"main":26,"subagents":14,"total":40},
 "output_tokens":{"main":21723,"subagents":4201,"total":25924},
 "thinking_tokens":{"main":9379,"subagents":1004,"total":10383},
 "input_tokens":{"main":52,"subagents":0,"total":52},
 "cache_write":{"main":139500,"subagents":38220,"total":177720},
 "ephemeral_1h":{"main":139500,"subagents":38220,"total":177720},
 "ephemeral_5m":{"main":0,"subagents":0,"total":0},
 "cache_read":{"main":9109158,"subagents":652592,"total":9761750},
 "web_search":{"main":0,"subagents":0,"total":0},
 "web_fetch":{"main":0,"subagents":0,"total":0}}
```

`evals_included` exists because `feature-implement`'s window deliberately contains its eval subagents (§ *Control flow*); without the flag, implement runs would be silently non-comparable depending on whether the user accepted the eval offer. `feature_version` is `null` for a run with no resolved version.

JSONL rather than a JSON array is a deliberate departure from the eval logs: an array needs read-modify-write, and two herdr sessions finishing a stage together can silently drop one entry. A single `O_APPEND` write of one line is atomic on POSIX below `PIPE_BUF` (4096 bytes), which the entry above satisfies at roughly 800 bytes.

**Tracker tokens** — two per stage, all substituted only by `usage-report`:

| Token | Content |
|---|---|
| `{{BRAINSTORMING_USAGE_CHIP}}` / `{{DESIGN_…}}` / `{{PLAN_…}}` / `{{IMPLEMENTATION_…}}` | `<span class="chip usage">8m 08s · 25,924 out · 76.0 tok/s</span>`, immediately after the panel's `<p class="section-timestamp">` element. (Corrected during planning: the template has **no** `.chiprow` — that wrapper exists only in the mockup. `.section-timestamp` is already `display: inline-block`, so a following inline `<span>` sits beside it; the `.chip.usage` and `table.usage` CSS rules are added alongside `.section-timestamp` / `.prose table` in the same change that adds the tokens.) |
| `{{BRAINSTORMING_USAGE}}` / `{{DESIGN_USAGE}}` / `{{PLAN_USAGE}}` / `{{IMPLEMENTATION_USAGE}}` | The `<table class="usage">` fragment, after the panel's `.bullets`. |

`usage-report` is **self-healing** on the tracker: on every run it fills its own stage's two tokens and blanks any of the other six that are still literal (to the empty string, not a "pending" placeholder — a stage that ran before this feature shipped simply has no usage to show). This keeps the four chain skills out of the usage tokens entirely, so no coordination or ordering dependency exists between their tracker steps and this one.

Requirement 10 (re-runs replace) follows from this: on a re-run the tokens are no longer literal, so `usage-report` replaces the previous run's rendered content between the same anchors rather than skipping. This is the one deliberate exception to the plugin's defensive substitute-only-if-literal rule, and it is safe because these eight tokens have exactly one owner.

### Interfaces

**Skill (C2), invoked via the `Skill` tool:**

```
usage-report start <slug>
usage-report report <slug>[, tracker_file=<path>][, feature_version=<N>][, outcome=<completed|halted>][, evals_included=<true|false>]
```

`outcome` defaults to `completed`, `evals_included` to `false`. `tracker_file` and `feature_version` come from the caller's `feature-resolve` block; when `tracker_file` is absent the tracker step is skipped and the chat table and log still happen. The skill takes its pathing as input and **never calls `feature-resolve`** — the `feature-mockup` precedent.

**Script (C1):**

```
usage_report.py start  --slug <slug>
usage_report.py report --slug <slug> [--tracker <path>] [--feature-version N]
                       [--outcome completed|halted] [--evals-included]
```

`report` writes the markdown table to stdout, applies the tracker edits itself when `--tracker` is given, appends the log line, and exits 0. Any recoverable problem prints a single diagnostic line to stdout prefixed `usage report skipped —` and still exits 0, so the caller can relay it without branching on exit codes.

### Control flow

**Start**, in Step 1 of each chain skill, immediately after the `set-herdr-label` block:

1. Read `CLAUDE_CODE_SESSION_ID`; if unset, do nothing at all.
2. Write the start marker with the current UTC timestamp.

Step 1 rather than Step 0 for the same reason the label sits there: Step 0 is the confirmation gate, and a declined run must not leave a marker with no report to clear it.

**Report**, at the end of each chain skill:

1. Read the start marker; if absent, print one line saying so and stop.
2. Set `end` to now. Scan the main transcript and every file in the session's `subagents/` directory, keeping entries whose `timestamp` falls in `[start, end]`.
3. Dedupe assistant entries by `requestId`; aggregate main and subagent columns separately.
4. Compute timings and throughput.
5. Print the markdown table; append the log line; apply the tracker edits.
6. Delete the start marker.

**Placement of the report call is deliberately asymmetric**, and this is the part most likely to be "tidied" into uniformity by a later edit:

| Skill | Report fires | Why |
|---|---|---|
| `feature-storm` (Step 9), `feature-design` (Step 11), `feature-plan` (Step 11) | **Before** the chain-offer `AskUserQuestion` | On acceptance these hand over to the next skill through the `Skill` tool and never return to the step. A trailing call would silently never run — the same reasoning that puts the herdr-label clear before the offer. |
| `feature-implement` (Step 11) | **After** the eval results are relayed (or immediately after a decline) | Its final question hands over to nothing; control returns on every branch. The user chose to have the eval subagents inside the measured window, which is only possible from this position. |

**Early exits** must report too, mirroring the label-clear catch-all: `feature-plan` Step 2's `BLOCKED:` relay, `feature-implement` Step 3's red-baseline halt and Step 6's stop conditions, each with `outcome=halted`. A catch-all constraint in all four skills covers halts the enumerated exits miss.

**Subagents never call either mode.** The window belongs to the main agent for the whole run, exactly as the herdr label does; `feature-plan`'s planning core and `feature-implement`'s stage units are inside the window and are counted by the scan, not by calling in.

### Failure and edge cases

Every case below prints at most one line and returns success — requirement 13 is absolute.

| Case | Behaviour |
|---|---|
| `CLAUDE_CODE_SESSION_ID` unset | Silent no-op on `start`; on `report`, one line and no log entry. |
| Script missing or not executable | One line: `usage report skipped — script not found`. The run continues. |
| `python3` unavailable | Same one-line skip. No fallback path — a partial reimplementation in the skill would defeat the determinism this design is for. |
| Start marker absent at `report` | One line naming the reason (cleared session, resumed run, `start` never fired). **Never** guess a start time — a fabricated window produces a plausible wrong number, which is worse than none. |
| Transcript file absent | One-line skip. |
| Malformed JSONL line | Skipped individually; the run is still reported. |
| `subagents/` directory absent | Subagent columns are zero; not an error. |
| Log write fails | Table still prints; one line notes the log failure. |
| Log line would exceed 4096 bytes | Entry is written anyway but the atomicity guarantee is void; a unit test asserts the serialised entry stays under 2048 bytes so this cannot arise in practice. |
| `tracker_file` missing or unreadable | Tracker step skipped; chat and log unaffected. |
| Zero requests in window | Table prints with zeros; throughput renders `—` rather than dividing by zero. |
| Clock moves backwards mid-run | Negative durations are clamped to 0. |

### Security

- **The transcript contains the full conversation.** The script parses it but must extract only numeric usage fields, timestamps, `requestId`, `model`, `service_tier` and `speed`. No message content, tool arguments, file contents or paths from the conversation may reach the log or stdout. This is enforced by construction — `log_entry` builds its dict from an explicit field list rather than by copying and filtering — and by a unit test that feeds a fixture containing a secret-shaped string and asserts it appears in neither output.
- The only paths written are under `<config-dir>/dev-skills/usage/` and the caller-supplied `tracker_file`. No network access, no credentials, no subprocess execution beyond the script itself.
- `slug` is used in a filename; it is validated against `^[a-z][a-z0-9-]{0,63}$` before use, so a hostile argument cannot traverse out of the state directory.
- The log is world-readable only insofar as the user's config directory is; it holds no secrets by the rule above.

### Performance

Transcripts reach a few megabytes (2.4 MB observed). `iter_entries` streams line by line rather than loading the file, and the window filter discards non-matching entries before aggregation. Subagent files are filtered by directory listing and mtime before parsing. Expected cost is well under a second for a typical run; requirement 16 is met with margin.

### Observability

The report itself is the observability surface. Beyond it: the one-line skip diagnostics name their cause, and the log's `outcome` field distinguishes completed from halted runs so averages can exclude the latter.

### Compatibility / migration

Purely additive. Trackers created before this feature contain none of the eight tokens; `usage-report`'s substitution is a no-op on them and the panels render unchanged. No migration, no flag, no rollback data. Removing the feature means deleting the script, the skill, the eight tokens and the call-site blocks.

### Testing strategy

**`tests/test_usage_report.py`** (new, pytest, free/static — no `llm` marker), one test group per C1 function, driven by synthetic JSONL fixtures under `tests/fixtures/`:

- `aggregate` — four snapshots of one `requestId` count once (requirement 12); missing optional fields default to 0.
- `timings` — a >30s gap ending at a `user` entry is excluded from `run_seconds` but not `elapsed`; backwards clock clamps to 0.
- `throughput` — returns `None` at zero request time.
- `window_entries` — boundary timestamps inclusive; entries outside excluded.
- `collect` — a fixture with a `subagents/` directory splits main and subagent columns correctly, including a depth-2 agent file.
- `iter_entries` — a malformed line is skipped, surrounding lines still parse.
- `render_markdown` / `render_tracker_html` — golden-string comparison against the accepted mockup's row order and labels.
- `log_entry` — exact field set; serialised length under 2048 bytes; a secret-shaped fixture string appears nowhere in the entry or the rendered table.
- `append_log` — two interleaved appends both survive; a pre-existing file is not truncated.
- `write_start` / `read_start` — round-trip; absent marker returns `None`; an invalid slug is rejected.

**`tests/test_static.py::TestUsageReportLifecycle`** (new), modelled on `TestHerdrLabelLifecycle`:

- All four chain skills call `start` with their own slug in Step 1.
- All four call `report` with their own slug in their final step.
- The three chaining skills place `report` **before** their chain-offer question; `feature-implement` places it **after** the eval relay.
- Each skill carries the catch-all "report before you stop" constraint.
- The eight tracker tokens exist in the template, and are filled only by `usage-report`.
- `bug-tracker-render` blanks all twenty feature-panel tokens, not twelve (C6).
- The rendered usage chip does not contain `Updated` followed by a date, so `feature-list`'s `last_activity` parsing is unaffected.
- `usage-report` frontmatter is `user-invocable: false`.

Acceptance (requirement-level) is verified by running one real chain stage and confirming a table in chat, a line in `runs.jsonl`, and a populated tracker panel.

## 6. Alternatives considered

- **Infer the run boundary from `<command-name>` tags** — rejected. Skills that print skill names pollute the transcript with false matches (three in this very session, all false), and chained or model-initiated runs emit no tag at all.
- **Attribute subagents by walking `meta.json` `toolUseId`** — rejected as unnecessary. It is exact, but needs a transitive fixed-point walk for depth-2 agents and a fallback for the one observed meta lacking `toolUseId`; because the `subagents/` directory is flat, a time-window scan achieves the same coverage in one pass.
- **Line offsets instead of timestamps as the window primitive** — rejected. An offset into the main transcript says nothing about the separate subagent files, which is where most of `feature-plan`'s cost lives.
- **JSON array log matching `~/.claude/evals/*.json`** — rejected for concurrency. Read-modify-write can drop an entry when two herdr sessions finish together; append-only JSONL cannot. Consistency with the eval logs was the cost.
- **Script only, no skill** — considered and rejected by the user. It would have avoided ~1.5–2k tokens of `SKILL.md` load on each of eight calls per chain, but loses the documented single entry point and a home for future judgement.
- **Bash rather than Python for C1** — rejected. The repo's harness is pytest, so a Python module is unit-testable by the existing suite; a bash script would need a new one. `hooks/remote-check.sh` is bash because a hook must run with no interpreter assumption; this script is invoked by a skill that can require `python3`, which `evals-code-run` already does.
- **Throughput as `(output + cache_read) / active`** — rejected against measurement. On a real run `cache_read` is 420× `output`, so the figure reports context re-reading, not generation: 27,538 versus 76.0 tok/s for the recommended formula.
- **Throughput as `output / active`** — rejected as the primary figure. Its denominator includes tool execution and file I/O (14% of active time on the measured run), so it varies with run shape rather than model speed.
- **Per-column throughput** — rejected. Subagents run in parallel, so their summed request time exceeds wall clock and a per-column figure would show a slowdown that never occurred.
- **Monospace block rather than a markdown table in chat** — rejected by the user at the mockup stage; chat renders markdown tables natively, so the table is both better aligned and better structured.
- **`headline-detail` and `compact-ledger` mockups** — offered and not chosen. `compact-ledger` reproduced the pasted spec exactly but summarised the subagent share into one line; `headline-detail` led with a single summary line but made per-metric subagent shares harder to compare. Both retained under `mockups/`.
- **A `Stop` hook instead of skill call sites** — rejected. Hooks fire every turn with no notion of a skill ending, and would need the same boundary inference already rejected above.

## 7. Risks and issues

| Risk | Likelihood / impact | Mitigation |
|---|---|---|
| The transcript schema is undocumented and may change in a Claude Code upgrade, silently zeroing every figure. | Medium / medium | All schema knowledge is confined to C1. Fixtures pin the exact shape depended on, so a change fails a test rather than reporting zeros. Missing fields default to 0 rather than raising. |
| Throughput's denominator includes prefill and network, so it is a response rate rather than pure decode speed. | High / low | Named `output_tokens_per_second` and documented as such in the skill and design. It is stable and comparable, which is what it is for. |
| `feature-implement`'s window includes eval subagents, making runs non-comparable with eval-declined runs. | High / medium | `evals_included` recorded on every entry so consumers can filter. Accepted deliberately by the user. |
| The eight tracker tokens are the largest single addition to the template's token contract, and a rename would break the reporter silently. | Low / medium | Single ownership, plus a static test asserting the tokens exist in the template and are filled only by `usage-report`. |
| The template has a second consumer — `bug-tracker-render` blanks feature tokens by name — so adding tokens without updating it leaks literal `{{DESIGN_USAGE}}` into every bug tracker. | Was near-certain / medium | Caught in review and made explicit as C6; covered by a static test asserting twenty blanked tokens. The general lesson is recorded in §9's documentation list: the template has two consumers, not one. |
| The asymmetric report placement (before the offer for three skills, after for `feature-implement`) reads as an inconsistency and invites a "tidying" edit that breaks the chaining skills. | Medium / high | The rationale is stated in this design, in each skill's own block, and asserted by `TestUsageReportLifecycle`, which fails if any of the three moves after its offer. |
| The report is itself inside the window it measures, so figures are marginally self-inflating and the final assistant message is never counted. | High / negligible | Documented as a known bound. Both effects are around one message. |
| `python3` absent on a user's machine leaves the feature permanently silent. | Low / low | One-line skip; the chain is unaffected. `evals-code-run` already carries the same dependency. |

## 8. Open questions

None — all decisions closed.

## 9. Rollout plan

Additive and unflagged; there is no partial state to guard. The natural implementation order, which `/feature-plan` should preserve, is:

1. C1's pure functions with their unit tests — everything else depends on the schema being right, and this is the only part that can be wrong invisibly.
2. C1's CLI and side-effecting functions (state, log, tracker), with the atomicity and no-content-leak tests.
3. C4's eight template tokens **and C6's `bug-tracker-render` update in the same stage** — the template's two consumers must never be out of step, or the next `/bug-submit` renders literal tokens.
4. C2's skill definition, wired to C1.
5. C3's call sites, one skill at a time, `feature-storm` first — it is the shortest and its final step is the simplest of the four.
6. C5's static lifecycle test, once all four call sites exist.

Verification is a real chain run: `/feature-storm` through `/feature-implement` on a throwaway feature, confirming four tables in chat, four lines in `runs.jsonl`, and four populated tracker panels.

Rollback is deletion — no persisted state outside `<config-dir>/dev-skills/usage/` and the tracker tokens, and both are inert if the feature is removed.

Documentation to update in the same change: `CLAUDE.md` — a new `scripts/` entry in *Files*, `usage-report` in the skill-group list, the tracker token-ownership note (including that the template has **two** consumers, `usage-report` and `bug-tracker-render`, so a token change is always a two-skill change), and the mirrored-blocks note in *Editing workflow* extended to the two `usage-report` blocks — plus the README if it enumerates skills, and the wiki's skills-reference and architecture pages.
