# Internal Operations API v1

This is the authenticated, staging-only boundary between the internal Risk
Hotspots / Decision Queue / Action Board / Outcome Review / Learning Review / Network Drill-down / Forecast Accuracy
journey and the
governed lifecycle tables plus private append-only Action mutation function.
Public GitHub Pages is not an API client and receives no write permission.

## Roles and permissions

| Role | Read risks/queue/outcomes/learning | Read forecasts/health | Read network aggregate | Read shipment entities | Edit assignment | Approve | Reject | Complete |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `viewer` | yes | yes | yes | no | no | no | no | no |
| `operator` | yes | yes | yes | yes | yes | no | no | yes |
| `approver` | yes | yes | yes | yes | no | yes | yes | no |
| `administrator` | yes | yes | yes | yes | yes | yes | yes | yes |

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

For each current valid `OPEN` `SLA_BREACH` or `COST_ANOMALY`, the same response
includes a `decision_brief` using the versioned `decision-brief.v1` contract.
SLA validates the exact shipment-milestone/delay-metric pair and selects
`EXPEDITE_MILESTONE`. Cost validates `SHIPMENT_COST` / `TOTAL_COST` /
`cost_variance_pct` and selects `REVIEW_COST`. Both derive a bounded breach
margin, expose monitor and no-action alternatives, and fail closed on invalid
or mismatched inputs. Resolved and unsupported Alerts receive
`decision_brief: null`.

SLA reports no-action exposure in delay hours; Cost reports variance and
percentage-point margin without inventing currency. Cost binds the exact
`stateful-cost-variance.v1` calculation source and explicitly reports the
rate-card version as unavailable in the current Alert contract. Both keep
expected benefit `NOT_ESTIMATED`, `assumption_set_version = null`, and all
execution, Outcome, and financial-value authority false. The authenticated
cockpit can display either brief and navigate to the existing governed Action
Board, but reading a brief creates no Action or mutation. See
[`decision_brief_v1.md`](decision_brief_v1.md) and
[`cost_anomaly_decision_brief_v1.md`](cost_anomaly_decision_brief_v1.md).

`GET /v1/actions?status=PROPOSED&limit=50` returns at most 100 operational,
actual-calendar Action records. The v1 response is
`{"schema_version":"operations-api.v1","items":[],"next_token":null}`.
Supported states include `PROPOSED`, `EDITED`, `APPROVED`, `REJECTED`, and
`COMPLETED`; assignment fields are `action_owner` and `action_due_date`.
New eligible SLA proposals expose immutable `decision_brief_version`,
`selected_alternative`, and `selection_rationale`. The deployed Cost extension
uses the same fields with `REVIEW_COST` and includes the exact calculation
source version in its rationale. These values describe the deterministic
proposal, not human approval. Existing Actions, including pre-release Cost
Actions, may return null binding fields and are never backfilled by inference.

`GET /v1/actions/{action_id}/evidence` returns one authenticated, read-only
Action–Outcome evidence chain. It joins the immutable Action table to its
append-only `EDIT` / `APPROVE` / `REJECT` / `COMPLETE` audit events and the
latest eligible Outcome in one bounded Athena query. All three sources must be
`OPERATIONAL`, `ACTUAL_CALENDAR`, and dated on or before the current Sydney
cutoff. Missing Actions return 404; unsafe identifiers fail before entering
SQL. Every internal role may read this chain because every role already has
both `actions:read` and `outcomes:read`.

The response distinguishes `ACTION_OPEN`, `ACTION_REJECTED`,
`ACTION_COMPLETED_AWAITING_OUTCOME`, `OUTCOME_PENDING`, and
`OUTCOME_OBSERVED`. A pending Outcome remains `NOT_OBSERVED` with no observation
date or effect. The governance block states that the proposal is immutable,
the Decision binding is immutable, the audit is append-only, and every Outcome is synthetic rather than real
logistics performance. Request IDs, scenario IDs, infrastructure identifiers,
and future-simulation rows are not returned.

The Action Board displays the immutable proposal binding beside the existing
audit events. The later named-human reason comes only from an append-only
`EDIT`, `APPROVE`, or `REJECT` event; the API does not pretend that a human
decision existed at proposal-generation time. The additive schema and view
change is defined in `sql/16_decision_action_binding_v1.sql`; a named human
applied it and all six aggregate checks returned zero on `2026-08-25`. The SLA
projection and private cockpit are deployed and reader/RBAC verified for both
SLA and Cost. The revised exact-pair aggregate validator has not run in staging,
the Generator has not been invoked, and no bound Cost proposal was observed. See
[`decision_action_binding_v1.md`](decision_action_binding_v1.md).

The Cost reader release is runtime-deployed from commit `0e5b740`. CI
`32982375432` and plan `32982375374` passed; separately authorized Operations
API deploy `32983721998` completed the staging stack update. The named human
published the matching private cockpit, the read-only verifier passed all
configured identity/API/frontend/CORS/alarm/logging/redaction checks, and the
four-role matrix passed before removing all four temporary users. This proves
reader and RBAC behavior, not that a Cost Brief row exists; no lifecycle
continuation or bound Cost proposal was observed.

`GET /v1/outcomes?status=PENDING&limit=50` returns the latest operational
Outcome version for each completed Action, bounded by the current Sydney date.
Pending rows must have no `observed_date` or `effect_pct` and are labelled
`NOT_OBSERVED`. Closed outcomes are returned only when `observed_date` is on or
before the cutoff and are labelled `OBSERVED_ACTUAL_CALENDAR`. Supported status
filters are `PENDING`, `SUCCESSFUL`, `PARTIALLY_SUCCESSFUL`, `FAILED`, and
`INCONCLUSIVE`.

Each row now also reads nullable `decision_brief_version` and
`selected_alternative` from the immutable Action proposal joined by the
existing `action_id`. Both sides of the read-time join must remain operational,
actual-calendar, and cutoff-eligible. The fields are not copied into the
Outcome table. Legacy and pre-release `COST_ANOMALY` Actions remain null rather
than being backfilled by inference; a future eligible Cost proposal may carry
the exact new binding only after separately authorized source release and
Generator invocation. This enables private grouping by proposal contract but
does not establish human approval, execution, causality, real logistics
performance, or financial value. See
[`outcome_review_decision_provenance_v1.md`](outcome_review_decision_provenance_v1.md).

The same response now includes `cohort_summary` using
`outcome-cohort-summary.v1`. A separate unbounded aggregate query groups only
latest-version observed Outcomes with numeric effects and complete immutable
Action bindings by `decision_brief_version` and `selected_alternative`. It
returns sample count, result-state counts, and minimum/average/maximum
descriptive effect percentages. Pending, future-simulation, and unbound rows
are excluded. The server rejects unreconciled counts and invalid distributions.
These synthetic descriptions are not causal estimates, realised financial
value, real logistics performance, model readiness, or policy authority. See
[`decision_contract_outcome_cohort_v1.md`](decision_contract_outcome_cohort_v1.md).

Each cohort and the top-level summary also expose
`outcome-cohort-evidence-sufficiency.v1`. The project owner approved the
versioned `outcome-cohort-threshold-contract.v1` on `2026-08-25`: each cohort
requires at least 20 observed Outcomes and two represented result states. The
runtime reports `HUMAN_APPROVED_CONTRACT` and evaluates both gates; partial or
invalid configuration still fails closed. It does not choose thresholds
automatically, and passing permits descriptive synthetic comparison only. See
[`outcome_cohort_evidence_sufficiency_v1.md`](outcome_cohort_evidence_sufficiency_v1.md).

Each cohort also includes `outcome-cohort-evidence-gap.v1`, which reports the
non-negative arithmetic shortfall to the approved 20/2 targets. Zero means the
minimum descriptive evidence shape is met; a positive value is not an
instruction to create Outcomes or advance the lifecycle. Collection,
creation, and lifecycle-continuation authority remain false. See
[`outcome_cohort_evidence_gap_v1.md`](outcome_cohort_evidence_gap_v1.md).

The response's `outcome-cohort-descriptive-comparison.v1` projection remains
unavailable until at least two cohorts independently pass the gate. When
available, it shows only status percentages and effect ranges for eligible
cohorts. It produces no ranking, preferred alternative, causal superiority,
statistical significance, or Action recommendation. See
[`outcome_cohort_descriptive_comparison_v1.md`](outcome_cohort_descriptive_comparison_v1.md).

Every cohort actually displayed in that comparison includes
`outcome-cohort-comparison-provenance.v1`. It binds the aggregate to its
immutable Decision Brief version and selected alternative, Sydney cutoff,
evidence class, aggregation contract, and approved threshold contract while
keeping Action, Outcome, and shipment identifiers unexposed. See
[`outcome_cohort_comparison_provenance_v1.md`](outcome_cohort_comparison_provenance_v1.md).

Each displayed comparison item also includes a deterministic
`outcome-cohort-comparison-fingerprint.v1` SHA-256 digest over its metrics and
provenance. The fingerprint supports response-content consistency checks only;
it is not a digital signature, source-authenticity attestation, or business-
validity proof. See
[`outcome_cohort_comparison_fingerprint_v1.md`](outcome_cohort_comparison_fingerprint_v1.md).
Percentage inputs use fixed two-decimal strings, including normalized zero,
before sorted compact JSON serialization so a browser can reproduce the same
bytes as the server.

The private cockpit's
`outcome-cohort-comparison-verifier.v1` recomputes that digest with browser Web
Crypto. Covered metrics and provenance remain hidden until the result is
`VERIFIED`; missing crypto support, contract drift, malformed values, trust-
flag expansion, or digest mismatch all fail closed. Verification remains an
unsigned content-consistency check and issues no additional API request. See
[`outcome_cohort_comparison_verifier_v1.md`](outcome_cohort_comparison_verifier_v1.md).

Verifier results include one local reason code from
`outcome-cohort-comparison-diagnostics.v1`. The cockpit maps it to fixed safe
copy while continuing to withhold covered content. It never exposes a raw
exception, canonical payload, covered value, or computed digest, and it creates
no telemetry or persistence. See
[`outcome_cohort_comparison_diagnostics_v1.md`](outcome_cohort_comparison_diagnostics_v1.md).

`outcome-cohort-comparison-retry.v1` permits one browser-local re-verification
per cohort and loaded response only for `CRYPTO_UNAVAILABLE` or
`VERIFICATION_ERROR`. Structural failures never receive the control. The retry
reuses the same response object, returns content to the hidden pending state,
and performs no API request. See
[`outcome_cohort_comparison_retry_v1.md`](outcome_cohort_comparison_retry_v1.md).

Before the cockpit or per-cohort verifier iterates a present comparison view,
`outcome-cohort-comparison-envelope-validator.v1` checks the exact schema,
status/count reconciliation, descriptive-only scope, all-false governance, and
cohort-array shape. A present malformed envelope fails the complete Outcome
load closed with fixed safe copy. Omission remains a supported partial-data
state for older API builds. See
[`outcome_cohort_comparison_envelope_validator_v1.md`](outcome_cohort_comparison_envelope_validator_v1.md).

`GET /v1/learning` returns the governed bridge from observed Outcomes to a
review-only policy proposal. One bounded Athena query de-duplicates Outcomes,
counts only closed `OPERATIONAL` / `ACTUAL_CALENDAR` records observed on or
before the current Sydney cutoff, and attaches the latest cutoff-eligible row
from `fact_policy_proposal_staging_v1`. Pending Outcomes, future simulations,
and post-cutoff observations never count toward the configured 20-Outcome
gate.

Below the gate, the response is `INSUFFICIENT_ELIGIBLE_OUTCOMES` and reports
the remaining count. Meeting the count without a stored proposal is
`ELIGIBLE_AWAITING_PROPOSAL`; an existing proposal is
`POLICY_PROPOSAL_RECORDED`. The governance contract always states that human
review is required, automatic activation is false, deterministic rules remain
in force, and the synthetic Outcome summary is not real logistics performance.
The 20-record threshold is `SYNTHETIC_POLICY_REVIEW_ONLY`; meeting it proves
neither model readiness nor production readiness. This endpoint has no approval
or activation mutation.

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

`GET /v1/label-readiness` returns the aggregate-only supervised-label evidence
gate by transport mode and provider. It reads only
`vw_multimodal_outcome_label_v1`, derives the current Sydney cutoff on the
server, and requires `OPERATIONAL` / `ACTUAL_CALENDAR` rows observed through
that cutoff. The query returns no shipment, Action, Outcome, infrastructure, or
storage identifiers. Pending labels are reported for coverage but excluded
from every target; future simulations are absent.

The frozen thresholds remain 200 observed labels per provider, 20 positive and
20 negative labels for each binary target, and 10 distinct observed
cost-variance values. The response reports exact remaining counts and target-
specific blockers for SLA breach, delay risk, and cost variance. Passing these
thresholds permits governed supervised evaluation only. The endpoint cannot
start training, promote a model, deploy prediction, create a schedule, or
establish production readiness. All four authenticated roles receive the same
aggregate-only read surface through the explicit `labels:read` permission.

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
  "reason": "Reviewed current operational evidence"
}
```

Operations are `EDIT`, `APPROVE`, `REJECT`, or `COMPLETE`. Existing transition and
request-id idempotency rules remain authoritative in the mutation Lambda.
Errors use `invalid_request`, `forbidden`, `not_found`, `conflict`, or
`service_unavailable`; responses are `no-store` and never expose AWS IDs.

The repository v1 extension accepts `EDIT` from `PROPOSED`:

```json
{
  "operation": "EDIT",
  "request_id": "stable-client-request-id",
  "reason": "Assigned for operational follow-up",
  "action_owner": "Jordan Lee",
  "action_due_date": "2026-08-09"
}
```

The API derives `logical_run_date` from the current Australia/Sydney date and
does not trust a client-supplied operational date. `EDIT` appends an immutable
audit event and moves the Action to `EDITED`; it
does not approve it. The owner must be a named human and the due date cannot
precede the operational date. `EDITED` may then be approved or rejected by an
authorised approver. This extension is implemented and locally verified in the
repository. A named human applied `sql/15_action_assignment_v1.sql` to isolated
staging on 2026-08-13; all five post-migration checks returned zero. The API and
private frontend were subsequently released through separately approved
staging-only paths. Assignment runtime and four-role checks passed. A named
operator subsequently recorded one real staging `EDIT`; the Action resolved to
`EDITED`, but the HTTP response was 503 because the mutation Lambda returned a
non-JSON-serializable Python `date`. Commit `763a817` fixed only the response
boundary. The fix was released through the protected narrow path on
2026-08-23; the original request-ID retry returned HTTP 200 with
`idempotent_replay=true` and retained one audit row. A different named
approver then selected `APPROVE`. Read-only reconciliation found one `EDIT`,
one `APPROVE`, two distinct named actors, one current `APPROVED` row, and an
unchanged assignment. No `COMPLETE` or Outcome creation occurred.

A local-only `COMPLETE`-to-Outcome canary package bound the next use of this
endpoint to the already verified `APPROVED` source state. It requires a
separately authorized `operator` or `administrator`, the existing signed-claim
actor derivation, the API-derived Sydney logical date, and same-request-ID
retry semantics. The package renders only a redacted plan and grants no
mutation authority. Pending and observed Outcome generation require their own
later actual-calendar lifecycle-continuation authorizations. Future
simulation, deployment, production, schedules, policy activation, and model
promotion remain excluded. See
[`action_complete_outcome_canary.md`](action_complete_outcome_canary.md).
An aggregate-only staging preflight passed on `2026-08-25` with one eligible
`APPROVED` candidate, the exact prior `EDIT`/`APPROVE` history, no
`REJECT`/`COMPLETE`, a matching assignment, and no Outcome. It did not call
this mutation endpoint and printed no protected identifiers.
After explicit project-owner authorization on `2026-08-25`, a signed-in named
human used the private Action Board to submit `COMPLETE`; the agent did not
click or submit it. The post-`COMPLETE` aggregate-only reconciler then passed
all eight checks with one current `COMPLETED` candidate, the exact prior
`EDIT`/`APPROVE` history, zero `REJECT`, exactly one named-human `COMPLETE`,
the unchanged assignment, and zero Outcomes. It printed no protected
identifiers. The one-time completion authority is consumed.
After a new explicit project-owner authorization, the agent used the named
GitHub session to trigger manual workflow run `32803181376` from commit
`291fffc`. It extended only `2026-08-25` in `OPERATIONAL` /
`ACTUAL_CALENDAR` mode with one date, no seed, and no future simulation. The
pending-Outcome aggregate-only verifier then passed all six checks: one
completed candidate, one `PENDING` / `SIMULATED` Outcome, null observed date
and effect, and the three-day due-date rule. It printed no protected
identifiers. The pending record is not observed evidence. Its system-computed
`2026-08-28` due date is a future gate, and the later continuation remains
separately unauthorized.

The local observation package is now implemented. Its system-derived Sydney
due-date checker blocked as expected on `2026-08-25` before any AWS setup or
call. Its aggregate-only post-observation reconciler will select only the
latest Outcome version, require a closed simulated result within the due-date
and current-cutoff window, verify the Learning eligible count increases from 1
to 2, and require zero policy proposals or activations while the 20-Outcome
threshold remains unmet. It has not run and does not claim an observed result.

The ordered release, validation, role-check, canary, and evidence-preserving
rollback boundary is defined in
[`action_assignment_staging_rollout.md`](action_assignment_staging_rollout.md).
The narrow Action mutation Lambda release path completed on 2026-08-10; the
whole stateful stack must not be updated as an implicit substitute. Its
CloudFormation change-set design is recorded in
[`action_mutation_staging_release_rfc.md`](action_mutation_staging_release_rfc.md)
and future release writes still require separate approval.

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

### Offline production-readiness evidence

`ops/evaluate_operations_production_readiness.py` reconciles the versioned
`docs/operations_production_readiness_evidence_v1.json` manifest without any
network request or external write. It reuses the bounded staging reliability
evidence above rather than rerunning failure injection. As of `2026-08-25`,
four of ten required gates are runtime-verified in staging and six remain
blocked or incomplete, so the only valid result is
`NOT_READY_INCOMPLETE_EVIDENCE`. The report is synthetic engineering evidence;
it is not a production SLA, real logistics performance, deployment approval,
or production-readiness decision.

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

The Action evidence route is another `AWS::ApiGatewayV2::Route` inside the
already discovered private API ID, so the existing API-scoped execution policy
can create it without granting Lambda, queue, schedule, alias, or production
resource creation. Release preflight verifies the immutable Action table,
Action audit table, and Outcome table explicitly. Before the authorized release,
the staging and four-role verifiers retained the prior deployed baseline; the
current post-release verification opts in with `-RequireActionEvidence`.
The private frontend packager also rejects a build that lacks the evidence-chain
controls or synthetic-performance disclosure.

The Learning route uses the same existing API-scoped route permission and adds
only exact read metadata access for the already governed policy-proposal table.
The plan workflow preflights that fourth closed-loop table, and the discovery
and Lake Formation helpers name it explicitly without write or grant-option
permission. Before the separately authorized release, verification remained on
the older baseline; the current deployed baseline requires
`-RequireLearningEvidence` in both staging verifiers. The frontend packager
rejects an internal build that omits the
Learning Review or its named-human activation disclosure.

## Current implementation boundary

The contract, adapter, API and identity infrastructure templates, plan-first
deployment tools, and browser client are implemented in the repository. The
dedicated identity stack creates an administrator-managed Cognito pool, four
role groups, an authorization-code-with-PKCE web client, and a manually deployed
Amplify staging branch. It has no repository connection and does not reuse
public GitHub Pages. Risk Hotspots reads current operational Alerts, a selected
Alert leads into Decision Queue through the shared `alert_fingerprint`, and
Action Board can assign/edit, approve, reject, or complete an Action after an administrator
creates a user and assigns the appropriate group. Outcome Review then links the
completed Action to its latest governed Outcome and separates pending rows from
mature actual-calendar evidence. The deployed private API and frontend now
support the assignment contract. The assignment-specific runtime verifier and
four-role allow/deny matrix passed on 2026-08-13, and independent cleanup
reconciliation found zero temporary role-check users.
The browser obtains its short-lived access token through Cognito and keeps it only
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

The `2026-08-13` assignment run confirmed viewer denial, operator `EDIT`
permission without approval permission, approver approval permission without
`EDIT`, and administrator access to all four operations. It targeted an
unguessable missing Action ID, appended no real audit event, and removed all
four temporary users. The named-human Action canary remains separate.

The named-human canary began later on `2026-08-13`. Aggregate reconciliation
confirmed exactly one valid `EDIT`, one request ID, one affected Action, and one
current `EDITED` match. The failed response did not add a duplicate. The
operator session was globally signed out during containment, and the identity
was reconciled to the operator group only. No access token or private Action
identifier is retained in repository evidence. On `2026-08-23`, separately
approved Prepare run `32623784739` and Execute run `32624244648` released the
response fix with the stack at `UPDATE_COMPLETE` and no production effect. The
same named operator's stable retry returned HTTP 200 and reused the original
event; a different named approver then approved the `EDITED` Action. Final
reconciliation retained one `EDIT`, one `APPROVE`, zero `REJECT`, zero
`COMPLETE`, two named actors, and the original assignment.

The cockpit previously refreshed the Action Board after a successful mutation
but left an already expanded Evidence chain in its pre-mutation local state.
The repository frontend now treats mutation success explicitly and reloads the
selected Action evidence after the Board refresh. A named human published the
clean frontend tree at commit `adfd2a5` to private staging. The read-only
staging verifier passed the Action assignment, Action evidence, and Learning
evidence gates, including site/assets, unauthenticated `401`, exact-origin
CORS, alarms, redacted logging, and throttling checks. No Action mutation was
performed during this release verification, so the deployed bundle and
governance controls were verified independently of the interaction. On
`2026-08-24`, a separately authorized named operator opened an eligible
`PROPOSED` Action's Evidence chain, submitted one `EDIT`, and reported both the
Board transition to `EDITED` and automatic appearance of the new event in the
already expanded chain. The aggregate-only read reconciler then confirmed one
matching `EDIT`, one Action, one request ID, one named actor, a valid
assignment, current `EDITED` state, and a matching current assignment without
printing any protected identifier. No approval, rejection, completion, or
Outcome was authorized as part of this interaction.

The Action–Outcome evidence endpoint and cockpit timeline were merged to `main`
and source-verified on `2026-08-23`. After separate named-human staging release
authorization, workflow run `32621697316` deployed the private Operations API
successfully and the named human deployed the matching private Amplify
cockpit. Both explicit post-release verifiers passed. The four-role check
returned the expected read access, retained viewer shipment-entity denial,
returned `404` for an unguessable missing Action, and removed all four temporary
users. No real Action was mutated.

On `2026-08-26`, plan run `32972934184` validated the current Decision Truth
reader package from commit `a3fe692` and explicitly skipped deployment.
Separately authorized run `32973297196` then deployed the authenticated staging
API. The first matching private-frontend release attempt stopped at Next.js type
checking before archive creation or any Amplify deployment. The discriminated
verification-result fix in commit `2627da6` passed frontend lint, the internal
production build, all five frontend tests, and CI run `32975380386`; the named
human then published the corrected private cockpit without printing protected
origin or deployment identifiers.

The post-publication read-only verifier passed every configured frontend, API,
CORS, alarm, logging, and redaction check. The separately human-run four-role
verifier passed reader, mutation-boundary, response-contract, temporal,
governance, and redaction checks and removed all four temporary users. All four
roles could read Action, Learning, and label-readiness evidence; the viewer
remained denied shipment-entity access and Action mutation, while the other
role boundaries matched the contract. No real Action was mutated. Runtime
reads reported an `ACTION_OPEN` chain with zero events and no Outcome, Learning
at `INSUFFICIENT_ELIGIBLE_OUTCOMES` with 1/20 eligible Outcomes and no proposal,
and no ready provider group or eligible label-readiness target. The Generator
was not invoked, so this verifies the private reader and RBAC boundary, not a
bound Decision proposal or eligible comparison cohort.

The Outcome-to-Learning evidence endpoint and private Learning Review were
released in the same staging-only change and passed explicit
`-RequireLearningEvidence` checks in both verifiers. Runtime evidence reported
`INSUFFICIENT_ELIGIBLE_OUTCOMES`, `1/20` eligible observed Outcomes, and no
proposal present. The endpoint exposes the governed threshold and
policy-proposal record read-only; it neither approves nor activates a proposal.
