# Notifications Revamp — Brainstorm v2

**Status:** Draft
**Date:** 2026-07-10

## 1. Summary
We want to revamp notifications because the current ones aren't great. This will make the product better for users.

## 2. Goals
- Make notifications better.
- Improve the user experience.
- Modernise the notification system.

## 3. Scope (in / out)
- **In scope:** everything related to notifications.
- **Out of scope / deferred:** things not related to notifications.

## 4. High-level technical direction
- Implement with Redis pub/sub, a WebSocket gateway service, and a React notification-center modal with infinite scroll.
- Store notifications in a new `notifications` table with columns `id`, `user_id`, `payload`, `read_at`.

## 5. Alternatives considered
- Not applicable — we didn't consider any.

## 6. Risks
- Timeline risk.
- Scope creep.
- Technical debt.

## 7. Open questions for design
- Figure out the architecture.
- Sort out the details.
