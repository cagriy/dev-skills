# Scheduled Report Exports — Implementation Plan v3

**Status:** Draft
**Date:** 2026-07-10
**Design:** [feature-design-v3-scheduled-report-exports.md](./feature-design-v3-scheduled-report-exports.md)

## Overview
This plan builds the scheduled-exports feature in seven stages that follow the design's component decomposition: persistence first (ScheduleStore + migration), then the time-to-work path (ScheduleDispatcher), the execution path (ExportSender), the HTTP API, the settings UI, the owner-departure hook, and finally the feature flag plus end-to-end wiring. Each stage maps to design §5 components and leaves the system working; the flag stage last means nothing is user-visible until everything behind it is green.

## Development strategy — Test-Driven Development
Every behavior-changing stage in this plan follows the TDD cycle:

1. **Write the test first.** Add the test(s) that describe the new behavior.
2. **Run the test and confirm it fails.** Capture the failure to prove the test exercises the new behavior.
3. **Write the implementation.** The minimum code needed to satisfy the test.
4. **Run the test and confirm it passes.** Plus the surrounding suite, to catch regressions.

Stages that fit a sanctioned non-red-first category — non-TDD (scaffolding | config-only | integration-verified), behaviour-preserving refactor/deletion, characterization/guard tests, platform-only/UI wiring — are labeled with that category and a one-line justification. Backend tests run with `pytest` (suite root `tests/`); the dashboard frontend uses `vitest` (suite root `dashboard/src/components/__tests__/`).

## Requirements coverage map

| Design req | Delivered by stage(s) |
| --- | --- |
| R1: create schedule (cadence, format, recipients) | Stage 1, Stage 4, Stage 5 |
| R2: edit/pause/resume/delete own schedules | Stage 1, Stage 4, Stage 5 |
| R3: delivery within 15 minutes of configured time | Stage 2, Stage 3, Stage 7 |
| R4: member recipients permission-checked at send time | Stage 3 |
| R5: external addresses gated on owner's live access | Stage 3 |
| R6: bounded retries + owner notified on final failure | Stage 3 |
| R7: schedules pause when owner leaves workspace | Stage 6 |
| R8: rendering reuses the existing export pipeline | Stage 3 |
| R9: peak schedules don't degrade interactive p95 latency | Stage 2, Stage 7 |

## Stages

### Stage 1 — ScheduleStore and additive migration
**Goal:** Persist schedules and delivery outcomes behind a single store component.
**Design references:** §5 (Architecture, Data model), §3 R1–R2 of feature-design-v3-scheduled-report-exports.md
**Touches:** create `migrations/0042_report_schedules.sql`, `app/schedules/store.py`, `tests/schedules/test_schedule_store.py` (sibling convention: `tests/models/test_report.py`)

**Steps (TDD):**
1. Write test: `tests/schedules/test_schedule_store.py` → CRUD round-trip, `list_due` boundary times (due exactly now, paused excluded, monthly on the 31st), `pause_all_for_owner`, `record_outcome`. Expected initial failure: `ModuleNotFoundError: No module named 'app.schedules'`.
2. Run the test — confirm it fails with the expected error.
3. Implement: the migration (two tables + `(state, send_at)` index, additive only) and `app/schedules/store.py` with `create/update/pause/resume/delete`, `list_due(now)`, `record_outcome`, `pause_all_for_owner`.
4. Run the test — confirm pass. Run `pytest tests/` — confirm no regressions.

**Definition of done:**
- All store operations covered by unit tests against the test database.
- Migration applies and rolls back cleanly (drop of unused tables only).

**Risks specific to this stage:** None

### Stage 2 — ScheduleDispatcher on the worker tick
**Goal:** Turn due schedules into queued `export_send` jobs with jitter, on the low-priority lane.
**Design references:** §5 (Architecture, Control flow, Performance), §3 R3, R9
**Touches:** create `app/schedules/dispatcher.py`, `tests/schedules/test_dispatcher.py`; modify `app/jobs/tick.py` (register the dispatcher on the per-minute tick)

**Steps (TDD):**
1. Write test: `tests/schedules/test_dispatcher.py` → with a fake store and fake queue: enqueues exactly the due set, payload `{schedule_id, scheduled_for, attempt}`, jitter within ±120 s, `low` lane, paused schedules skipped. Expected initial failure: `ModuleNotFoundError: No module named 'app.schedules.dispatcher'`.
2. Run the test — confirm it fails with the expected error.
3. Implement: `dispatcher.py` using `ScheduleStore.list_due` and `app/jobs/queue.py` `enqueue`; register on the tick.
4. Run the test — confirm pass. Run `pytest tests/` — confirm no regressions.

**Definition of done:**
- Dispatcher unit-tested with fakes only; no real queue or database needed.
- Tick registration verified by the existing `tests/jobs/test_tick.py` registry guard (updated in the same stage — it asserts the tick handler list).

**Risks specific to this stage:** Time-based assertions can flake — use the repo's existing `tests/helpers/fake_clock.py` instead of real time.

### Stage 3 — ExportSender job
**Goal:** Execute one `export_send` job end-to-end: permission filtering, render reuse, delivery, outcomes, retries.
**Design references:** §5 (Control flow, Failure and edge cases, Security, Observability), §3 R3–R6, R8
**Touches:** create `app/schedules/sender.py`, `tests/schedules/test_sender.py`; modify `app/jobs/registry.py` (register the `export_send` job type)

**Steps (TDD):**
1. Write test: `tests/schedules/test_sender.py` → with fakes for store/permissions/renderer/mailer: member filtering via `can_open` at send time; external addresses gated on the owner's live access; one render reused across the recipient batch; retry ladder (1/5/25 min) ending in owner notification; idempotency short-circuit on `(schedule_id, scheduled_for)`; `ReportGone` pauses the schedule; oversized attachment is a terminal failure; outcome counters emitted. Expected initial failure: `ModuleNotFoundError: No module named 'app.schedules.sender'`.
2. Run the test — confirm it fails with the expected error.
3. Implement: `sender.py` calling `app/auth/permissions.py` `can_open`, `app/exports/renderer.py` `render_export`, `app/notify/mailer.py` `send`, recording via ScheduleStore; register the job type.
4. Run the test — confirm pass. Run `pytest tests/` — confirm no regressions.

**Definition of done:**
- Every failure case from design §5 has a named test.
- Metrics: per-outcome counters and the `scheduled_for`→sent lag gauge emitted via the existing metrics helper.

**Risks specific to this stage:** None

### Stage 4 — Schedules HTTP API
**Goal:** Expose schedule CRUD on the authenticated dashboard API.
**Design references:** §5 (Interfaces, Security), §3 R1–R2
**Touches:** create `app/api/schedules.py`, `tests/api/test_schedules_api.py` (sibling convention: `tests/api/test_reports_api.py`); modify `app/api/router.py`

**Steps (TDD):**
1. Write test: `tests/api/test_schedules_api.py` → CRUD via `POST/PATCH/DELETE/GET /api/reports/{id}/schedules`; owner-or-admin authorization enforced on every verb (403 otherwise); 422 with per-field messages on bad cadence/recipients; recipient address shape validated on write. Expected initial failure: `404` from the test client — route not registered.
2. Run the test — confirm it fails with the expected error.
3. Implement: `app/api/schedules.py` delegating to ScheduleStore; register the route.
4. Run the test — confirm pass. Run `pytest tests/` — confirm no regressions.

**Definition of done:**
- Authorization tests cover owner, admin, non-member, and revoked-member callers.
- Validation errors are field-addressed, matching the dashboard API's existing 422 shape.

**Risks specific to this stage:** None

### Stage 5 — Schedule settings panel
**Goal:** The report-settings UI for creating and managing schedules, with all four states.
**Design references:** §5 (UI flows and states, Interfaces), §3 R1–R2
**Touches:** create `dashboard/src/components/ScheduleSettingsPanel.tsx`, `dashboard/src/components/__tests__/ScheduleSettingsPanel.test.tsx` (sibling convention: `ExportButton.test.tsx`)

**Steps (TDD):**
1. Write test: `ScheduleSettingsPanel.test.tsx` → against a mocked API: empty state ("No scheduled exports yet"), loading skeleton, fetch-error banner with retry, populated rows with pause/edit/delete; create/edit form validates inline and disables submit while saving. Expected initial failure: cannot resolve module `../ScheduleSettingsPanel`.
2. Run the test — confirm it fails with the expected error.
3. Implement: the panel component against `GET/POST/PATCH/DELETE /api/reports/{id}/schedules`.
4. Run the test — confirm pass. Run `vitest run dashboard/src` — confirm no regressions.

**Definition of done:**
- All four UI states asserted; form validation paths covered.
- No new frontend dependency added.

**Risks specific to this stage:** None

### Stage 6 — Owner-departure pause hook
**Goal:** Pause a departing owner's schedules and notify workspace admins.
**Design references:** §5 (Control flow — alternative flow), §3 R7
**Touches:** modify `app/workspaces/membership.py` (removal hook), create `tests/workspaces/test_membership_schedules.py` (sibling convention: `tests/workspaces/test_membership.py`)

**Steps (TDD):**
1. Write test: `tests/workspaces/test_membership_schedules.py` → removing a member calls `pause_all_for_owner` and writes one admin notification via the existing notification path; removal without schedules notifies nothing. Expected initial failure: assertion — fake store's `pause_all_for_owner` never called.
2. Run the test — confirm it fails with the expected error.
3. Implement: wire the existing membership-removal hook to ScheduleStore and the notification write path.
4. Run the test — confirm pass. Run `pytest tests/` — confirm no regressions.

**Definition of done:**
- Departure pauses schedules without deleting data; admins notified exactly once.

**Risks specific to this stage:** None

### Stage 7 — Feature flag and end-to-end wiring
**Goal:** Gate the whole feature behind `scheduled_exports` and prove the chain end-to-end.
**Category:** Non-TDD (integration-verified) — the stage is flag plumbing plus a live integration check; the behavior it gates is already unit-tested in Stages 1–6, and the end-to-end path is verifiable only by running the queue worker against a test transport.
**Design references:** §5 (Compatibility / migration), §9 Rollout, §3 R3, R9
**Touches:** modify `app/config/flags.py`, `app/schedules/dispatcher.py` (no-op when flag off), `app/api/schedules.py` (404 when flag off), `dashboard/src/components/ScheduleSettingsPanel.tsx` (hidden when flag off); create `tests/integration/test_scheduled_exports_e2e.py`

**Steps:**
1. Add the `scheduled_exports` flag (default off) and gate dispatcher, API, and panel on it.
2. Integration verification: run `pytest tests/integration/test_scheduled_exports_e2e.py` — creates a schedule with the flag on, advances the fake clock past the send time, runs one worker pass, and asserts a `sent` delivery row and exactly one mail on the mailer's test transport; asserts the lag gauge is under 15 minutes; with the flag off, asserts the dispatcher enqueues nothing.
3. Run the full backend and frontend suites — confirm no regressions.

**Definition of done:**
- Flag off: dispatcher no-ops, API 404s, panel hidden — verified by the integration test.
- Flag on: end-to-end delivery proven against the test transport.

**Risks specific to this stage:** None

## Cross-cutting concerns
- **Security** — send-time permission checks live in Stage 3 (member `can_open`, owner-gated external addresses); API authorization and input validation in Stage 4; the flag (Stage 7) keeps every surface dark until the whole chain is protected — no stage exposes an endpoint before its authz lands.
- **Performance** — low-lane + jitter dispatch (Stage 2) and the `(state, send_at)` index (Stage 1) implement design §5's peak-contention decisions; the integration test (Stage 7) asserts the lag budget.
- **Observability** — outcome counters and the delivery-lag gauge land with the sender (Stage 3); the lag alert threshold matches R3's 15-minute budget.
- **Compatibility / migration** — the migration is additive (Stage 1) and no existing table changes, so every intermediate stage leaves current behavior untouched; the feature is dark until Stage 7's flag.

## Verification
With all stages complete and the flag on in staging: configure a weekly schedule for a real report via the settings panel, wait for (or fake-clock past) the send time, and confirm the recipient receives the export, the delivery row records `sent`, and the queue-lag gauge stays under 15 minutes — the acceptance criteria from design §3 (R1, R3). Revoke a recipient's report access and confirm the next run records `skipped_permission` (R4).

## Risks and open issues
- Time-based tests can flake under CI load — mitigated by using the repo's existing `fake_clock` helper everywhere instead of real sleeps.
- The integration test depends on the mailer's test transport — mitigated by asserting the transport exists in the test's setup and skipping with a loud message (not silently) if the environment lacks it.

## Planning decisions taken
1. Data-first stage order (store before dispatcher before sender) — each later component's fakes mirror an already-real interface, keeping fakes honest.
2. Backend test files live under `tests/schedules/`, mirroring the `tests/models/` sibling convention; frontend tests colocate under `__tests__/` per the dashboard's existing pattern.
3. The feature flag lands in the final stage rather than early — the design mandates the flag but not its timing, and gating last keeps stages 1–6 invisible without extra flag plumbing in each.
4. Existing `fake_clock` test helper adopted for all time-dependent tests — the design is silent on test tooling.

## Deviations from the design
None — plan matches design v3 exactly.
