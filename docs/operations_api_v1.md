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

## Current implementation boundary

The contract, adapter, infrastructure template, plan-first deployment tool, and
browser client are implemented in the repository. Decision Queue reads the
operational queue and Action Board can approve, reject, or complete an Action
when the build has an internal HTTPS API URL and the authenticated host has put
its short-lived access token in session storage. Without both conditions the
product remains in read-only demonstration mode and sends no request.

The stack has not yet been deployed or connected to an approved identity
provider/origin, so runtime AWS authorization and recovery evidence remain the
next release gate. Public GitHub Pages must be built without the internal API
URL and cannot submit these mutations.
