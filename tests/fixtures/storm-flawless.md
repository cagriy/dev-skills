# Scheduled Report Exports — Brainstorm v3

**Status:** Draft
**Date:** 2026-07-10

## 1. Summary
Team leads on the analytics dashboard currently export weekly reports by hand and mail them to stakeholders one by one. We're considering scheduled, recurring exports: a team lead configures a report, a cadence, and a recipient list once, and the platform delivers the export automatically. Why now: the Q3 rollout of shared workspaces tripled the number of stakeholders asking for weekly numbers, and manual exporting has become the single most common support complaint this quarter.

## 2. Goals
- A team lead can set up a recurring export for any report they can open, without contacting support.
- Scheduled exports are delivered within 15 minutes of their configured time.
- Support tickets tagged "manual export" drop by at least half within one quarter of launch.
- At least 30% of weekly-active team leads have one live schedule within two months of launch.

## 3. Scope (in / out)
- **In scope:** weekly and monthly schedules; PDF and CSV formats; delivery by email to workspace members and named external addresses.
- **Out of scope / deferred:** ad-hoc one-off sends (already covered by manual export); Slack and Teams delivery (deferred to a later iteration); per-recipient row-level filtering (deferred until the permissions rework ships).

## 4. High-level technical direction
- Must reuse the existing export rendering path — no second PDF pipeline to maintain.
- Delivery must respect existing workspace permissions: recipients only ever receive reports they could open themselves, evaluated at send time.
- Must fit the current infrastructure budget — no new always-on services.
- Deliberately NOT detailed design — the scheduling mechanism, queueing, and retry policy are decisions for /feature-design.

## 5. Alternatives considered
- Browser-extension auto-download on a local schedule — rejected because delivery must not depend on a team lead's machine being on at the scheduled time.
- Buying a third-party report-delivery service — rejected because reports contain customer data and our current data-processing agreements don't cover a new subprocessor.
- Do nothing and document the manual flow better — rejected because ticket volume scales with workspace adoption, not with user confusion; documentation doesn't change the trend.

## 6. Risks
- If permission checks happen at schedule time instead of send time, a recipient removed from a workspace could keep receiving reports — impact: data-exposure incident.
- Export rendering at popular schedule times (Monday 09:00) could contend with interactive dashboard use — impact: degraded latency for all users at peak.
- Spam filtering of attachment-heavy mail could silently drop deliveries — impact: users lose trust in the feature and revert to manual exporting.

## 7. Open questions for design
- Where does schedule state live: extend the existing report metadata store, or a separate scheduling table? (user leaned toward extending report metadata, but didn't commit)
- What happens to a schedule when its owner leaves the workspace — pause, transfer to another member, or delete?
- Should failed deliveries retry automatically, and how is the schedule owner notified of repeated failures?
