---
name: usage-report
description: Internal helper invoked only by other skills in this plugin (the four feature-chain skills) to open and close a run's usage window. `start <slug>` records the moment a run began; `report <slug>` measures the window from that marker to now and emits what the run cost — a `Run usage` markdown table in chat (elapsed, run time, the full token breakdown split main / subagents / total, request counts and output throughput), one appended line in the durable usage log, and the same figures in the stage's tracker panel. All of the work is done by the plugin's `scripts/usage_report.py`, which owns every piece of transcript knowledge; this skill locates that script, runs it, and relays its output verbatim. Any problem degrades to a single `usage report skipped — …` line: reporting never fails, blocks or aborts the calling skill. Takes its pathing as input rather than resolving it. Not user-invocable.
user-invocable: false
allowed-tools: Read, Bash(python3 *), Bash(test *), Bash(find *), Bash(date *), Bash(pwd), Bash(printf *)
---

# usage-report — what the run cost

Invoked as a sub-step of another skill in this plugin (currently `feature-storm`, `feature-design`, `feature-plan` and `feature-implement`), twice per run: once in Step 1 to open the measurement window, once in the final step to close it and report.

**You are running inline, inside the calling turn.** The `Skill` tool loads these instructions into the same context that was already working — nothing is delegated, and nothing "returns" to a waiting caller. This skill is a side effect on the way past, not a destination.

**You hold no domain logic.** Everything about how a run is measured — which files carry the numbers, how requests are deduplicated, how the window is applied, how the table is laid out — lives in `scripts/usage_report.py`. This skill's whole job is to find that script, hand it the right arguments, and put its output on the screen. Keep it that way: a change in what the harness writes should be a one-file fix, and it stops being one the moment this file starts knowing things.

## Input

One argument string, in one of two forms:

```
start <slug>
report <slug>[, tracker_file=<path>][, feature_version=<N>][, outcome=<completed|halted>][, evals_included=<true|false>]
```

- `<slug>` is the **calling skill's own slug** — `feature-storm`, `feature-design`, `feature-plan` or `feature-implement`. It keys the start marker together with the session id, so parallel sessions and a storm → design hand-over never collide.
- `tracker_file` and `feature_version` come from the calling skill's own `feature-resolve` resolution block, which it already has in context; this skill never calls the resolver itself. When `tracker_file` is absent the tracker step is simply skipped — the chat table and the log entry still happen.
- `outcome` defaults to `completed`. A run that halts early passes `outcome=halted`, so averages can exclude it later.
- `evals_included` defaults to `false`. Only `feature-implement` passes `true`, and only when the user accepted its eval offer, because those subagents run inside the measured window.

**Never ask the user anything.** Every value comes from the caller or has a default. If the argument string is malformed, run nothing and print one `usage report skipped — …` line saying so.

## Step 1 — Locate the script

The script ships with this plugin at `scripts/usage_report.py`. Find it the same two-step way `bug-tracker-render` finds the tracker template:

```bash
find ~ -path "*dev-skills*/scripts/usage_report.py" 2>/dev/null
```

- **Try the running plugin's own copy first** — this skill's base directory was announced when it was invoked (`…/dev-skills/<version>/skills/usage-report`), so the script sits two levels up at `<base>/../../scripts/usage_report.py`. If that file exists, use it: it is by definition the script matching the running plugin version, and no search is needed.
- Otherwise run the `find` above. The `*dev-skills*` form is deliberate — an installed plugin lives at `…/plugins/cache/<marketplace>/dev-skills/<version>/scripts/`, and the narrower `*/dev-skills/scripts/…` pattern silently misses it, matching only a working clone.
- Exactly one match → use it.
- Multiple matches → prefer one under a `plugins/cache/` path at the **highest** version over a working clone. Don't key this on `~/.claude/`: a profile directory can live elsewhere, and versions are cached side by side.
- Zero matches → print `usage report skipped — script not found` and go to *When you are done*. Never reimplement any part of the measurement here as a fallback; a hand-rolled approximation produces a plausible wrong number, which is worse than no number.

## Step 2 — Run it

The script is stdlib-only and is run with the system interpreter, not a project environment. One command, matching the mode you were called with.

**start:**

```bash
python3 "<script>" start --slug <slug>
```

It prints nothing on success and nothing when `CLAUDE_CODE_SESSION_ID` is unset — there is then no session to key a marker on, and that is a silent no-op, not a failure. Either way, say nothing in chat: the caller's Step 1 has better things to tell the user about.

**report:**

```bash
python3 "<script>" report --slug <slug> [--tracker "<tracker_file>"] [--feature-version <N>] [--outcome <completed|halted>] [--evals-included]
```

Pass only the optional flags you were actually given. `--evals-included` is a bare flag, not a value: include it when the argument was `evals_included=true`, and leave it off otherwise. `--outcome` accepts only `completed` or `halted`.

If `python3` is not available at all, print `usage report skipped — python3 not available` and go to *When you are done*.

## Step 3 — Relay the output

`report` writes the whole report to stdout and always exits `0`. **Relay that stdout to chat verbatim.** Do not reformat it, do not re-total anything, do not summarise it into a sentence, and never write a figure of your own alongside it — the table is the product, and it carries the same numbers the tracker panel and the log line carry because all three were rendered from one measurement.

The script also, in the same run, appends one line to the usage log and — when `--tracker` was passed — writes the figures into the tracker panel itself. You do not do either of those; this skill deliberately holds no `Edit` tool, so the anchored tracker replacement stays a deterministic Python edit rather than a hand-applied one.

A run that could not be measured prints exactly one line beginning `usage report skipped — ` instead of the table. Relay it as-is; it is a note, not an error. The causes it names are:

| Line | Meaning |
|---|---|
| `CLAUDE_CODE_SESSION_ID is not set` | No session to measure. Nothing was logged. |
| `no start marker for this run (cleared session, resumed run, or start never fired)` | The window has no beginning. **Never guess a start time.** |
| `the start marker has no readable timestamp` | Same — a fabricated window is worse than none. |
| `no transcript for this session` | The numbers live in the transcript; there isn't one. |
| `log write failed: <cause>` | The table still printed; only the log entry was lost. |
| `script not found` / `python3 not available` | Step 1 or Step 2 above; nothing ran. |
| anything else after `usage report skipped — ` | An unexpected problem, already caught and downgraded to this line. |

None of these is a reason to stop, retry, or investigate. Relay the line and carry on.

## When you are done

**Do not end your turn.** This skill is a side effect invoked mid-task; the moment the script's output is on the screen (or the skip line is), continue with the calling skill's next step, in the same turn, exactly where it left off. For `start` that is the rest of the caller's Step 1; for `report` it is whatever the caller's final step does next — for the three chaining skills, the chain offer that immediately follows.

## The tracker tokens this skill owns

`templates/feature-tracker.html` carries two usage tokens per stage panel, and this skill is the only one that fills them:

| Stage panel | Headline chip | Table |
|---|---|---|
| Brainstorming | `{{BRAINSTORMING_USAGE_CHIP}}` | `{{BRAINSTORMING_USAGE}}` |
| Design | `{{DESIGN_USAGE_CHIP}}` | `{{DESIGN_USAGE}}` |
| Plan | `{{PLAN_USAGE_CHIP}}` | `{{PLAN_USAGE}}` |
| Implementation | `{{IMPLEMENTATION_USAGE_CHIP}}` | `{{IMPLEMENTATION_USAGE}}` |

The four chain skills never touch these — they own the `_AT` / `_BULLETS` / `_DETAILS` tokens of their own panel and nothing else here, so no ordering dependency exists between their tracker steps and this one. `bug-tracker-render` is the only other skill that may name them, and it blanks all twenty feature-panel tokens when it regenerates a bug tracker rather than filling any.

These eight are the **one deliberate exception** to the plugin's substitute-only-if-literal rule, which is safe precisely because they have a single owner. On each run the script fills its own stage's pair and wraps the content in `<!-- usage:TOKEN -->…<!-- /usage:TOKEN -->` anchors; a re-run replaces what sits between those anchors, so the panel shows the latest figures rather than a second table. The other six are blanked to an *empty* anchored region while they are still literal — never deleted outright, so the stage that owns one can still fill it when it eventually runs.

## Constraints (non-negotiable)

- **Never fail the caller.** Reporting is a courtesy at the end of a run, and no failure in it may fail, block or abort the work that produced the run. Every path here ends in either a table or one `usage report skipped — …` line, and then in continuing the caller's step.
- **Never guess.** No estimated start time, no reconstructed totals, no "roughly". If the script could not measure the run, the honest output is the skip line.
- **Never hold schema knowledge.** No transcript field names, no file layouts, no dedup rules in this file. They live in `scripts/usage_report.py`, which is unit-tested against fixtures pinned to the real shape.
- **The usage chip must never read `Updated` followed by a date.** `feature-list` derives every feature's last-activity date by matching that shape in the tracker's chips, so a usage chip wearing it would silently make each feature report the wrong date. The rendered chip reads `8m 08s · 25,924 out · 76.0 tok/s`.
- **No conversation content ever leaves this skill.** The transcript the script reads holds the whole conversation; only numeric usage, timestamps and identifiers come back out of it. Never print, quote or summarise anything else you happen to see.
- **Never calls `feature-resolve`.** Pathing arrives as input — the `feature-mockup` precedent. Calling the resolver here would create folders and seed trackers as a side effect of reporting.
- **Never calls `lessons-capture`.** The reflection belongs to the calling skill's own lessons step; this skill holds no `Skill` tool, so it cannot invoke anything.
- **Subagents never call either mode.** The window belongs to the main agent for the whole run, exactly as the herdr label does. A subagent's work is inside the window and is counted by the scan, not by calling in.
