# Scheduled Report Exports — Design v3

**Status:** Draft
**Date:** 2026-07-10
**Storm:** [feature-storm-v3-scheduled-report-exports.md](./feature-storm-v3-scheduled-report-exports.md)

## 1. Summary
Team leads on the analytics dashboard export weekly reports by hand and mail them to stakeholders one by one. This feature adds scheduled, recurring exports: a team lead configures a report, a cadence, a format, and a recipient list once, and the platform renders and delivers the export automatically. It removes the most common support complaint of the quarter and makes weekly numbers reach stakeholders without a human in the loop.

## 2. Goals and non-goals
- **Goals:**
  - A team lead can create, edit, pause, and delete a recurring export for any report they can open, without contacting support.
  - Scheduled exports are delivered within 15 minutes of their configured time.
  - Recipients only ever receive reports they are permitted to see, evaluated at send time.
- **Non-goals:**
  - Ad-hoc one-off sends — already covered by the existing manual export flow.
  - Slack and Teams delivery — deferred to a later iteration so this feature can reuse the existing mailer unchanged.
  - Per-recipient row-level filtering — deferred until the permissions rework ships; today's permission model is report-level only.

## 3. Requirements
1. A team lead can create a schedule for any report they can open, choosing weekly or monthly cadence, PDF or CSV format, and a recipient list of workspace members and named external addresses.
2. A team lead can edit, pause, resume, and delete their own schedules from the report's settings panel.
3. Each due schedule is rendered and delivered within 15 minutes of its configured time.
4. Workspace-member recipients are permission-checked at send time with the existing report-access check; members who cannot open the report are skipped and the skip is recorded.
5. External addresses receive the export only if the schedule owner can open the report at send time; if the owner has lost access, the send is skipped and recorded.
6. A failed delivery is retried up to 3 times with exponential backoff; after the final failure the schedule owner is notified in-app.
7. When a schedule owner leaves the workspace, their schedules pause automatically and workspace admins are notified.
8. Rendering reuses the existing export pipeline — no second PDF/CSV renderer is introduced.
9. Peak schedule volume (Monday 09:00) must not degrade interactive dashboard p95 render latency beyond the current SLO.

## 4. Background and context
- Report rendering already exists as `app/exports/renderer.py:112` — `render_export(report_id, format) -> ExportArtifact`, used by the manual export button; it raises `RenderTimeout` after 120 s and `ReportGone` for deleted reports.
- Report-level access control lives in `app/auth/permissions.py:74` — `can_open(user_id, report_id) -> bool`; there is no row-level variant yet (see non-goals).
- The platform has a worker-based job queue at `app/jobs/queue.py:31` (`enqueue(job_type, payload, run_at)`) with a `low` priority lane added for backfills in `app/jobs/queue.py:58`; no new always-on service is needed.
- Outbound mail goes through `app/notify/mailer.py:58` — `send(to, subject, body, attachments) `; it returns a `DeliveryResult` with provider status rather than raising on 5xx.
- Report metadata lives in the `reports` table managed by `app/models/report.py:20`; migrations are additive SQL files under `migrations/`.
- The storm for this feature (same folder) fixed the product boundaries; its open questions — schedule-state storage, owner-departure behaviour, retry/notification policy — are each closed in §5 below.

## 5. Design

### Architecture / components
Five small components, each separately testable; the existing renderer, permissions module, queue, and mailer are reused, not modified.

- **ScheduleStore** — single responsibility: persistence of schedules and delivery outcomes. Public interface: `create/update/pause/resume/delete(schedule)`, `list_due(now) -> [Schedule]`, `advance(schedule_id)`, `claim(schedule_id, scheduled_for, attempt) -> bool`, `record_outcome(schedule_id, scheduled_for, attempt, outcome, skipped_recipients, detail)`, `pause_all_for_owner(user_id)`. Depends only on the database layer.
- **ScheduleApi** — single responsibility: the schedules HTTP API (Interfaces below). Enforces owner-or-admin authorisation, validates payloads (cadence, day, IANA timezone, RFC-shape recipient addresses) and maps validation failures to 422 with per-field messages. Depends on ScheduleStore, `app/auth/permissions.py:74` (the caller must be able to open the report), and the existing authenticated dashboard API layer.
- **ScheduleDispatcher** — single responsibility: turn time into work. Runs on the existing per-minute worker tick, calls `ScheduleStore.list_due(now)`, enqueues one `export_send` job per due schedule on the `low` priority lane with ±120 s jitter and `scheduled_for` = the schedule's `next_run_at`, then calls `ScheduleStore.advance`. Depends on ScheduleStore and `app/jobs/queue.py:31`.
- **ExportSender** — single responsibility: execute one `export_send` job. Claims the run, re-checks permissions (`can_open`, per R4/R5), calls `render_export`, hands the artifact to the mailer, records the outcome via ScheduleStore, and schedules retries. Depends on ScheduleStore, `app/auth/permissions.py:74`, `app/exports/renderer.py:112`, and `app/notify/mailer.py:58`.
- **ScheduleSettingsPanel** — single responsibility: the UI for R1/R2 inside the existing report settings page. Depends on ScheduleApi only.

### Data model
- New table `report_schedules`: `id`, `report_id` (FK reports), `owner_id`, `cadence` (`weekly`|`monthly`), `send_time` (local time of day), `send_day` (weekday 1–7 for weekly, day of month 1–31 for monthly), `timezone` (IANA name; defaults to the workspace timezone), `next_run_at` (UTC instant of the next due run), `format` (`pdf`|`csv`), `recipients` (JSON list of `{type: member|external, address}`), `state` (`active`|`paused`), `created_at`, `updated_at`. Extends the existing report metadata store (the direction the storm leaned) via one additive migration under `migrations/`; no changes to the `reports` table itself.
- `next_run_at` is computed from `send_time`, `send_day` and `timezone` on every write and by `advance` after each dispatch. A monthly `send_day` beyond the month's length (29–31) runs on that month's last day. A local time skipped by a DST change runs at the first valid minute after it; a repeated local time runs once, at its first occurrence.
- New table `schedule_deliveries`: `id`, `schedule_id` (FK), `scheduled_for` (the `next_run_at` the run belongs to), `attempt` (1 for the first send, 2–4 for the three retries), `outcome` (`in_progress`|`sent`|`skipped_permission`|`failed`), `skipped_recipients` (JSON list of `{type, address}` filtered out at send time; empty when none), `detail`, `created_at`. Unique on `(schedule_id, scheduled_for, attempt)`. Retained 90 days, pruned by the existing nightly cleanup job.
- Lifetime: schedules live until deleted by the owner or an admin; pausing (R7) never deletes data.

### Interfaces
- HTTP API (ScheduleApi) under the existing authenticated dashboard API: `POST/PATCH/DELETE /api/reports/{id}/schedules`, `GET /api/reports/{id}/schedules`. Payloads mirror the writable `report_schedules` columns (`cadence`, `send_time`, `send_day`, `timezone`, `format`, `recipients`, `state`); `next_run_at` is returned, never accepted. Validation errors return 422 with per-field messages; a caller who is neither the schedule owner nor a workspace admin gets 403.
- Job payload for `export_send`: `{schedule_id, scheduled_for, attempt}` — small and replayable.
- In-app notification on final delivery failure reuses the existing notification write path.

### Design language
- `ScheduleSettingsPanel` follows [`DESIGN.md`](../../DESIGN.md), reconciled before this design; specimen at [`design/specimen.html`](../../design/specimen.html) (https://claude.ai/artifact/9fK2mQ7xLwR4tVb8NcHs3D). Its rows, form, buttons and error banner use the recorded canonical `table`, `input`, `button` and `alert` components and the recorded type and spacing tokens; it introduces no other value.
- Language deltas: `Color: color.status-paused = #B45309 / #F59E0B — paused rows in the schedule list` — `pending v3`.
- Drift: none touches this surface.

### Control flow
Happy path: worker tick → `ScheduleDispatcher` finds due schedules → enqueues `export_send` (jittered, low lane) and advances `next_run_at` → `ExportSender` claims the run (inserts the `in_progress` delivery row) → filters recipients through `can_open` (owner check for external addresses) → `render_export` once per schedule → `mailer.send` per recipient batch → `record_outcome(sent)` with any filtered recipients in `skipped_recipients`. The 15-minute budget (R3) breaks down as ≤1 min dispatch, ≤2 min renders at p99, remainder queue headroom at peak.
Alternative flow — owner departure (R7): the existing workspace-membership removal hook calls `ScheduleStore.pause_all_for_owner(user_id)` and notifies admins; paused schedules are skipped by `list_due`.

### Failure and edge cases
- `RenderTimeout` from the renderer: record `failed` for the attempt and retry per R6.
- `ReportGone` from the renderer: record a final `failed`, pause the schedule and notify the owner in-app. No retry: the report no longer exists.
- Mailer returns a non-success `DeliveryResult` (it does not raise — see §4): record `failed` for the attempt and retry with backoff (1 min, 5 min, 25 min) as attempts 2, 3 and 4. When attempt 4 fails, that row is the final failure and the owner is notified in-app (R6).
- Some recipients filtered out by permission checks: send to the rest and record `sent` with the filtered ones in `skipped_recipients` (R4, R5).
- All recipients filtered out: record `skipped_permission` with every recipient in `skipped_recipients`, send nothing, do not retry — the next scheduled run re-evaluates.
- Duplicate ticks (worker restart between enqueue and `advance`): `claim` inserts the `in_progress` row for `(schedule_id, scheduled_for, attempt)`; the unique constraint makes a duplicate job's claim fail, and that job exits without sending. A retry job carries the next attempt number, so it is never blocked by the earlier attempt's row.
- Attachment over the mailer's 20 MB limit: record a final `failed` with detail, notify the owner, do not retry (retrying cannot shrink it).

### Security
- Trust boundary is the recipient list. Member recipients: `can_open(recipient, report)` at send time (R4) — never at schedule time, so revoked members stop receiving immediately. External addresses cannot be permission-checked, so they inherit the owner's live access (R5): if the owner can no longer open the report, external sends stop.
- Schedule CRUD (ScheduleApi) requires the caller to be the schedule owner or a workspace admin, on top of the existing authenticated API; creating a schedule also requires `can_open(caller, report)`.
- Recipient addresses are validated on write by ScheduleApi (RFC-shape check) and stored as data, never interpolated into mail headers directly — the existing mailer already header-encodes.
- No new secrets; delivery logs store addresses but never report content.

### Performance
- Rendering runs on the `low` queue lane with ±120 s jitter, so Monday-09:00 bursts cannot starve interactive renders (R9); the interactive path keeps its current lane untouched.
- One render per schedule regardless of recipient count; the artifact is reused across the recipient batch.
- `list_due` reads via an index on `(state, next_run_at)` added in the same migration.

### Observability
- Counter metrics per terminal outcome (`sent`, `skipped_permission`, `failed`) and a gauge for queue lag between `scheduled_for` and actual send; lag > 15 min is alertable (R3).
- Each `export_send` logs schedule id, attempt, and outcome — no report content, no recipient lists in logs.

### Compatibility / migration
- One additive migration (two new tables + index); no existing table changes and nothing to reverse. Rollback is disabling the `scheduled_exports` flag (§9): the tables and stored schedules are kept, dormant. Older app versions ignore the new tables entirely.

### Testing strategy
- **ScheduleStore**: unit tests against a test database — CRUD, `next_run_at` computation (monthly on the 31st in a 30-day month and in February, timezone offsets, both DST transitions), `list_due` boundaries (due exactly now, paused), `advance`, `claim` refusing a duplicate triple, `pause_all_for_owner`. No other component involved.
- **ScheduleApi**: unit tests with a fake store and fake permissions — owner and admin allowed, anyone else 403; 422 per field for bad cadence, day, timezone and recipient addresses; `next_run_at` rejected on write.
- **ScheduleDispatcher**: unit tests with a fake store and fake queue — enqueues exactly the due set with `scheduled_for` = `next_run_at`, applies jitter bounds, skips paused, advances each dispatched schedule.
- **ExportSender**: unit tests with fakes for store/permissions/renderer/mailer — partial and total permission filtering (member and external paths) with `skipped_recipients`, retry ladder through attempt 4, duplicate claim exits without sending, retry not blocked by the earlier attempt, `ReportGone` pauses without retry, oversized-attachment terminal failure. Each §5 failure case above has a corresponding test.
- **ScheduleSettingsPanel**: component tests against a mocked API — all four UI states below, paused-row styling, validation errors on bad cadence/recipients.
- Integration: one end-to-end test that creates a schedule, advances the clock, and asserts a delivery row and one mail via the mailer's test transport. Acceptance for R3 is asserted on the queue-lag metric in staging.

### UI flows and states
The panel follows the accepted mockup [`mockups/mockup-v3-schedule-panel.html#compact-rows`](./mockups/mockup-v3-schedule-panel.html#compact-rows); the `card-list` option on the same page was rejected (§6). As that mockup shows it, the settings panel (R1/R2) has four states: **empty** ("No scheduled exports yet" with a create button), **loading** (skeleton rows while fetching), **error** (fetch failure banner with retry), and **populated** (one compact row per schedule — cadence, next run in the schedule's timezone, format, recipient count — with pause/edit/delete; paused rows are tinted `color.status-paused`). The create/edit form opens inline below the rows, validates inline and disables submit while saving; delivery failures surface as an in-app notification linking back to this panel.

## 6. Alternatives considered
- Evaluating recipient permissions at schedule-creation time instead of send time — rejected because membership churn would leak reports to removed members (the storm's top risk).
- A standalone scheduler service with its own clock — rejected because the existing per-minute worker tick already provides the needed granularity and the storm rules out new always-on services.
- Storing schedules as JSON blobs on the `reports` row — rejected because `list_due` would require a full-table scan instead of an indexed query.
- A card list for the schedules panel (the mockup's `card-list` option) — rejected in the mockup round because three schedules pushed the create button below the fold of the settings page.

## 7. Risks and issues
- Monday-09:00 render bursts contend with interactive use — likelihood medium, impact degraded dashboard latency; mitigated by the `low` queue lane plus jitter (§5 Performance), with the queue-lag alert as the tripwire.
- Attachment-heavy mail gets spam-filtered and silently dropped — likelihood medium, impact users distrust the feature; mitigated by using the already-authenticated (SPF/DKIM) mailer domain and surfacing provider bounce status from `DeliveryResult` as a delivery failure rather than a silent success.
- Recipient JSON lists drift from future recipient features (e.g. groups) — likelihood low, impact migration cost; mitigated by keeping recipient handling inside ScheduleStore so a schema change touches one component.

## 8. Open questions
None — all decisions closed.

## 9. Rollout plan
Phase 1: enable behind the `scheduled_exports` feature flag for two internal workspaces for one week; watch outcome metrics and queue lag. Phase 2: 10% of workspaces, then 100% after a clean week. Rollback at any phase: disable the flag — the dispatcher no-ops, existing schedules are retained but dormant, and the additive migration needs no reversal. Launch note in the dashboard changelog; support macro updated to point at the settings panel.
