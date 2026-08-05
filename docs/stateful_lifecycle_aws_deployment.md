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
| `AWS_LIFECYCLE_ARTIFACT_BUCKET` | Existing private bucket for the Lambda ZIP |
| `AWS_LIFECYCLE_DATA_BUCKET` | Existing private bucket; writes are restricted to `stateful-lifecycle-staging/data/` |
| `AWS_LIFECYCLE_ATHENA_OUTPUT` | Prefix-scoped private Athena result URI; `AWS_OPS_ATHENA_OUTPUT` is the fallback |

Run `action=plan` first. The first `deploy-replay-validate` execution must set
`load_initial_seed=true`; repeat executions leave it false. The workflow does
not create a schedule, modify a production alias, or connect the function to
the production controller.

### One-time deployer permission bootstrap

The existing `glap-github-staging-deployer` role may only have permissions for
the older Lambda staging release path. Before the first lifecycle workflow run,
an IAM administrator must add the lifecycle-specific inline policy. Review the
plan first:

```powershell
.\ops\configure_stateful_lifecycle_deployer.ps1 `
  -AdminProfile "<iam-admin-profile>" `
  -ArtifactBucket "<private-artifact-bucket>" `
  -LifecycleDataBucket "<private-data-bucket>" `
  -AthenaOutputUri "s3://<private-query-bucket>/athena-results/"
```

Apply only after checking the three prefixes and role name:

```powershell
.\ops\configure_stateful_lifecycle_deployer.ps1 `
  -AdminProfile "<iam-admin-profile>" `
  -ArtifactBucket "<private-artifact-bucket>" `
  -LifecycleDataBucket "<private-data-bucket>" `
  -AthenaOutputUri "s3://<private-query-bucket>/athena-results/" `
  -Apply
```

The inline policy is scoped to the lifecycle workgroup/database contracts,
artifact, data and query-result prefixes, the isolated CloudFormation stack,
the staging Lambda, its stack-generated execution role and its alarm. It grants
no Scheduler action and no production alias update. Re-run `action=plan` after
the policy is applied; do not start the one-time seed while plan is failing.
The execution role uses the fixed staging-only name
`glap-stateful-lifecycle-generator-staging-role`; this prevents CloudFormation
physical-name truncation from widening or bypassing the deployer policy scope.

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
  -Apply
```

This checks Athena engine version 3, packages only `lambda_function.py` and the
pure lifecycle engine module, uploads a versioned artifact when the workflow is
used, and deploys an IAM role, Lambda and error alarm. It creates no event source.

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
  -Apply
```

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
executed the `2026-09-01` logical date.

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

The isolated controller then completed each logical date from `2026-09-02`
through `2026-09-06` in order.

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
- Existing Ocean history remained in place. Compatibility views emit the
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
- Logical dates `2026-09-06` and `2026-09-07` each passed all 27 staging
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
- All nine observed Air market lanes had an Ocean reference. Planned Air time
  saved ranged from 349 to 602 hours. Cost premium is deliberately calculated
  on a standardized simulated weight basis, Air chargeable kilograms versus
  Ocean gross kilograms, rather than misleadingly comparing a small Air
  shipment with a multi-container Ocean shipment. The observed range was
  3,728.07% to 4,173.52%.
- The stack update still created no schedule and changed no production alias or
  production table. The views are read-only and do not materialize another
  daily data copy.

This closes the governed operational-analytics foundation in isolated staging.
It supplies analysis-ready history and prediction-ready features/labels, but it
does not yet train or authorize a production forecasting model.

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
