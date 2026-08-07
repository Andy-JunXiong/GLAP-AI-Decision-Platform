# Operations API reliability runbook

This runbook covers the authenticated, staging-only Operations API. It does not
authorize production changes, recurring schedules, public write access, or new
operational Action mutations.

## Signals and response

| Signal | Meaning | Operator response |
| --- | --- | --- |
| `ServiceUnavailable` alarm | The API returned a controlled 503 because a dependency failed | Stop new write attempts, inspect the safe Lambda error type/AWS code, restore the dependency, then retry with the same request ID |
| `ThrottleResponses` alarm | API Gateway returned one or more 429 responses | Back off with jitter, preserve the request ID, and retry below the published rate |
| HTTP 404 | The Action is absent from the requested operational scope | Do not retry as a service failure; refresh the queue and reconcile the Action reference |
| HTTP 409 | The Action state was consumed by a competing transition | Refresh the Action state; do not submit a new request ID for the stale transition |
| HTTP 503 | The request outcome is uncertain until reconciled | Retry only with the original request ID after the dependency recovers |

API Gateway access logs contain only request ID, route key, and status. They do
not contain IP addresses, identity claims, authorization headers, request bodies,
Action IDs, or request IDs supplied in the JSON body.

## Verification

Preview the bounded test before applying it:

```powershell
.\ops\verify_operations_reliability_staging.ps1
```

The apply mode requires an explicit failure-injection switch:

```powershell
.\ops\verify_operations_reliability_staging.ps1 `
  -Profile codex-readonly `
  -Apply `
  -InjectFailure
```

The verifier replays one existing operational audit request sequentially and
concurrently, so it does not create or change an Action. It confirms the audit
event count remains one. It temporarily isolates only the staging mutation
dependency to produce a real 503, restores the original Lambda environment in a
`finally` block, and verifies the same path returns the correct domain 404 after
recovery. It temporarily lowers the API stage throttle for a bounded burst,
restores the original rate and burst in a second `finally` block, and requires
both alarms to enter `ALARM` and recover to `OK`.

The encrypted Lambda DLQ is expected to remain empty because API Gateway invokes
the Lambda synchronously. A non-empty DLQ is not accepted as synchronous recovery
evidence. Temporary Cognito users are suppressed from email delivery, removed,
and confirmed absent before the script succeeds. The verifier refuses to trigger
alarms that have external notification or automation actions.

## Recovery order

1. Stop clients from creating new request IDs for an uncertain operation.
2. Confirm the API stage throttle and Lambda environment match the deployed
   configuration.
3. Resolve the dependency failure without bypassing authorization or temporal
   scope checks.
4. Retry with the original request ID and verify `idempotent_replay: true` when
   the original audit event exists.
5. Confirm both alarms return to `OK`, the synchronous DLQ remains empty, and no
   temporary user remains.

As of the Australia/Sydney business date `2026-08-07`, this runbook is backed by
staging engineering evidence. It does not change the pending `2026-08-09`
Outcome into observed or production-readiness evidence.
