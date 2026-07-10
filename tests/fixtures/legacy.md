# Workspace Audit Log — Brainstorm v1

**Status:** Draft
**Date:** 2026-05-02

## 1. Summary
Workspace admins have no way to see who changed a dashboard, invited a member, or exported data — every "who did this?" question becomes a support escalation with engineering pulling raw database history. We're considering an in-product audit log: a chronological, filterable record of administrative and data-access actions per workspace. Why now: two enterprise prospects made an audit trail a condition of signing this quarter, and support escalations for history reconstruction doubled since the shared-workspaces launch.

## 2. Goals
- A workspace admin can answer "who did X and when" for any tracked action from the last 90 days without contacting support.
- Support escalations asking engineering to reconstruct history drop to zero within one quarter of launch.
- The two named enterprise prospects accept the audit capability as satisfying their procurement requirement.

## 3. Scope (in / out)
- **In scope:** membership changes, permission changes, dashboard create/edit/delete, data exports; a filterable list view; CSV download of the log.
- **Out of scope / deferred:** real-time alerting on audit events (deferred to a later iteration); retention beyond 90 days (deferred until storage costs are modelled); SIEM/webhook streaming (deferred — no current customer commitment).

## 4. High-level technical direction
- Audit records must be append-only from the application's perspective — no edit or delete path in product code.
- Must not add measurable latency to the actions being audited; capture must be asynchronous to the user-facing request.
- Log access is itself a permissioned, audited action — admins only.
- Deliberately NOT detailed design — storage shape, capture mechanism, and retention enforcement are decisions for /feature-design.

## 5. Open questions for design
- Is capture transactional with the audited action or best-effort asynchronous — and if best-effort, what loss rate is acceptable? (user leaned toward best-effort, but didn't commit)
- Do audit records reference entities by id, by display name at time of action, or both?
- Where is the 90-day retention enforced — storage layer, scheduled job, or query filter?
