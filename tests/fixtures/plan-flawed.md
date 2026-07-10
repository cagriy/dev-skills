# Notifications Revamp — Implementation Plan v2

**Status:** Draft
**Date:** 2026-07-10
**Design:** [feature-design-v2-notifications-revamp.md](./feature-design-v2-notifications-revamp.md)

## Overview
This plan implements the notifications revamp in four stages.

## Development strategy — Test-Driven Development
We follow TDD where practical. The test framework will be decided later, once we see how the code shapes up.

## Requirements coverage map

| Design req | Delivered by stage(s) |
| --- | --- |
| R1: notifications created for mentions, assignments, watched changes | Stage 2 |
| R2: notification center lists notifications with unread badge | Stage 2 |
| R3: mark one or all notifications read | Stage 2 |
| R4: mute a project | |
| R5: export history to CSV | Stage 4 |
| R6: new notifications appear within 5 seconds | Stage 3 |

## Stages

### Stage 1 — Public notifications endpoint
**Goal:** Expose `GET/POST /api/notifications` so the frontend team can start early.
**Touches:** `app/api/notifications.py`

**Steps:**
1. Implement the endpoint returning notifications from `NotificationStore`.
2. Authentication and authorization will be added in Stage 3 once the auth approach is settled; until then the endpoint is open.
3. Write a test for the endpoint. Run it — it will fail. Then make it pass.

### Stage 2 — The notifications engine
**Goal:** Everything else: the `notifications` schema and store, event matching for mentions/assignments/watched changes, read-state and badge counting, the notification-center UI, and the WebSocket push channel.
**Touches:** `migrations/`, `app/notifications/`, `dashboard/src/`

**Steps:**
1. Create the schema and `NotificationStore`.
2. Implement event matching, read-state, badge counting, the UI, and push.
3. Add tests at the end of the stage if time allows; otherwise we will add tests once the feature stabilises.

**Risks specific to this stage:** This stage is large.

### Stage 3 — Real-time delivery hardening
**Goal:** Make the push channel reliable and add auth to the API.
**Touches:** `app/notifications/push.py`, `app/api/notifications.py`

**Steps:**
1. Write test: reconnect/backoff behavior for the push channel.
2. Run it — confirm it fails.
3. Implement reconnect/backoff; wire authentication onto the Stage 1 endpoint.
4. Run it — confirm it passes.

### Stage 4 — CSV export
**Goal:** Users can export their notification history to CSV.
**Touches:** TBD — probably somewhere under `app/exports/`.

**Steps:**
1. Figure out where export code should live.
2. Implement the CSV export; it should be straightforward.

## Cross-cutting concerns
- **Security** — covered by Stage 3.
- **Performance** — the system should be fast enough.

## Verification
Manual poke around the notification center once everything is merged.

## Risks and open issues
- Timeline risk.
- Scope creep.

## Planning decisions taken
1. Switched notification storage from the relational database (design §5) to Redis — it should be faster for this workload.
2. Stages ordered API-first so the frontend team is unblocked.

## Deviations from the design
None — plan matches design v2 exactly.
