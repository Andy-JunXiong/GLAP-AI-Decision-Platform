# Internal Operations API v1

This is the authenticated, staging-only boundary between the internal Risk
Hotspots / Decision Queue / Action Board journey and the governed lifecycle
tables plus private append-only Action mutation function.
Public GitHub Pages is not an API client and receives no write permission.

## Roles and permissions

| Role | Read risks | Read queue | Approve | Reject | Complete |
| --- | --- | --- | --- | --- | --- |
| `viewer` | yes | yes | no | no | no |
| `operator` | yes | yes | no | no | yes |
| `approver` | yes | yes | yes | yes | no |
| `administrator` | yes | yes | yes | yes | yes |

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

Risk and queue reads use the existing governed Glue/Athena tables and view. The API execution role
has `lakeformation:GetDataAccess` in addition to exact Glue table, Athena
workgroup, and S3 result/data permissions; it has no Glue writes or S3 deletes.
Because IAM permission to request Lake Formation data is not itself a table
grant, a Lake Formation administrator must also apply the exact database and
view permissions once per created execution role:

```powershell
.\\ops\\configure_operations_api_data_access.ps1

.\\ops\\configure_operations_api_data_access.ps1 `
  -Profile codex-readonly `
  -Apply
```

The script is plan-first and idempotent. It grants database `DESCRIBE` plus
`SELECT` and `DESCRIBE` on
`vw_lifecycle_action_current_staging_v1` and its required backing audit table,
`fact_lifecycle_action_audit_staging_v1`, and current-state table,
`fact_lifecycle_action_staging_v1`, plus the operational Alert table
`fact_lifecycle_alert_staging_v1`. Athena resolves stored views with the
caller's permissions, so the Action view and both backing tables are required.
The API role's Glue policy is restricted to those objects and the Alert table.
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
inside the workflow. After this one-time bootstrap, rerun the Operations API
workflow in `plan` mode. Deployment permissions remain a separate review gate.

## Current implementation boundary

The contract, adapter, API and identity infrastructure templates, plan-first
deployment tools, and browser client are implemented in the repository. The
dedicated identity stack creates an administrator-managed Cognito pool, four
role groups, an authorization-code-with-PKCE web client, and a manually deployed
Amplify staging branch. It has no repository connection and does not reuse
public GitHub Pages. Risk Hotspots reads current operational Alerts, a selected
Alert leads into Decision Queue through the shared `alert_fingerprint`, and
Action Board can approve, reject, or complete an Action after an administrator
creates a user and assigns the appropriate group. The
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
Risk and queue reads plus every role-specific allow/deny boundary, then removed
all four. All four Risk reads and queue reads returned HTTP 200. The Risk
response contained 15 open operational Alerts, and every returned `as_of_date`
was on or before the Sydney cutoff. The governed Alert table, Action view, and
its two direct backing tables have exact read-only Glue and Lake Formation
permissions; no write or grant option was added. Reliability verification replayed one existing
request sequentially and concurrently without adding an audit row, produced and
recovered from a controlled 503, observed bounded 429 responses, verified both
alarms moved through `ALARM` and back to `OK`, and confirmed the synchronous DLQ
remained empty. Public GitHub Pages is still built without the internal API or
Cognito variables, uses synthetic Risk examples, and cannot read private Alerts
or submit these mutations.

An IAM administrator can exercise the deployed allow/deny matrix without using
real email addresses by running `ops/verify_operations_roles_staging.ps1` first
in plan mode and then with `-Apply`. The script suppresses email delivery,
targets an unguessable missing Action ID, keeps passwords and tokens in process,
prints only HTTP statuses and boolean boundaries, and deletes all four temporary
users in a `finally` block.
