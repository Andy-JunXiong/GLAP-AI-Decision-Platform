# Stateful lifecycle AWS deployment

## Current delivery boundary

This repository slice creates the versioned lifecycle, route, rate, tier and FX
contracts; an isolated staging snapshot/event/cost/metric/signal boundary; a
deterministic state transition and expected-cost engine; a retry-safe Athena
persistence adapter; an unscheduled staging Lambda template; and fail-closed
validation SQL.
It does not replace `glap-daily-incremental-generator-v2` or write to governed
v2 production tables.

The P2P contract has exactly one immutable `etd` and `eta`. `atd` and `ata` are
written once when observed. Origin gate-in, destination discharge and final
delivery have separate target and actual milestones.

## Files

- `sql/04_stateful_lifecycle_config.sql` creates configuration and staging tables.
- `sql/05_stateful_lifecycle_seed.sql` installs the approved initial route and
  synthetic rate versions.
- `sql/06_stateful_lifecycle_validation.sql` reconciles snapshot, milestones,
  versions, tiers and cost detail.
- `lambda/glap_stateful_lifecycle_generator.py` provides deterministic replay,
  seed population, daily progression, expected-cost calculation, lifecycle SLA
  metrics and auditable SLA/cost signal candidates.
- `lambda/glap_lifecycle_athena_adapter.py` reads governed configuration and the
  prior active snapshot, then performs retry-safe staging Iceberg merges.
- `ops/deploy_stateful_lifecycle.ps1` renders and optionally executes the schema.
- `ops/deploy_stateful_lifecycle_stack.ps1` packages the two-module Lambda and
  deploys the isolated IAM/Lambda/alarm CloudFormation stack.
- `infrastructure/stateful-lifecycle-staging.yaml` creates an unscheduled,
  prefix-scoped staging Lambda and alarm.
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
