# Internal Operations API v1

This is the authenticated, staging-only boundary between the internal Decision
Queue / Action Board and the private append-only Action mutation function.
Public GitHub Pages is not an API client and receives no write permission.

## Roles and permissions

| Role | Read queue | Approve | Reject | Complete |
| --- | --- | --- | --- | --- |
| `viewer` | yes | no | no | no |
| `operator` | yes | no | no | yes |
| `approver` | yes | yes | yes | no |
| `administrator` | yes | yes | yes | yes |

API Gateway validates the JWT issuer and audience. The adapter obtains the
actor from signed `name` or `email`, the stable identity from `sub`, and roles
from `cognito:groups`/`groups`. Client-supplied actor names are never trusted.

The internal build sets `NEXT_PUBLIC_GLAP_OPERATIONS_API_URL` to the exact API
origin. Its approved authentication shell supplies the short-lived access token
under the session-storage key `glap.internal.operations.access_token`; the
client does not persist it in local storage. Token acquisition and refresh stay
owned by that shell and are not simulated by the public demonstration.

## Endpoints

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
Errors use `invalid_request`, `forbidden`, `not_found`, or
`service_unavailable`; responses are `no-store` and never expose AWS IDs.

## Reliability and recovery

The API has bounded concurrency plus failure and throttling alarms. The stack
also provisions an encrypted DLQ, but API Gateway invokes Lambda synchronously,
so that DLQ is not evidence of synchronous API request recovery; those failures
are covered by alarms, logs, client retries, and idempotent reconciliation.
Synchronous callers must retry only with the same request ID. A timeout is
reconciled by repeating that ID; the mutation
audit table returns the original event rather than appending a duplicate.
Operators should stop retries on validation or authorization errors and use
Pipeline Health for service failures. Deployment remains manual and staging
only, with no recurring schedule or production alias.

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
public GitHub Pages. Decision Queue reads the
operational queue and Action Board can approve, reject, or complete an Action
after an administrator creates a user and assigns the appropriate group. The
browser obtains its short-lived access token through Cognito and keeps it only
in session storage. Without the internal build-time configuration, the public
product remains in read-only demonstration mode and sends no request.

The dedicated identity and hosting stack is implemented but not yet deployed.
After it is deployed, the Operations API plan reads its protected outputs by
known stack name, masks them, and retains candidate discovery only as a fallback.
Runtime AWS authorization and recovery evidence remain the next release gate.
Public GitHub Pages must be built without the internal API or Cognito variables
and cannot submit these mutations.
