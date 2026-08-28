# SLA Decision review handoff v1

**Status:** deployed to private staging and exact-source canary verified on `2026-08-28`

This private-cockpit handoff connects one authenticated Decision Queue entry to
its complete bound Decision Brief and then back to that same governed Action.
It fixes a navigation ambiguity only. It adds no API route, data write,
deployment mechanism, or human decision authority.

## Fail-closed entry contract

`Review now` opens a Brief only when the browser can reconcile exactly one
current open Risk to the selected Action through `alert_fingerprint` and all of
the following immutable fields agree:

- shipment and Alert type;
- `decision-brief.v1` schema and Action binding version;
- recommended Action type and selected alternative; and
- the exact deterministic selection rationale.

A missing or duplicate Risk, resolved Risk, absent Brief, incomplete Action
binding, source mismatch, Decision mismatch, or rationale mismatch blocks the
handoff. The cockpit displays a bounded reason and states that no Action was
changed. It does not fall back to a different Risk, Brief, or Action.

## Review and return behavior

After a successful reconciliation, the full bound Brief opens in read-only
review mode. Its primary control returns to an Action Board containing only the
selected Action card. The operator may explicitly return to the same Brief or
choose `Show all Actions`. If the selected Action disappears after a refresh,
the focused mutation surface remains unavailable until the operator explicitly
leaves the focused view.

The handoff performs no automatic evidence-chain request. Evidence remains a
separate operator click, so opening a Brief does not create an extra Athena
read. Existing signed-identity, RBAC, audit-reason, and append-only event checks
still govern every Action mutation.

## Authority and maturity boundary

Commit `3316627` was published to the private Amplify staging branch after
separate explicit human authorization. The standard read-only staging verifier
passed, and an exact-source canary found the live index plus all 9 referenced
assets byte-identical to the authorized internal build. The live bundle contains
the `Review now`, selected-Action return, and Brief-return markers; the focused
deterministic handoff scenario also passed.

This evidence establishes deployed package and contract integrity, not a named-
human review of an entity. The canary created no user, made no authenticated
entity request, and did not approve, reject, edit, complete, execute, or observe
an Action or Outcome. The natural SLA proposal remains
`WAITING_HUMAN_REVIEW`, and any business judgment remains named-human owned.
