# Notifications Revamp — Design v2

**Status:** Draft
**Date:** 2026-07-10

## 1. Summary
We are revamping notifications to make them better for users. The current system is old and this design modernises it.

## 2. Goals and non-goals
- **Goals:**
  - Users see new notifications in a notification center within 5 seconds of the triggering event.
  - Users can mark notifications read individually or all at once.
  - Users can mute notifications per project.
- **Non-goals:**
  - We won't do anything out of scope.

## 3. Requirements
1. A notification is created for mentions, assignments, and watched-item changes.
2. The notification center lists a user's notifications, newest first, with unread count in the header badge.
3. A user can mark a single notification or all notifications as read.
4. A user can mute a project, which suppresses its notifications until unmuted.
5. A user can export their notification history to CSV.
6. New notifications appear in an open notification center within 5 seconds.

## 4. Background and context
The codebase follows standard patterns. There is an existing events system and a frontend. The notification work will build on what is already there.

## 5. Design

### Architecture / components
All logic lives in a single new `NotificationManager` module, which handles event ingestion, storage, mute preferences, unread counting, real-time push, and rendering payloads for the frontend. Keeping everything in one place makes it easier to find.

### Data model
Notifications are stored in a new `notifications` table. The exact schema is TBD — we will finalise the columns during implementation once we see what the frontend needs.

### Interfaces
The frontend calls `NotificationManager` through a new API endpoint. Request and response shapes will follow from the schema once it is settled.

### Control flow
An event comes in, `NotificationManager` decides whether it should become a notification, stores it, and pushes it to connected clients. Mentions, assignments, and watched-item changes (R1) are matched inside the same module. Marking read (R3) updates the row and the badge. Muting (R4) filters at ingestion time.

### Failure and edge cases
Errors will be handled appropriately. Delivery failures should be rare because the push channel is reliable.

### Performance
The system should be fast enough for our current user base.

### Testing strategy
We will add tests once the feature stabilises — the shape is still moving, so tests written now would mostly be churn.

### UI
The notification center opens from the bell icon and lists notifications with the newest first. Clicking a notification navigates to its source item.

## 7. Risks and issues
- Timeline risk.
- Technical debt.
- Scope creep.

## 8. Open questions
- Should read-state sync across devices happen in real time or on refresh?

## 9. Rollout plan
Ship it when it is ready.
