# Decision Queue discovery controls v1

**Status:** deployed to private staging and exact-source canary verified on `2026-08-28`

This private-cockpit feature makes the authenticated review entry easier to
find and narrow before a human opens a Decision Brief. Internal navigation now
uses the same `Risk Hotspots` name as the destination page, and Decision Queue
can filter waiting Actions by `CRITICAL`, `HIGH`, `MEDIUM`, or `LOW` severity.

## Queue contract

- `All` contains only `PROPOSED` and `EDITED` Actions waiting for review.
- Each severity filter uses the normalized server-provided
  `alert_severity`; filtering never rewrites the Action.
- Every filter displays its waiting count, including a visible zero.
- A filter with no matching waiting Actions displays a bounded empty state and
  offers no inferred or substituted Action.
- Closed or completed Actions cannot re-enter Decision Queue through filtering.

Selecting a visible Action continues through SLA Decision review handoff v1.
Filtering does not weaken its exact-one Risk resolution, immutable Brief
binding checks, or selected-Action return path.

## Authority and maturity boundary

The feature is browser-local presentation over the already authenticated
Action response. It adds no API route, request, storage, query, mutation,
telemetry, deployment mechanism, or public Pages surface. It cannot edit, approve, reject,
complete, execute, or observe an Action or Outcome.

Commit `3316627` was published to private staging after separate explicit human
authorization. The standard read-only staging verifier passed, and an exact-
source canary found the live index and all 9 referenced assets byte-identical to
the authorized build. The byte-matched live bundle contains `Risk Hotspots`,
`MEDIUM`, and `Review now`; the focused waiting-only filter scenario passed
without changing source state.

The canary created no user, made no authenticated entity request, and granted no
Action or business-decision authority. The natural SLA proposal remains
`WAITING_HUMAN_REVIEW` until an independently justified named-human decision.
