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

## Sustained authenticated read-load plan

`docs/operations_authenticated_read_load_plan_v1.json` is the unexecuted,
staging-only plan for the production-readiness sustained-read gate. Validate it
locally with:

```powershell
py -3.11 .\ops\validate_operations_authenticated_read_load_plan.py
```

This command performs no network request, identity operation, or external
write. The plan allowlists seven viewer-accessible `GET` projections and caps a
future run at 15 minutes, two requests per second, four concurrent requests,
and 1,800 total requests with no automatic retries. Any 401/403, non-allowlisted
route, unexpected method, bounded error/latency breach, or failed temporary-
identity cleanup must abort or fail the future run closed.

The companion baseline schema stores only aggregate status and latency totals
by route ID. Raw request records, tokens, claims, contact details, actors,
request/query IDs, Action/Outcome/shipment IDs, raw URLs, and infrastructure
identifiers are outside the format. Artifact persistence is not authorized by
the plan. A later staging run requires a separate named-human authorization;
the repository contract alone does not authorize traffic, temporary-user
creation, alarm/throttle changes, production access, or any mutation.

Exercise the pacing and aggregate-result contract entirely offline:

```powershell
py -3.11 .\ops\simulate_operations_authenticated_read_load.py `
  --scenario healthy

py -3.11 .\ops\simulate_operations_authenticated_read_load.py `
  --scenario reconciliation_failure
```

The simulator builds 1,740 deterministic in-memory request slots: one request
per second for the first minute and two per second for the remaining 14
minutes. It never sleeps, authenticates, resolves an origin, or sends a
request. Ten fixed scenarios cover every current abort class and validate the
future aggregate baseline candidate. Its report is repository engineering
simulation with `staging_runtime_evidence=false`; even a healthy simulated
completion cannot advance the sustained-read production-readiness gate.

Preview the staging runner without resolving AWS stacks, creating an identity,
or sending traffic:

```powershell
.\ops\run_operations_authenticated_read_load_staging.ps1
```

The default path revalidates the immutable plan and prints only its redacted
execution shape. It returns before AWS scope or HTTP execution is initialized.
`-Apply` alone fails closed. A separately named-human-authorized staging run
uses both gates:

```powershell
.\ops\run_operations_authenticated_read_load_staging.ps1 `
  -Apply -AuthorizedSustainedReadLoad
```

That apply command is an authority boundary, not a routine validation step. It
creates one email-suppressed `viewer`, holds its token only in process memory,
uses only the exact seven allowlisted `GET` routes, applies the frozen pacing
and abort gates, and confirms the temporary identity is absent in `finally`.
It validates the aggregate candidate through a temporary local file and removes
that file; neither raw records nor a baseline artifact are persisted. The
runner does not alter alarms or throttles, mutate an Action, access production,
or create a schedule. Implementation and default preview do not authorize or
prove an applied staging run.

The first separately authorized apply attempt on `2026-08-28` failed closed at
identity-cleanup confirmation. The temporary viewer deletion succeeded, but an
expected not-found response was treated as a terminating PowerShell native-
command error before the aggregate result could be reconciled. A separate
aggregate Cognito audit found zero remaining read-load identities. The runner
now confirms deletion by successfully listing users and matching the exact
temporary username locally. This correction is locally verified but has not
yet produced a baseline. Do not count the failed attempt as a sustained-load
baseline.

The separately authorized corrected retry also failed closed before baseline
validation: it reached aggregate serialization, but Windows PowerShell 5 does
not support the `utf8NoBOM` `Set-Content` value. Cleanup again left zero
read-load identities. The runner now writes UTF-8 without BOM through
`System.IO.File.WriteAllText` and `UTF8Encoding(false)`, clears the serialized
content, and still removes the temporary file in `finally`.

The separately authorized third attempt produced a validated aggregate and
exercised the intended latency stop: 20/20 responses were 2xx with zero 429,
other 4xx, or 5xx, while p95 latency was 6,177 ms. Because that exceeded the
frozen 3,000 ms threshold, the runner returned
`ABORTED / P95_LATENCY_EXCEEDED`, confirmed the temporary viewer was absent, and
persisted no raw records or artifact. Treat this as partial staging evidence,
not a completed sustained-load baseline. Diagnose the aggregate route-level
latency before another run; changing the threshold to manufacture a pass is not
authorized. Any new traffic requires new named-human authorization.

The runner now prints that route-level diagnostic only after the candidate
baseline passes schema and reconciliation validation. Each of the seven fixed,
safe route IDs gets a sample count, p50/p95/p99 latency, and a derived boolean
showing whether its p95 exceeds the unchanged 3,000 ms gate. It prints no path,
URL, token, identity, entity, request record, query ID, or infrastructure value.
The diagnostic is implemented and regression-protected. A separately
authorized `2026-08-29` apply exercised it once: all 20 responses were 2xx,
with zero 429, other 4xx, or 5xx responses, while overall p95 was 6,023 ms.
The route p95 results were `outcomes_pending` 7,054 ms, `risks_open` 6,023 ms,
`label_readiness` 4,167 ms, `actions_proposed` 2,553 ms, `learning_review`
2,538 ms, `actions_edited` 2,272 ms, and `pipeline_health` 797 ms. The first
three exceeded the unchanged 3,000 ms gate. The run aborted, viewer cleanup was
confirmed, and no artifact or completed baseline was retained. Do not rerun on
this evidence alone. The `outcomes_pending` correction now starts its two
unchanged required queries together with separate clients and exactly two
workers; either failure still rejects the complete response. Commit `66eeb52`
passed CI, and separately authorized manual run `33220634162` passed contract
tests and updated the private Operations API staging stack. The workflow called
no deployed endpoint and generated no post-deployment traffic, so live contract
preservation and latency effect remain unverified. Any bounded observation
remains separately authorized, must preserve the frozen workload and gate, and
must not be treated as an automatic entrance to further optimization.

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
