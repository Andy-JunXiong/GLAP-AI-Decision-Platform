# Stateful lifecycle AWS deployment

## Current delivery boundary

This repository slice creates the versioned lifecycle, route, rate, tier and FX
contracts; provider and transport-mode contracts; an isolated staging
snapshot/event/cost/metric/signal boundary; a
deterministic state transition and expected-cost engine; a retry-safe Athena
persistence adapter; an unscheduled staging Lambda template; and fail-closed
validation SQL. It also includes six read-only v2 compatibility views and a
separate unscheduled manual controller/quality-gate integration path.
It does not replace `glap-daily-incremental-generator-v2` or write to governed
v2 production tables.

The P2P contract has exactly one immutable `etd` and `eta`. `atd` and `ata` are
written once when observed. Generic Origin handover and Destination release
milestones support both modes; Ocean retains gate-in/discharge aliases while
Air uses airport receipt/cargo-availability events and chargeable-weight cost.

## Files

- `sql/04_stateful_lifecycle_config.sql` creates configuration and staging tables.
- `sql/05_stateful_lifecycle_seed.sql` installs the approved initial route and
  synthetic rate versions.
- `sql/06_stateful_lifecycle_validation.sql` reconciles snapshot, milestones,
  versions, tiers and cost detail.
- `sql/07_stateful_lifecycle_compatibility_views.sql` exposes the isolated data
  through six read-only views matching the deployed v2 input shapes.
- `sql/08_stateful_lifecycle_multimodal_seed.sql` idempotently installs Maersk
  and KN Ocean plus DHL Air provider, route, target, and synthetic rate profiles.
- `lambda/glap_stateful_lifecycle_generator.py` provides deterministic replay,
  seed population, daily progression, expected-cost calculation, lifecycle SLA
  metrics and auditable SLA/cost signal candidates.
- `lambda/glap_lifecycle_athena_adapter.py` reads governed configuration and the
  prior active snapshot, then performs retry-safe staging Iceberg merges.
- `lambda/glap_quality_contracts.py`, `lambda/glap_data_quality_gate.py`, and
  `lambda/glap_pipeline_controller.py` enforce the named lifecycle and
  compatibility contracts in the isolated manual chain.
- `ops/deploy_stateful_lifecycle.ps1` renders and optionally executes the schema.
- `ops/deploy_stateful_lifecycle_stack.ps1` packages the two-module Lambda and
  deploys the isolated IAM/Lambda/alarm CloudFormation stack.
- `infrastructure/stateful-lifecycle-staging.yaml` creates unscheduled,
  prefix-scoped generator, controller, quality-gate, roles, and alarm resources.
- `ops/replay_stateful_lifecycle_staging.ps1` performs a plan-only-by-default
  sequence of governed logical-date invocations.
- `ops/validate_stateful_lifecycle_staging.ps1` runs both reconciliation query
  sets for every replay date and stops on the first non-zero failure count.
- `.github/workflows/deploy-stateful-lifecycle-staging.yml` provides the manual
  GitHub OIDC plan/deploy/replay/validate path.

The local `plan-stack-only` / `deploy-stack-only` pair adds a plan-first
Decision Truth producer release path without lifecycle execution. Both require
separate manual dispatches. The corrected plan action creates an unexecuted
temporary change set, prints only logical resource ID, type, action, and
replacement status, enforces the exact-one-generator boundary, and deletes the
change set without uploading an artifact. The deploy action uploads only the
commit-addressed generator artifact, preserves the existing controller and
quality-gate artifact parameters, and fails unless the inspected change set
contains exactly one non-replacing `LifecycleGeneratorFunction` modification. Neither
action applies schema, seeds data, replays dates, invokes an integration date,
extends the controller, changes an alias, or creates a schedule. The options
were delivered in commit `59a9eaa`. Human run `32905914076` failed closed at
the exact change-set gate before execution; the temporary change set was
deleted, the uploaded generator artifact remained inactive, and no stack
resource changed. This source-control correction delivers the diagnostic plan
path but does not dispatch it.

All PowerShell deployment commands are plan-only unless `-Apply` is explicit.
They use `AWS_PROFILE` when it exists and otherwise use the temporary AWS
credentials supplied by GitHub OIDC.
The Iceberg DDL uses Athena engine v3 type names such as `int` rather than the
Trino alias `integer`, which Athena rejects in `CREATE TABLE` column contracts.
The deployer inspects existing Glue columns and adds only missing multimodal
columns before applying the idempotent configuration merge and recreating the
read-only compatibility views.

## Multimodal simulation contract

- New bookings use a deterministic 17-shipment cycle: Maersk Ocean `7/17`, KN
  Ocean `7/17`, and DHL Air `3/17` (17.65% Air).
- Ocean keeps port nodes, `40HC`, container quantities, gate-in/discharge, and
  per-container charges.
- Air uses airport nodes, pieces, gross/volumetric/chargeable weight,
  origin-received/flight/cargo-available milestones, and per-chargeable-kg
  charges.
- Common P2P ETD/ATD/ETA/ATA and final delivery semantics remain unchanged.
- Provider rates, transit targets, and operating-carrier labels are explicitly
  simulated and are not live quotes, schedules, or performance claims.
- The fail-closed contract includes provider coverage, provider-to-mode/cargo
  semantics, and a 28-day Air booking-share check after a 70-booking warm-up.

## GitHub staging environment

The manual workflow uses the existing protected `staging` Environment and
requires these private repository/environment variables:

| Variable | Purpose |
| --- | --- |
| `AWS_STAGING_ROLE_ARN` | OIDC role assumed only by the staging workflow |
| `AWS_LIFECYCLE_CF_EXECUTION_ROLE_ARN` | CloudFormation-only service role for the complete lifecycle staging stack |
| `AWS_LIFECYCLE_ARTIFACT_BUCKET` | Existing private bucket for the Lambda ZIP |
| `AWS_LIFECYCLE_DATA_BUCKET` | Existing private bucket; writes are restricted to `stateful-lifecycle-staging/data/` |
| `AWS_LIFECYCLE_ATHENA_OUTPUT` | Prefix-scoped private Athena result URI; `AWS_OPS_ATHENA_OUTPUT` is the fallback |

Run `action=plan` first. The first `deploy-replay-validate` execution must set
`load_initial_seed=true`; repeat executions leave it false. The workflow does
not create a schedule, modify a production alias, or connect the function to
the production controller.

After successful Decision Truth schema validation, first use only
`action=plan-stack-only`, `execution_mode=OPERATIONAL`, an empty scenario ID,
and `load_initial_seed=false`. Review that completed run, then separately decide
whether to dispatch `action=deploy-stack-only` with the same bounded inputs.
Neither option consumes the replay or integration date fields or can establish
a bound-Action runtime canary.

### One-time deployer permission bootstrap

The existing `glap-github-staging-deployer` role also supports older staging
release paths. Before a lifecycle workflow run that needs a new catalog object,
an IAM administrator must reconcile the lifecycle-specific permissions. Review
the plan first:

```powershell
.\ops\configure_stateful_lifecycle_deployer.ps1 `
  -AdminProfile "<iam-admin-profile>" `
  -ArtifactBucket "<private-artifact-bucket>" `
  -LifecycleDataBucket "<private-data-bucket>" `
  -AthenaOutputUri "s3://<private-query-bucket>/athena-results/"
```

The plan derives the exact current policy set and checks all three documents
against the non-adjustable `6,144`-character customer-managed-policy limit. It
requires at least 512 characters of headroom in each document and checks that
the role will have no more than ten attached managed policies.
Apply only after checking the three prefixes, role name, reported policy sizes,
and attachment count:

```powershell
.\ops\configure_stateful_lifecycle_deployer.ps1 `
  -AdminProfile "<iam-admin-profile>" `
  -ArtifactBucket "<private-artifact-bucket>" `
  -LifecycleDataBucket "<private-data-bucket>" `
  -AthenaOutputUri "s3://<private-query-bucket>/athena-results/" `
  -Apply
```

The script splits the lifecycle permission set into three customer-managed
policies: Catalog covers the exact Athena workgroup, Glue database/table/view
inventory, and Lake Formation data access; Storage covers only the reviewed S3
prefixes; Deployment covers the isolated CloudFormation stack, staging Lambda
functions, exact execution roles, and staging alarms. It stages and verifies
all managed policies before removing the superseded
`GLAPStatefulLifecycleStagingDeploy` inline policy. If migration fails before
that final removal, the legacy inline policy remains and newly activated
versions are rolled back where possible. No managed policy grants the GitHub
role permission to modify its own policies. The set grants no Scheduler action
and no production alias update. Re-run `action=plan` after the policies are
applied; do not start the one-time seed while plan is failing.
The execution role uses the fixed staging-only name
`glap-stateful-lifecycle-generator-staging-role`; this prevents CloudFormation
physical-name truncation from widening or bypassing the deployer policy scope.

### Lifecycle CloudFormation ownership bootstrap

The Action mutation Prepare/Execute path supplies a deliberately narrow service
role to the shared stack. Because AWS permanently associates that role with the
stack, full lifecycle maintenance must explicitly replace it with a separate
CloudFormation-only lifecycle role. Review its exact-resource plan first:

```powershell
.\ops\configure_stateful_lifecycle_cloudformation_role.ps1 `
  -AdminProfile "<iam-admin-profile>" `
  -ArtifactBucket "<private-artifact-bucket>"
```

After named-human review, apply it with the same arguments plus `-Apply`. Then
re-run `configure_stateful_lifecycle_deployer.ps1` in plan and apply modes so
the existing staging OIDC role receives only `iam:PassRole` for that service
role and `cloudformation:ContinueUpdateRollback` for the one lifecycle stack.
Set the resulting protected ARN as
`AWS_LIFECYCLE_CF_EXECUTION_ROLE_ARN` in the `staging` environment.

On 21 August 2026 Sydney time, PR #75 merged the missing-role probe correction
as `1f602c5d`, and post-merge CI run `32389801911` passed. A named IAM
administrator then reviewed and successfully applied the service-role plan,
reapplied the bounded deployer policies, and configured the protected staging
variable. Direct GitHub assumption remains disabled.

The service role is trusted only by CloudFormation and is exact-resource scoped
to the four staging functions, their four runtime roles, the lifecycle alarm,
and the lifecycle plus retained Action mutation artifact prefixes. Its Action
mutation capability exists for shared-stack consistency and rollback only. The
normal lifecycle deployer preserves the existing mutation artifact and rejects
any change set containing `ActionMutationFunction` or `ActionMutationRole`; the
separately approved Prepare/Execute workflow remains the only routine mutation
release path.

### Recovery-controller release blocker -- 17 August 2026

Manual workflow run `32012608848` used pushed commit
`6b2a6c8feda6af37207dedd860babe1b328cf009` and action
`deploy-recovery-controller`. Repository tests, private-variable checks,
isolated-target verification, and plan rendering passed. The run then failed
during idempotent schema application because the GitHub staging deployer did
not have `glue:GetTable` for one existing lifecycle catalog table.

Repository inspection found that the policy generator already declares the
read action but its exact table-resource inventory does not include that
catalog table. No seed was requested. The temporal backfill, stack/controller
deployment, deployed guard checks, failed-date recovery, operational-baseline
refresh, and Pages publication were all skipped. Earlier idempotent schema
statements may have been replayed before the failing statement, so the run is
not evidence of a complete schema deployment.

PR #71 merged the exact Glue inventory correction to `main` as commit
`2af45d06`, and CI run `32360803923` passed. The correction adds the five
governed closed-loop tables and `vw_lifecycle_action_current_staging_v1`. A
regression test derives every table and view declared by
`sql/04_stateful_lifecycle_config.sql`, requires each object to appear in the
policy inventory, and rejects a database-wide table wildcard.

On 20 August 2026, a named human first ran the corrected inline-policy apply.
AWS rejected `PutRolePolicy` with `LimitExceeded` before mutation because all
four inline policies on the shared role already occupied approximately 10,234
of the fixed 10,240-character aggregate quota; the corrected lifecycle policy
would have raised the total to approximately 10,827. The existing lifecycle
inline policy remained unchanged. Repository source now avoids that aggregate
limit by using the three customer-managed policies described above. A read-only
plan measured them at 4,829, 1,317, and 2,221 characters and projected four of
ten managed-policy attachments. All 21 focused lifecycle deployment tests and
all 313 repository tests pass, as do Python compilation and the 16-check drift
audit. Mocked success and injected-failure runs verify final legacy removal only
after all three attachments and preserve the legacy policy on incomplete
migration. PR #72 merged the migration as commit `68035ee`.

On 21 August Sydney time, a named IAM administrator reviewed and applied the
three-policy migration. All three managed policies were attached and verified,
the final attachment count was four of ten, and the superseded lifecycle inline
policy was then removed. Read-only workflow run `32379095685` passed with
`action=plan`, `OPERATIONAL` / `ACTUAL_CALENDAR`, and logical date `2026-08-09`.

PR #73 then merged the rerunnable temporal verifier as commit `7adf1863`; both
PR and post-merge CI passed. Separately authorised run `32383741062` passed the
backfill and failed later during the full stack update. CloudFormation reused
the narrow Action mutation service role persisted by the earlier one-resource
release. That role could not update the lifecycle generator or quality gate and
could not read the general lifecycle artifact prefix. Automatic rollback also
failed, leaving the isolated stack at `UPDATE_ROLLBACK_FAILED`.

That failed state was recovered through separately approved run `32390505373`.
It called `ops/recover_stateful_lifecycle_stack.ps1`, supplied the dedicated
role, skipped no resources, verified the persisted role, and finished at
`UPDATE_ROLLBACK_COMPLETE`. Plan runs `32390302719` and `32390677045` passed on
either side of recovery. Separately approved run `32390847334` then completed
the isolated schema replay, temporal backfill, full stack deployment, and
deployed temporal guard. Read-only inspection found the stack at
`UPDATE_COMPLETE` and the controller active on Python 3.14 with a successful
last update.

Diagnostic run `32391364627` checked the persisted failed `2026-08-09` date
without mutation and passed all 28 lifecycle checks. The stored status remains
failed. A named human subsequently authorized recovery run `32634293552` from
commit `adfd2a5`. Repository tests, OIDC and isolated-target checks, plan
rendering, generation, and the 28-check lifecycle gate passed; the controller
then failed closed at `input_validation` on `abnormal_volume_change`. A bounded
aggregate diagnostic reported 17 current shipments, zero in the exact prior-
calendar-day baseline, six of six required tables populated and current, and
zero duplicate business keys.

The repository follow-up aligns the lifecycle adapter, prior-alert read,
immutable-state validation, and compatibility volume gate on the latest
earlier populated date within the same temporal scope. It retains the 50%
threshold and still fails when no earlier same-scope baseline exists. This
follow-up was delivered as commit `85fc2f2`. Protected plan `32670942817` and
separately approved isolated-staging release `32671064789` passed. A further
named-human authorization bounded recovery run `32671484061` to only
`2026-08-09` in `OPERATIONAL` / `ACTUAL_CALENDAR` mode. It completed four
stages and 41/41 checks: 28 lifecycle, 5 compatibility, and 8 analytics. The
controller persisted terminal success before returning. The sequence used no
seed and did not refresh the baseline, replay another date, move a production
alias, create a schedule, publish Pages, or mutate an Action.

Separately authorised deployment run `32379866761` then completed repository
tests, isolated-target inspection, plan rendering, and the idempotent schema
step. It failed closed during temporal backfill verification with zero invalid
temporal identities but 120 `OPERATIONAL` rows later than the original
`2026-08-06` migration cutoff. The fixed cutoff correctly classifies only the
pre-boundary legacy rows; it is not a valid ceiling after actual-calendar
operations have advanced. The stack deployment, deployed guard check,
failed-date recovery, baseline refresh, and Pages publication were skipped.
The merged correction retains the original classification cutoff while
validating operational rows against their stored `as_of_date` and the
system-derived current Sydney business date. The correction passed the 21-test
lifecycle deployment suite, all 313 repository tests, Python compilation,
PowerShell parsing and plan rendering, the 16-check drift audit, and
`git diff --check`, then merged through PR #73 as `7adf1863` with successful PR
and post-merge CI. Run `32383741062` confirmed the temporal step now passes; the
remaining blocker is the separate stack-role collision and failed rollback
described above. No database-wide wildcard or production permission is
justified by either failure.

## Deployment

First inspect a plan without changing AWS:

```powershell
.\ops\deploy_stateful_lifecycle.ps1 `
  -SourceBucketUri "s3://<private-bucket>/stateful-lifecycle-staging/data" `
  -AthenaOutputUri "s3://<private-query-bucket>/athena-results/"
```

Create the isolated tables:

```powershell
.\ops\deploy_stateful_lifecycle.ps1 `
  -SourceBucketUri "s3://<private-bucket>/stateful-lifecycle-staging/data" `
  -AthenaOutputUri "s3://<private-query-bucket>/athena-results/" `
  -Apply
```

After reviewing the seed SQL, load its first version once:

```powershell
.\ops\deploy_stateful_lifecycle.ps1 `
  -SourceBucketUri "s3://<private-bucket>/stateful-lifecycle-staging/data" `
  -AthenaOutputUri "s3://<private-query-bucket>/athena-results/" `
  -IncludeSeed `
  -Apply
```

`IncludeSeed` is deliberately not advertised as idempotent. Do not run the same
seed version twice. The validation query fails on duplicate active configuration.

Deploy the unscheduled staging writer after the tables and seed exist:

```powershell
.\ops\deploy_stateful_lifecycle_stack.ps1 `
  -ArtifactBucket "<private-artifact-bucket>" `
  -LifecycleDataBucket "<private-data-bucket>" `
  -AthenaOutputUri "s3://<private-query-bucket>/athena-results/" `
  -CloudFormationRoleArn "<lifecycle-cloudformation-role-arn>" `
  -Apply
```

This checks Athena engine version 3, preserves the existing Action mutation
artifact, packages the lifecycle generator, controller, and quality gate,
inspects the proposed change set for protected-resource changes, and deploys
the staging roles, Lambdas, and alarm through the dedicated CloudFormation
service role. It creates no event source.

## Staging Lambda configuration

Package the engine with `glap_stateful_lifecycle_generator.lambda_handler` as
`lambda_function.lambda_handler`. Its technical configuration will use:

```text
ATHENA_SOURCE_DATABASE=simulated_iceberg_m
ATHENA_WORKGROUP=primary
ATHENA_OUTPUT=s3://<private-query-bucket>/athena-results/
SHIPMENT_TABLE=fact_shipment_lifecycle_staging_v1
SHIPMENT_EVENT_TABLE=fact_shipment_lifecycle_event_staging_v1
SHIPMENT_COST_TABLE=fact_shipment_cost_staging_v1
SHIPMENT_METRICS_TABLE=fact_shipment_lifecycle_metrics_staging_v1
SHIPMENT_SIGNAL_TABLE=fact_shipment_signal_candidate_staging_v1
ROUTE_SERVICE_TABLE=dim_route_service_v1
LIFECYCLE_TARGET_TABLE=dim_lifecycle_target_v1
RATE_CARD_TABLE=dim_rate_card_v1
RATE_TIER_TABLE=dim_rate_tier_v1
FX_RATE_TABLE=dim_fx_rate_v1
DEFAULT_REPORTING_CURRENCY=AUD
```

Business targets and rates stay in Iceberg and are never Lambda environment
variables.

The selected Athena workgroup must use engine version 3 because Athena supports
transactional `MERGE INTO` only for Iceberg on that engine. The stack verifies
this before upload. Its writer role has table-scoped Glue metadata permission,
prefix-scoped S3 data/result access and no production Lambda invoke permission.
If the lifecycle prefix is registered for Lake Formation fine-grained access,
confirm the account governance model before deployment: Lake Formation does
not currently govern Athena `MERGE`, `UPDATE`, `VACUUM` or `OPTIMIZE` write
operations. See the official [Athena MERGE documentation](https://docs.aws.amazon.com/athena/latest/ug/merge-into-statement.html)
and [Lake Formation transactional-table limitation](https://docs.aws.amazon.com/lake-formation/latest/dg/athena-lf.html).

Rate selection is locked by `booking_at`. A shipment booked in Q1 retains the
Q1 Rate Card even when ETD, ATD, ETA or ATA falls in Q2. Active versions are
never used to reprice an existing shipment.

## Replay

Review the 28-day replay plan:

```powershell
.\ops\replay_stateful_lifecycle_staging.ps1
```

After deploying the isolated Lambda and validating its target prefixes:

```powershell
.\ops\replay_stateful_lifecycle_staging.ps1 -Apply
```

The synchronous Lambda invocation sets the AWS CLI read timeout to 900 seconds,
matching the function timeout. Keep this explicit: the CLI's shorter default
can retry a still-running invocation and create avoidable concurrent Athena
MERGE attempts, even though the writer's business keys are retry-safe.

Then fail closed on any reconciliation error:

```powershell
.\ops\validate_stateful_lifecycle_staging.ps1 `
  -AthenaOutputUri "s3://<private-query-bucket>/athena-results/" `
  -ExecutionMode OPERATIONAL `
  -Apply
```

The validator resolves one temporal scope before rendering either SQL contract:
`OPERATIONAL` for actual-calendar evidence, or the isolated
`SIMULATION:<scenario_id>` scope for an explicitly named future simulation.

## Required staging evidence

Before invoking the function from the success-gated controller or promoting
its staging data contract:

1. run a fixed-seed 28-day replay;
2. confirm 14--18 new shipments per normal day;
3. confirm the same active shipment IDs cross logical dates;
4. confirm ETD/ETA never change and actual milestones never change after set;
5. confirm the seed population covers at least origin, P2P and destination stages;
6. confirm delivered shipments have one final `DELIVERED/CLOSED` snapshot and no
   later active rows;
7. run `sql/06_stateful_lifecycle_validation.sql` for every replay date;
8. reconcile expected cost totals to their rate-card detail and FX version;
9. reconcile exactly one lifecycle metric row to each daily snapshot;
10. validate stable `SLA_BREACH` and `COST_ANOMALY` candidate fingerprints and
    explicit `SIMULATED` provenance;
11. confirm the journey exception incidence is between 3% and 7%; and
12. retain the current production generator alias and rollback configuration.

Only after those checks pass should the staging writer receive scoped Glue,
Lake Formation and S3 write permissions and be added ahead of the existing
input quality gate. Production v2 promotion remains a separate controlled step.

## AWS staging evidence — 5 August 2026

The isolated staging gate passed in GitHub Actions workflow run
[`30967670110`](https://github.com/Andy-JunXiong/GLAP-AI-Decision-Platform/actions/runs/30967670110)
from commit `346ed68`. The successful run used `load_initial_seed=false`, kept
the initial seed single-loaded, and replayed 28 logical dates from `2026-08-04`
through `2026-08-31` with an initial active population of 450.

- All 28 Lambda invocations completed serially with no Lambda error, timeout,
  or CLI retry in the successful run.
- Every logical date passed both validation statements and all 16 fail-closed
  checks: 448 checks in total.
- The replay produced 16,037 daily snapshot rows across 895 distinct shipment
  IDs. Journey-level exception incidence was 4.58%, inside the documented
  3--7% target.
- 309 shipments reached `DELIVERED`; invalid terminal rows, rows after the
  first delivered snapshot, and duplicate snapshot keys were all zero.
- The CloudFormation stack finished `UPDATE_COMPLETE`. Its managed resources
  are the isolated Lambda, its dedicated IAM role, and an error alarm in `OK`.
  Lambda event-source mappings, aliases, and EventBridge rules targeting the
  function were all empty.
- The workflow evidence records `Production alias changed: false` and
  `Schedule created: false`.

This closes the private replay and reconciliation gate only.

## Isolated pipeline-integration evidence — 5 August 2026

Commits `b9d4049` and `bee43ef` add six read-only compatibility views, shared
quality contracts, and a separate manual integration controller. Plan workflow
run
[`30971969667`](https://github.com/Andy-JunXiong/GLAP-AI-Decision-Platform/actions/runs/30971969667)
passed before integration workflow run
[`30972254011`](https://github.com/Andy-JunXiong/GLAP-AI-Decision-Platform/actions/runs/30972254011)
executed the `2026-09-01` logical date. Relative to the `2026-08-05` execution
date, this was a future-dated synthetic staging scenario, not real September
history.

- The chain completed `stateful_lifecycle_generation`, `lifecycle_validation`,
  and `input_validation` successfully in about 139 seconds. Generation used
  about 120 seconds; the two quality stages used about 18 seconds combined.
- All 16 lifecycle checks and all 5 `lifecycle_compat_v2` input-contract checks
  passed fail closed.
- Native staging contained 601 shipment snapshots, 109 milestone events, 601
  lifecycle metrics, 61 cost rows, and 22 signal candidates for the logical
  date.
- The shipment, event, leg-metric, cost, risk, and product-allocation
  compatibility views returned 601, 109, 601, 601, 601, and 601 rows
  respectively. Derived identity, risk, and allocation values remain explicitly
  marked as simulated where the deployed schema permits provenance.
- The stack contains no Scheduler resource. Both integration Lambdas have no
  alias, event-source mapping, or EventBridge rule, and the compatibility layer
  does not write the current v2 tables.

This closes schema compatibility and isolated manual insertion ahead of the
input quality gate. It does not authorize production v2 writes, a schedule, or
an alias change. The next gate is to build governed operational aggregates and
forecast feature/label history on this foundation, validate backtests, and only
then request explicit approval for a controlled production-boundary change.

## Multimodal AWS staging evidence — 5 August 2026

Commit `def806b` introduced the backward-compatible multimodal evolution.
[CI run `30978116882`](https://github.com/Andy-JunXiong/GLAP-AI-Decision-Platform/actions/runs/30978116882)
and manual
[plan run `30978159773`](https://github.com/Andy-JunXiong/GLAP-AI-Decision-Platform/actions/runs/30978159773)
passed before
[integration run `30978208810`](https://github.com/Andy-JunXiong/GLAP-AI-Decision-Platform/actions/runs/30978208810)
applied the missing Iceberg columns, idempotent provider configuration, views,
and unscheduled Lambda package. The integration workflow completed in 5 minutes
59 seconds, including the one-time schema and stack updates.

The isolated controller then completed each future-scenario logical date from
`2026-09-02` through `2026-09-06` in order. This is technical staging evidence,
not observed calendar history.

- Every date passed all 19 lifecycle checks and all 5 compatibility-input
  checks.
- The five-day cohort contained 83 new bookings: 35 Maersk Ocean (42.17%), 33
  KN Ocean (39.76%), and 15 DHL Air (18.07%). The rolling Air-share check became
  active after 70 bookings and passed the approved 15--20% range.
- The first three DHL Air shipments recorded `BOOKING_CONFIRMED`,
  `ORIGIN_RECEIVED`, `FLIGHT_DEPARTED`, `FLIGHT_ARRIVED`, `CARGO_AVAILABLE`, and
  `DELIVERED`; all three were closed as `DELIVERED` on `2026-09-06`.
- DHL Air rows used zero containers, positive pieces/gross/volumetric and
  chargeable weight, and chargeable weight greater than or equal to gross
  weight. Their booking cost detail used `AIR_FREIGHT`,
  `AIR_FUEL_SURCHARGE`, `ORIGIN_HANDLING`, `SECURITY_SCREENING`, and
  `DESTINATION_HANDLING`.
- Existing synthetic Ocean scenario rows remained in place. Compatibility views emit the
  governed mode, preserve common P2P and delivery fields, and keep Ocean-only
  equipment null for Air.
- The updated stack still contains no Scheduler resource. Controller and
  quality-gate functions have no alias, event-source mapping, or EventBridge
  target rule.

This establishes the multimodal data foundation in isolated staging only.
Recurring execution and production writes remain disabled.

## Multimodal operational analytics AWS staging evidence — 5 August 2026

The next read-only layer adds six governed Athena views over lifecycle staging:
one shipment-grain analytic base, daily mode and provider rollups, an
Air-vs-Ocean lane decision view, a past-only daily feature view, and a latest
shipment outcome-label view. The deployment also adds the eight-check
`multimodal_analytics_v1` fail-closed contract as the fourth manual controller
stage.

- Local validation passed all 99 repository tests, and
  [CI run `30980919130`](https://github.com/Andy-JunXiong/GLAP-AI-Decision-Platform/actions/runs/30980919130)
  passed for commit `635a590`.
- Future-scenario logical dates `2026-09-06` and `2026-09-07` each passed all 27 staging
  checks: 19 lifecycle checks plus 8 analytics checks. The Sep 7 controller
  also passed all 5 v2 compatibility checks.
- The Sep 7 four-stage controller completed in about 163 seconds: generation
  144.3 seconds, lifecycle validation 11.4 seconds, compatibility validation
  3.3 seconds, and analytics validation 4.3 seconds.
- Sep 7 mode rollups contained 15 DHL Air snapshots with 3 new bookings and 4
  deliveries, and 570 Ocean snapshots with 13 new bookings and 19 deliveries.
  DHL's operational unit is chargeable kilograms; KN and Maersk use containers.
- The provider rollup contained DHL Air, KN Ocean, and Maersk Ocean without
  duplicating shipment snapshots. Forecast features use only prior rows through
  the feature cutoff, and pending outcome rows carry no future labels.
- All nine generated Air market lanes had an Ocean reference. Planned Air time
  saved ranged from 349 to 602 hours. Cost premium is deliberately calculated
  on a standardized simulated weight basis, Air chargeable kilograms versus
  Ocean gross kilograms, rather than misleadingly comparing a small Air
  shipment with a multi-container Ocean shipment. The scenario range was
  3,728.07% to 4,173.52%.
- The stack update still created no schedule and changed no production alias or
  production table. The views are read-only and do not materialize another
  daily data copy.

This closes the governed operational-analytics foundation in isolated staging.
It supplies analysis-ready synthetic scenario data and prediction-path test
features/labels, but it does not establish real performance, train, or authorize
a production forecasting model.

## Private forecast-validation workflow

Forecast validation uses the manual
`backtest-multimodal-forecast-staging.yml` workflow. Its default action is
`plan`; the explicit `backtest` action reads only
`vw_multimodal_forecast_feature_daily_v1`, validates the frozen feature
contract, and runs rolling one-step-ahead recent-level, seven-observation moving
average, weekday-seasonal, and OLS baselines independently by mode/provider.

The report includes MAE, RMSE, signed bias, MAPE where actual volume is non-zero,
95% residual interval coverage, training windows, provider history coverage,
seven-day booking drift, and Athena bytes scanned. A challenger is recommended
only when it lowers both MAE and RMSE and beats the recent-level baseline on at
least 60% of at least seven comparable held-out dates. Otherwise the simple
baseline remains.

The workflow may initially report `partial_history` or `insufficient_history`
for providers introduced during the multimodal evolution. That is a valid
evidence state and must not be represented as a failed model. Reports remain
private workflow artifacts for 14 days; Pages publication, recurring execution,
production writes, and policy changes are all disabled.

Operational runs and reports may use dates only through the current Sydney
business date. A later cutoff requires explicit `FUTURE_SIMULATION` mode and a
scenario ID, is isolated from operational status, and can validate mechanics
only. See the [temporal truthfulness contract](temporal_truthfulness.md).

The frozen feature columns must first be applied with the existing lifecycle
workflow's explicit `deploy-analytics-contract` action. That action follows the
plan-only `AnalyticsOnly` deployment path and validates an existing logical
date; it updates view definitions only and does not invoke the generator.

The backtest workflow also runs a separate aggregate label-readiness query. It
exports no shipment IDs and excludes all `PENDING` outcomes from training
counts. SLA-breach and delay-risk evaluation require at least 200 observed
labels with at least 20 examples in each class per mode/provider. Cost-variance
evaluation requires at least 200 observed labels and 10 distinct values. A
provider below those thresholds remains explicitly blocked while history
accumulates.

## Forecast-validation AWS evidence — 5 August 2026

After PR `#11` merged as commit `4348e8e`, plan-only workflow run
`30996670988` passed. Run `30996715050` then updated only the six read-only
analytics view definitions and passed the existing `2026-09-07` staging
future-scenario validation. It did not invoke lifecycle generation, create a
schedule, change a production alias, or write a business table.

Forecast plan run `30996809400` passed before private scenario backtest run
`30997015294` queried the generated `2026-08-04` through `2026-09-07` feature
window. Dates after `2026-08-05` were future scenario dates.

- Maersk Ocean had 35 observations with 100% calendar completeness, producing
  21 held-out forecasts per model. DHL Air and KN Ocean each had six complete
  observations and remained in `partial_history` rather than being evaluated
  on an unsafe short window.
- Recent-level was retained for Maersk with MAE `2.0476`, normalized MAE
  `15.3571%`, RMSE `2.5355`, bias `0.3333`, MAPE `17.9231%`, and 95% residual
  interval coverage of `90.4762%`. Moving-average, OLS, and weekday-seasonal
  MAE values were `2.7279`, `2.7707`, and `3.6627`, respectively.
- Label readiness remained `blocked_insufficient_observed_labels`: DHL had 7
  observed and 11 pending outcomes, KN had 0 observed and 39 pending, and
  Maersk had 20 observed and 482 pending. No supervised target was authorized
  for training.
- The feature and label queries scanned `160137` and `463988` bytes,
  respectively, both far below the `104857600`-byte per-query budget.
- The 14-day workflow artifact contains only mode/provider aggregates and model
  evidence. A post-download guard found no shipment ID, route-service ID,
  market lane, S3 URI, or AWS ARN.

This validates the private forecasting workflow mechanics. It does not prove
real model performance or close any operational backtest or supervised-label
accumulation gate.

## Governed scenario extension

Use the manual lifecycle workflow action `extend-integration-validate` to add
consecutive staging scenario dates after the latest successful scenario date.
Operational use is restricted to the current Sydney date or earlier. The action
invokes the isolated controller once per date and requires generation, 28
lifecycle checks, 5 compatibility checks, and 8 analytics checks to pass before
advancing. It stops on the first failure.

Use `diagnose-integration-date` when a deployed controller run reports a
lifecycle quality-gate failure. The action invokes the already deployed staging
quality gate directly and emits only the allowlisted check count and failed
check names. Action Outcome review remains behind the authenticated Operations
API `/v1/outcomes`; this workflow has no direct closed-loop table access. The
diagnostic does not emit entity identifiers, invoke the generator, render
against a newer local SQL contract, deploy resources, or write lifecycle rows.

The extension payload carries the logical date and its system-resolved temporal
context; it never requests a new seed population. The action neither deploys
the stack nor creates a schedule or production alias. `replay_start_date` is
the first new date and `replay_days` is limited to 12 so the run retains margin
inside the one-hour GitHub OIDC credential window.

For GitHub OIDC validation, the script delegates the 28 closed-loop lifecycle
checks to the already deployed quality-gate Lambda, whose execution role owns
the exact table reads. It still renders and runs the current repository's eight
analytics checks directly, so a newly changed analytics SQL contract is not
silently validated through older deployed code. Local administrators may omit
`-LifecycleQualityGateFunction` to run both SQL contracts directly with an
appropriately authorised profile.

### Deploy row-level temporal isolation

After PR `#23`, the manual `deploy-recovery-controller` action also performs
the idempotent five-table schema evolution and the explicitly approved one-time
`2026-08-06` temporal-scope backfill before deploying the unscheduled stack.
The backfill fails closed unless every row has a consistent temporal identity,
legacy future rows exist, no future row remains operational, and the default
operational analytics view exposes zero rows after the cutoff. It does not
create a schedule, production alias, or public output.

### Row-level temporal isolation AWS evidence -- 6 August 2026

PR `#24` merged as commit `793dc45`. Workflow run `31065406261` was dispatched
from protected `main` with action `deploy-recovery-controller`. Its first
attempt stopped before backfill because the exact-resource GitHub deployer
policy did not yet include the 12 context-view Glue ARNs introduced by PR
`#23`. The policy was updated with those 12 explicit resources only; it was not
widened to a database or account wildcard.

The second attempt, job `92503565020`, completed the 45-statement idempotent
schema and view deployment, all five bounded Iceberg backfill updates, the
unscheduled lifecycle stack update, and the deployed future-operational-date
guard. The post-backfill assertions returned:

- invalid temporal rows: `0`
- legacy future simulation rows: `78,621`
- future rows remaining in operational scope: `0`
- operational rows through `2026-08-06`: `5,092`
- future rows exposed by the default operational view: `0`

CloudFormation independently reported `UPDATE_COMPLETE` for
`glap-stateful-lifecycle-staging`, last updated at
`2026-08-06T02:37:31.609000+00:00`. The workflow evidence also confirms that
no schedule was created and no production alias was changed.

### Operational-calendar baseline contract

Use the manual `deploy-operational-baseline` action with a separately approved,
non-future `integration_logical_date` to create and validate
`vw_multimodal_operational_baseline_v1`. The view freezes the operational scope
at that Sydney as-of date and provides one overall row plus transport-mode,
provider, and market-lane breakdowns for shipment volume, delivery performance,
delay, cost variance, and governed signal candidates.

`baseline_as_of_date` is the inclusion cutoff; `source_max_metric_date` is the
latest eligible lifecycle metric actually included. The deployment validator
now requires those values to match. This prevents a later recovery from being
backdated into an earlier point-in-time baseline and prevents a newer cutoff
from masking stale source coverage.

This is an operational-calendar engineering baseline over staging data, not
real-world company performance. Every row therefore carries
`real_world_evidence=false`, provenance `SIMULATED_MULTIMODAL_V1`, evidence
class `SYNTHETIC_OPERATIONAL_CALENDAR_BASELINE`, and decision use
`ENGINEERING_EVALUATION_ONLY`. Ten fail-closed checks reconcile the view to the
bounded operational source and reject cutoff drift, scenario leakage, invalid
evidence claims, duplicate dimensions, or invalid metric ranges.

The public-safe OPS snapshot publishes only the aggregate `ALL` row beside the
existing v2/v3 decision-flywheel population. It does not reconcile unlike
shipment denominators or expose entity rows. Realized cost variance is null
until at least one delivery exists, and the Control Tower remains `NOT_READY`
until 200 delivered outcomes plus observable delivery and cost measures are
available. Even then, synthetic evidence can become engineering-ready only;
real-world decision use remains blocked.

### Operational-calendar baseline evidence -- 24 August 2026

After the bounded `2026-08-09` lifecycle recovery completed, a separate named
human authorized workflow run `32672560594` from commit `d368b4a` with
`action=deploy-operational-baseline`, `execution_mode=OPERATIONAL`, and
`integration_logical_date=2026-08-09`. The run rendered and applied exactly
one `CREATE OR REPLACE VIEW` statement and all 10 fail-closed validation rows
returned zero failures. The result remains
`SYNTHETIC_OPERATIONAL_CALENDAR_BASELINE`, `ENGINEERING_EVALUATION_ONLY`, and
`real_world_evidence=false`.

The run did not load a seed, recover or replay another date, deploy analytics
or a lifecycle stack, change production, schedules, or aliases, publish Pages,
or mutate an Action. Any public aggregate publication remains a separately
authorized step.

Separately authorized Pages run `32673379142` subsequently published commit
`fed2462` successfully. The public JSON showed the daily OPS track current at
`2026-08-24`, while this stateful view retained cutoff `2026-08-09` and eligible
source metrics only through `2026-08-06`. The repository date-display and
cutoff/source equality correction is locally implemented and test-verified,
while continuing the lifecycle, replacing the baseline at a later cutoff, and
publishing again remained three separate human-authorized operations.

The first two of those later operations were separately authorized and
completed. Run `32674455765` advanced 12 dates through `2026-08-21`; run
`32676988757` advanced the remaining three dates through `2026-08-24`, with
four stages and 41 checks passing per date. Redundant run `32728891520` failed
closed before processing because the controller refused to overwrite the newer
24 August status. Run `32729202007` then used only
`deploy-operational-baseline` at cutoff `2026-08-24`, replaced one aggregate
view, and passed the deployed 10-check contract. It reported 751 shipments,
301 new bookings, and 199 delivered rows with synthetic, engineering-only
provenance. No seed, production alias, schedule, Pages publication, or Action
mutation was included.

The third operation was separately authorized afterward. Commit `28e3edf` and
aggregate-only Pages run `32731582185` delivered the two-date display and
exercised the connected exporter equality gate successfully. A read-only live
check confirmed cutoff and latest source metric date both at `2026-08-24`.
Pages did not deploy this SQL file or mutate lifecycle data, production aliases,
schedules, or Actions.

## Future-scenario extension AWS evidence -- 5 August 2026

PR `#13` merged as commit `e56b41b` after both Python 3.13 and 3.14 CI jobs
passed in run `30997968931`. Plan run `30998092491` then validated the no-seed,
no-deploy extension for `2026-09-08` through `2026-10-05`.

Apply run `30998141662` completed 23 consecutive future-scenario dates from
`2026-09-08` through `2026-09-30`. Each date returned the exact four-stage
contract and all 32 checks passed. This proves scenario pipeline behavior, not
real September operations. At the next invocation, the GitHub caller's OIDC credentials
expired after one hour. The AWS CLI therefore failed before receiving the
normal `2026-10-01` controller response.

A five-day continuation plan passed in run `31002256538`. Continuation run
`31002314446` then received a Lambda `FunctionError` immediately when retrying
`2026-10-01`. Because the first invocation may have reached or partially
changed same-day state before its caller credentials expired, do not replay the
date again without a read-only state diagnosis.

Forecast plan run `31002432750` validated a read-only diagnostic with a
`2026-10-01` cutoff. The actual Athena query was deliberately not dispatched:
the expanded private-data window requires explicit authorization. The next
session must confirm the latest completed feature/label boundary, resume only
the missing dates through `2026-10-05`, and then rerun the aggregate forecast
backtest. No schedule, production alias, production table, or public
entity-level artifact was created by these attempts.
