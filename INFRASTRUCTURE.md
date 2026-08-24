# GLAP Infrastructure

## Evidence status

GLAP is an AWS-deployed reference implementation validated with synthetic logistics data. The Lambda source in [`lambda/`](lambda/) was exported from the deployed function. The SQL artifacts include sanitized `SHOW CREATE TABLE` output from Athena, a query embedded in the deployed function, and read-only validation queries derived from observed history. Environment-specific identifiers are excluded.

The dated verification record and evidence boundaries are maintained in [`docs/aws_implementation_evidence.md`](docs/aws_implementation_evidence.md).

| Evidence level | Meaning |
| --- | --- |
| Deployed | Present in the AWS environment and directly inspected |
| Validated | Successfully exercised with synthetic data |
| Representative | Simplified material retained under `examples/` |
| Designed | An extension or future capability, not claimed as production behavior |

## Deployment model

The inspected deployment runs in AWS `us-east-1` and uses Python 3.14 Lambda functions. Its public artifacts contain synthetic data only.

| Service | Responsibility | Status |
| --- | --- | --- |
| Amazon S3 | Iceberg data files and Athena query results | Deployed |
| AWS Glue Data Catalog | Iceberg table metadata | Deployed |
| Amazon Athena | SQL analytics and Iceberg reads/writes | Deployed and validated |
| AWS Lambda | Root-cause and decision orchestration | Deployed and validated |
| EventBridge Scheduler | Recurring invocation | Documented deployment |
| Amazon CloudWatch | Execution logs and monitoring | Documented deployment |
| Amazon QuickSight | Operational dashboards | Validated with synthetic outputs |

## Isolated mainland reviewer entry

The human-created AWS surface consists of an isolated Lambda Function URL,
DynamoDB table, and least-privilege execution role. Its health endpoint and
login were inspected; a three-second timeout caused the earlier generic login
failure, and the human corrected the Lambda to the documented ten-second
timeout. The repository package for collection `glap-ten-story-review.v1` was
uploaded by a named human. A read-only health check verified build
`ten-story-review-2026-08-18.1`, the expected bundle digest, ten cases, 30
moments, and status `ok`. It stores 30 immutable per-moment answers followed by
one final submission. It does not reuse operational tables, aliases, schedules,
Athena, Glue, S3,
Actions, Outcomes, or production paths. See
[`docs/three_case_review_entry.md`](docs/three_case_review_entry.md).

## Runtime flow

```text
EventBridge Scheduler
-> Lambda orchestrator
-> Athena reads anomaly records
-> Python root-cause rules
-> Iceberg root-cause table
-> Python decision rules
-> Iceberg decision table
-> QuickSight dashboards
```

## Core tables

The scheduled public OPS analytics contract reads the current decision flywheel:

- `curated_iceberg.fact_shipment_events_extended_iceberg`
- `curated_iceberg.fact_ai_alerts_v3`
- `curated_iceberg.fact_ai_root_causes_v1`
- `curated_iceberg.fact_ai_insights_v3`
- `curated_iceberg.fact_ai_decisions_v3`
- `curated_iceberg.fact_ai_actions_v2`
- `curated_iceberg.fact_ai_outcomes_v2`
- `curated_iceberg.fact_ai_learning_feedback_v1`
- `curated_iceberg.fact_ai_learning_v1`
- `curated_iceberg.ai_decision_trace_v1` (stored-view dependency)
- `curated_iceberg.v_ai_latest_decision_trace`

Athena performs the public KPI, distribution, action-completion, outcome, OLS
trend, residual-interval, and forecast calculations. Shipment volume is anchored
to the governed logical run date and the Iceberg `dt` partition, so future
shipment event timestamps do not make the analysis appear to run in the future.
No new analytics table is created for this public path.

The following v1 tables document the separately deployed deterministic agent
orchestrator. They are retained as historical contracts but are not used to
claim current daily pipeline health:

- `curated_iceberg.fact_ai_anomaly_scores_v1`
- `curated_iceberg.fact_ai_root_cause_v1`
- `curated_iceberg.fact_ai_decision_explanations_v1`

Additional action, outcome, learning, and policy tables exist in the inspected environment. Their outcome records are generated from synthetic validation logic and are not presented as measured business impact.

## Runtime configuration

The deployed orchestrator reads these environment variables:

- `ATHENA_DATABASE`
- `ATHENA_OUTPUT`
- `ATHENA_WORKGROUP` (defaults to `primary`)

The values are deliberately omitted because they identify environment-specific resources.

## Reliability controls

- Athena query status polling and timeout handling
- failure propagation from Athena
- SQL string escaping for generated statements
- duplicate checks by date, entity, and metric
- inserted/skipped counters in the Lambda result and logs
- immutable `staging` and `prod` Lambda aliases for controlled promotion
- EventBridge Scheduler targets `prod`, retries failed invocations twice within
  24 hours, and sends exhausted invocations to a dedicated SQS dead-letter queue
- the dead-letter queue uses SQS-managed encryption and retains messages for 14
  days
- CloudWatch alarms cover Lambda errors, throttles, duration above 100 seconds,
  and visible dead-letter queue messages
- GitHub Actions assumes a repository- and environment-scoped OIDC role for
  manual staging deployments; no long-lived AWS key is stored in GitHub
- a dedicated promoter Lambda owns alias mutation and is hard-locked in code and
  environment to `staging`, so the GitHub deployment role has no `UpdateAlias`
  permission and cannot move `prod`
- the separately deployed Action mutation staging function uses a two-phase
  GitHub OIDC release boundary: a protected prepare environment may upload one
  content-addressed artifact and create an unexecuted change set, while a
  separately protected execute environment may execute only that reviewed
  change set
- neither Action mutation GitHub identity can update Lambda directly; a
  CloudFormation-only service role holds the exact function update capability,
  exact template-role reads, and both the candidate and retained rollback
  artifact reads required to finish or recover the one-resource update
- the repository Operations API extension reads the already allow-listed
  immutable Action table, Action audit table, and Outcome table in one bounded
  query to assemble a private Action–Outcome evidence chain; its explicit JWT
  route and environment binding are merged to `main` but not deployed
- the repository Outcome-to-Learning extension adds one authenticated read route
  over the existing Outcome and policy-proposal tables; IAM and Lake Formation
  inventories name the policy table exactly and grant no write, grant-option,
  activation, schedule, alias, or production capability

PR #76 merged both read-only extensions as `c4f367fb`. The merge-triggered
Operations API workflow passed its protected configuration, dependency, and
deployment-plan checks, while the deploy step was explicitly skipped. This is
delivery-plan evidence only; the existing staging stack and private frontend
were not updated or runtime-verified by that run.

The deployed CloudWatch alarms publish both alarm and recovery transitions to
the existing `glap-pipeline-alerts` SNS topic. Subscriber endpoints are managed
in AWS and are deliberately not published in this repository.

## IAM model

The Lambda execution role needs permission to start and inspect Athena queries, read Glue catalog metadata, and access the relevant S3 data and result locations. The scheduler needs permission to invoke the Lambda function. This repository does not publish account IDs, role ARNs, policies, or bucket names.

The 2026-08-17 lifecycle recovery-controller release attempt exposed a narrower
staging delivery gap: the GitHub staging deployer's exact-resource Glue
allowlist did not cover one existing lifecycle catalog table. Manual workflow
run `32012608848` stopped at schema application before temporal backfill,
controller/stack deployment, recovery, baseline refresh, or public
publication. PR #71 corrected the repository policy inventory and merged to
`main` as commit `2af45d06`; CI run `32360803923` passed. The correction
reconciles the explicit inventory with every object declared by the lifecycle
schema DDL, adding the five governed closed-loop tables and their current-action
view that were previously omitted. A regression test enforces DDL-to-policy
coverage and rejects a database-wide table wildcard.

A named-human apply on 2026-08-20 then failed closed before IAM mutation because
the shared role's four inline policies already used approximately 10,234 of the
fixed 10,240-character aggregate quota. The corrected inline policy would have
raised the total to approximately 10,827. The migration implementation
now preserves the same permission statements across three bounded
customer-managed policies for Catalog, Storage, and Deployment. It preflights
the per-policy size and attachment quotas, stages and verifies the managed
policies before removing the legacy inline policy, and retains rollback paths
before final legacy removal. A read-only plan measured 4,829, 1,317, and 2,221
characters and four of ten final attachments. PR #72 merged the migration as
commit `68035ee`. On 2026-08-21 Sydney time, a named IAM administrator applied
and verified all three attachments before the legacy inline policy was removed;
read-only workflow run `32379095685` then passed. Deployment run `32379866761`
completed the idempotent schema step but failed closed before stack deployment
because the one-time temporal verifier treated 120 later actual-calendar
operational rows as if the original `2026-08-06` migration cutoff were still the
current calendar boundary. PR #73 merged the correction to `main` as commit
`7adf1863`, and both PR and post-merge CI passed.

Separately authorised deployment run `32383741062` then passed that temporal
backfill but exposed the persisted CloudFormation-role collision and stopped at
`UPDATE_ROLLBACK_FAILED`. PRs #74 and #75 introduced and hardened a dedicated
CloudFormation-only lifecycle maintenance role, preserved the narrow Action
mutation release boundary, and added rollback continuation without skipped
resources. PR #75 merged as `1f602c5d`; post-merge CI run `32389801911` passed.

A named IAM administrator then configured and verified the dedicated role,
the bounded deployer policies, and the protected staging variable. Plan run
`32390302719`, rollback-recovery run `32390505373`, and follow-up plan run
`32390677045` passed; rollback recovery restored the stack without skipping a
resource. Separately approved deployment run `32390847334` completed the schema
replay, temporal backfill, full isolated stack update, and deployed guard.
Read-only inspection found the stack at `UPDATE_COMPLETE` and the controller
active on Python 3.14 with a successful last update. Diagnostic run
`32391364627` passed all 28 checks for `2026-08-09` without mutation. The
cross-gap correction then passed protected plan `32670942817`, separately
approved isolated-staging release `32671064789`, and one-date recovery
`32671484061`. The recovery completed 28 lifecycle, 5 compatibility, and 8
analytics checks and persisted terminal success. Separately authorized
baseline run `32672560594` then created or replaced one cutoff-bounded
aggregate view and passed 10/10 fail-closed checks. Production alias,
Scheduler, and Pages remain unchanged and human-owned.

A separately authorized read-only export and Pages deployment run
`32673379142`, followed by scheduled run `32682049141`, published the aggregate
snapshot from commit `fed2462`. Inspection confirmed the daily OPS track at
`2026-08-24` but also exposed that
the frozen stateful baseline cutoff was `2026-08-09` while its latest eligible
source metric date was `2026-08-06`. The repository worktree now rejects a
connected baseline whose source coverage does not equal its cutoff and displays
both dates. That safeguard is locally verified, with publication verification
pending.

Separately authorized manual staging runs later closed the source-date gap.
Run `32674455765` extended `2026-08-10` through `2026-08-21`; run
`32676988757` completed `2026-08-22` through `2026-08-24`, with four stages and
41 checks passing per date. Redundant run `32728891520` failed closed before
processing rather than overwrite the newer 24 August controller status.
Baseline run `32729202007` then replaced exactly one aggregate view at cutoff
`2026-08-24` and passed the deployed 10-check contract. These operations loaded
no seed and changed no production alias, schedule, Pages surface, or Action.

The Action mutation staging release boundary was exercised end to end on
2026-08-10. Separate human approvals guarded change-set preparation and
execution, the change set contained one non-replacing Lambda property update,
and the final stack and function both completed successfully. A preceding
attempt exposed missing rollback-path permissions, reached
`UPDATE_ROLLBACK_FAILED`, and was recovered by a named human without skipping a
resource before the successful retry. This is staging delivery and recovery
evidence only; it grants no production alias, schedule, IAM-administration, or
operational Action authority.

## Security and redaction

Public artifacts exclude credentials, account IDs, ARNs, bucket names, query output paths, and internal URLs. Configuration remains environment-driven. Sample data and dashboard outputs are synthetic.
