# Internal Operations API v1

This is the authenticated, staging-only boundary between the internal Risk
Hotspots / Decision Queue / Action Board / Outcome Review / Network Drill-down / Forecast Accuracy
journey and the
governed lifecycle tables plus private append-only Action mutation function.
Public GitHub Pages is not an API client and receives no write permission.

## Roles and permissions

| Role | Read risks/queue/outcomes | Read forecasts/health | Read network aggregate | Read shipment entities | Approve | Reject | Complete |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `viewer` | yes | yes | yes | no | no | no | no |
| `operator` | yes | yes | yes | yes | no | no | yes |
| `approver` | yes | yes | yes | yes | yes | yes | no |
| `administrator` | yes | yes | yes | yes | yes | yes | yes |

API Gateway validates the JWT issuer and audience. The adapter obtains the
actor from signed `name`, `email`, or Cognito access-token `username` claims,
the stable identity from `sub`, and roles from `cognito:groups`/`groups`.
Client-supplied actor names are never trusted.

The internal build sets `NEXT_PUBLIC_GLAP_OPERATIONS_API_URL` to the exact API
origin. Its approved authentication shell supplies the short-lived access token
under the session-storage key `glap.internal.operations.access_token`; the
client does not persist it in local storage. Token acquisition and refresh stay
owned by that shell and are not simulated by the public demonstration.

## Endpoints

`GET /v1/risks?status=OPEN&limit=50` returns at most 100 latest operational
Alert records. The server uses the current Australia/Sydney date as its cutoff,
requires `OPERATIONAL` scope and execution mode plus `ACTUAL_CALENDAR` time
basis, and excludes later-dated rows. `status` may be `OPEN` or `RESOLVED`.
The `alert_fingerprint` in each item is the same governed key carried into a
downstream Action.

`GET /v1/actions?status=PROPOSED&limit=50` returns at most 100 operational,
actual-calendar Action records. The v1 response is
`{"schema_version":"operations-api.v1","items":[],"next_token":null}`.

`GET /v1/outcomes?status=PENDING&limit=50` returns the latest operational
Outcome version for each completed Action, bounded by the current Sydney date.
Pending rows must have no `observed_date` or `effect_pct` and are labelled
`NOT_OBSERVED`. Closed outcomes are returned only when `observed_date` is on or
before the cutoff and are labelled `OBSERVED_ACTUAL_CALENDAR`. Supported status
filters are `PENDING`, `SUCCESSFUL`, `PARTIALLY_SUCCESSFUL`, `FAILED`, and
`INCONCLUSIVE`.

`GET /v1/pipeline-health` returns the sanitized six-stage controller status and
ten quality checks without S3 paths, Lambda names, ARNs, or raw errors. A
future logical date can never be returned as current operational health.

`GET /v1/forecasts` reads only the operational, actual-calendar multimodal
feature view through the current Sydney cutoff. Its historical window remains
labelled synthetic operational-calendar engineering evidence. Seven-day points
are returned only after 28 complete eligible dates and are isolated as a
system-derived staging `FUTURE_SIMULATION` scenario with
`MODEL_PROJECTION` time basis, `ADVISORY_FORECAST_NOT_OBSERVED` points, and no
production effect. Rolling accuracy requires at least seven past-only holdouts;
it never authorizes model promotion.

`GET /v1/network?mode=AIR&provider=DHL&lane=PVG-SYD` returns at most 100
provider/lane aggregates from the latest snapshot of each shipment. All four
internal roles may read this aggregate. The response states whether the caller
also has entity access, but never includes a shipment identifier, raw port,
cost, infrastructure identifier, or future-simulation row.

`GET /v1/shipments?provider=DHL&lane=PVG-SYD&limit=25` is the explicitly
authorised entity drill-down for `operator`, `approver`, and `administrator`;
`viewer` receives 403. It returns only the latest operational snapshot at or
before the Sydney cutoff, exposes a bounded operational field set, and uses an
opaque `next_token` for stable shipment-ID pagination. `mode`, `provider`,
`lane`, `status`, and page-token inputs are allow-listed before entering SQL.

`POST /v1/actions/{action_id}/events` accepts:

```json
{
  "operation": "APPROVE",
  "request_id": "stable-client-request-id",
  "reason": "Reviewed current operational evidence",
  "logical_run_date": "2026-08-07"
}
```

Operations are `APPROVE`, `REJECT`, or `COMPLETE`. Existing transition and
request-id idempotency rules remain authoritative in the mutation Lambda.
Errors use `invalid_request`, `forbidden`, `not_found`, `conflict`, or
`service_unavailable`; responses are `no-store` and never expose AWS IDs.

## Reliability and recovery

The API has API Gateway request-rate and burst limits plus failure and
throttling alarms. It does not reserve Lambda concurrency because the staging
account must retain its minimum unreserved concurrency. The stack also
provisions an encrypted DLQ, but API Gateway invokes Lambda synchronously,
so that DLQ is not evidence of synchronous API request recovery; those failures
are covered by alarms, logs, client retries, and idempotent reconciliation.
Synchronous callers must retry only with the same request ID. A timeout is
reconciled by repeating that ID; the mutation
audit table returns the original event rather than appending a duplicate.
Operators should stop retries on validation or authorization errors and use
Pipeline Health for service failures. Deployment remains manual and staging
only, with no recurring schedule or production alias.

Concurrent mutations are serialized by both request ID and the Action's prior
state. If another request consumes that state first, the losing request returns
409 instead of appending a second transition. The API emits a restricted
`ServiceUnavailable` metric for handled 503 responses, while a redacted API
Gateway access-log filter counts 429 responses. See the
[Operations API reliability runbook](runbooks/operations_api_reliability.md).

Risk, queue, and Outcome reads use the existing governed Glue/Athena tables and
view. The API execution role
has `lakeformation:GetDataAccess` in addition to exact Glue table, Athena
workgroup, and S3 result/data permissions; it has no Glue writes or S3 deletes.
Because IAM permission to request Lake Formation data is not itself a table
grant in an explicitly governed database, the plan-first access script detects
the database mode before applying exact permissions:

```powershell
.\\ops\\configure_operations_api_data_access.ps1

.\\ops\\configure_operations_api_data_access.ps1 `
  -Profile codex-readonly `
  -Apply
```

The script is plan-first and idempotent. For an explicitly Lake Formation
governed database, it grants database `DESCRIBE` plus
`SELECT` and `DESCRIBE` on
`vw_lifecycle_action_current_staging_v1` and its required backing audit table,
`fact_lifecycle_action_audit_staging_v1`, and current-state table,
`fact_lifecycle_action_staging_v1`, plus the operational Alert table
`fact_lifecycle_alert_staging_v1`, plus the operational Outcome table
`fact_lifecycle_outcome_staging_v1`, plus the Forecast feature view, the Network
source view, their context views, and their two lifecycle backing tables. Athena resolves stored views with the
caller's permissions, so the Action view and both backing tables are required.
The API role's Glue policy is restricted to those objects and the Alert and
Outcome tables. When the database explicitly uses `IAM_ALLOWED_PRINCIPALS`, as
the current staging database does, the script does not attempt an inapplicable
Lake Formation grant; the same exact table boundary is enforced by the Lambda
IAM policy.
The script grants no write access, no grant option, and no permission on other
tables or views. Its output omits protected resource identifiers.

## One-time protected-configuration discovery bootstrap

The shared staging OIDC role needs a separate read-only inline policy
before the plan can privately discover the approved Cognito and internal-origin
candidates. An IAM administrator first previews, then applies, the narrowly
scoped policy:

```powershell
.\\ops\\configure_operations_api_discovery.ps1

.\\ops\\configure_operations_api_discovery.ps1 \`
  -Apply
```

This does not replace the lifecycle deployer policy and grants no deployment
permission. It cannot modify the OIDC role itself, create schedules, invoke or
change Lambda functions, access S3, or update production aliases. Cognito and
origin access is read-only; resolved values remain masked and process-local
inside the workflow. The same policy permits `DescribeStacks` on the exact
Operations API target stack because `aws cloudformation deploy` reads its
current state before preparing a change set. After this one-time bootstrap, rerun the Operations API
workflow in `plan` mode. Deployment permissions remain a separate review gate.

## Dedicated staging deployment bootstrap

The Operations API uses a separate two-role deployment boundary instead of
reusing the Stateful Lifecycle stack policy. An IAM administrator previews and
applies it once:

```powershell
.\ops\configure_operations_api_deployer.ps1 `
  -ArtifactBucket <reviewed-staging-artifact-bucket>

.\ops\configure_operations_api_deployer.ps1 `
  -AdminProfile codex-readonly `
  -ArtifactBucket <reviewed-staging-artifact-bucket> `
  -Apply
```

The GitHub OIDC role receives this orchestration boundary as a separate
customer-managed policy so it does not compete with existing inline policies'
aggregate size quota. It can upload only under the reviewed artifact prefix,
operate change sets only for `glap-operations-api-staging`, and pass only
`glap-operations-api-cloudformation-staging-role` to CloudFormation. The
dedicated execution role can update only the stack's currently discovered
Lambda, runtime role, API Gateway ID, queue, log group, and alarms. It has no
top-level create/delete permission, schedule or alias permission, production
resource access, or ability to modify the GitHub role. A physical resource
replacement or new top-level resource type therefore fails closed until this
bootstrap is reviewed and reapplied.

## Current implementation boundary

The contract, adapter, API and identity infrastructure templates, plan-first
deployment tools, and browser client are implemented in the repository. The
dedicated identity stack creates an administrator-managed Cognito pool, four
role groups, an authorization-code-with-PKCE web client, and a manually deployed
Amplify staging branch. It has no repository connection and does not reuse
public GitHub Pages. Risk Hotspots reads current operational Alerts, a selected
Alert leads into Decision Queue through the shared `alert_fingerprint`, and
Action Board can approve, reject, or complete an Action after an administrator
creates a user and assigns the appropriate group. Outcome Review then links the
completed Action to its latest governed Outcome and separates pending rows from
mature actual-calendar evidence. The
browser obtains its short-lived access token through Cognito and keeps it only
in session storage. Without the internal build-time configuration, the public
product remains in read-only demonstration mode and sends no request.

As of the Australia/Sydney business date `2026-08-07`, the dedicated identity,
internal hosting, Operations API, alarms, and DLQ staging resources are deployed.
The internal frontend is manually deployed to Amplify and the API plan reads
protected identity outputs by known stack name and masks them. Runtime checks
confirm the site is reachable, unauthenticated API requests are rejected with
401, and CORS accepts only the exact internal origin. Run the same redacted
checks with `ops/verify_operations_staging.ps1`.

No persistent Cognito user is created automatically. An isolated runtime check
created one temporary viewer, operator, approver, and administrator, verified
Risk, queue, Outcome, Pipeline Health, Forecast, Network aggregate, and shipment
entity reads plus every role-specific allow/deny boundary, then removed all
four. All aggregate reads returned HTTP 200 for all four roles. Shipment entity
reads returned 403 for `viewer` and 200 for `operator`, `approver`, and
`administrator`, as designed. The Risk
response contained 15 open operational Alerts, and every returned `as_of_date`
was on or before the Sydney cutoff. The governed Alert table, Action view, its
two direct backing tables, Outcome table, and Forecast view chain have exact
read-only Glue IAM permissions. The database remains in its existing
IAM-allowed-principals mode; no write or grant option was added. Reliability
verification replayed one existing
request sequentially and concurrently without adding an audit row, produced and
recovered from a controlled 503, observed bounded 429 responses, verified both
alarms moved through `ALARM` and back to `OK`, and confirmed the synchronous DLQ
remained empty. Public GitHub Pages is still built without the internal API or
Cognito variables, uses synthetic Risk and Outcome examples, and cannot read
private Alerts or Outcomes or submit these mutations.

The Forecast runtime response is deliberately
`insufficient_operational_history`: the operational view currently has three
eligible actual-calendar dates, below both the 28-date advisory forecast gate
and the seven-holdout accuracy gate. It therefore returns no future points and
no accuracy metrics. This is a working fail-closed product state, not missing or
manufactured performance evidence.

The deployed Network response contained 12 latest-snapshot provider/lane
groups. Its viewer payload contained no shipment identifier and reported
`entity_access=false`. The operator entity sample passed the Sydney cutoff,
bounded-field, and next-page checks; costs, raw ports, infrastructure
identifiers, and future simulations were absent. The API and internal Amplify
page were deployed with the approved local `codex-readonly` management profile.
The previously blocked GitHub OIDC deployment path is now operational without
reusing or broadening the Stateful Lifecycle policy. Workflow run `31156819949`
used the customer-managed orchestration policy to upload the commit-scoped
artifact and operate the exact stack change set, then passed the dedicated
CloudFormation execution role. The stack reached `UPDATE_COMPLETE` and records
that role as its execution role. Post-deployment checks reconfirmed exact-origin
CORS, alarms, redacted logs, seven unauthenticated route rejections, the full
four-role read/mutation matrix, Network aggregate/entity boundaries, temporal
cutoffs, pagination, and removal of all four temporary users.

The Outcome runtime response contained one `PENDING` row and zero observed rows.
The pending row had no observation date or effect value and remained explicitly
`NOT_OBSERVED`; it is not performance, value, label-maturity, or promotion
evidence before its `2026-08-09` Sydney due date.

Post-handoff verification on the Sydney business date `2026-08-09` refreshed
the same authenticated Outcome Review and returned zero pending rows and one
observed `SUCCESSFUL` Action Outcome with a 20.0% simulated effect. This matured
the dated synthetic staging record without rewriting its Action or audit
history. It does not supply an observed shipment-delivery label, real logistics
performance, model readiness, production readiness, or policy authority.

The private frontend now exposes accessible loading, empty, stale, partial,
failed, sign-in-required, and idle states with retry and reduced-motion support.
The final `2026-08-07` deployment also corrected Windows ZIP entry separators:
the private staging verifier confirmed the root page, every referenced Next.js
JavaScript/CSS asset, and the accessible-state fingerprint are reachable. A
shell-only HTTP 200 can no longer pass the frontend release check.

An IAM administrator can exercise the deployed allow/deny matrix without using
real email addresses by running `ops/verify_operations_roles_staging.ps1` first
in plan mode and then with `-Apply`. The script suppresses email delivery,
targets an unguessable missing Action ID, keeps passwords and tokens in process,
prints only HTTP statuses and boolean boundaries, and deletes all four temporary
users in a `finally` block.
