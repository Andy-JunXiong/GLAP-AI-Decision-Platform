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
backfill and reached the stack update. CloudFormation reused the narrow Action
mutation service role that an earlier one-resource release had permanently
associated with the shared stack. That role correctly lacked permission to
update the generator and quality-gate functions or read the lifecycle artifact
prefix, so the update and its automatic rollback failed closed at
`UPDATE_ROLLBACK_FAILED`. Repository source now introduces a separate lifecycle
CloudFormation service-role plan, makes full lifecycle updates pass that role
explicitly, preserves the existing Action mutation artifact, rejects any
Action mutation resource in the lifecycle change set, and exposes a separate
manual rollback-recovery action that never skips a resource. These controls are
implemented and repository-tested only; the new IAM role, GitHub
variable, deployer-policy update, rollback recovery, controller release,
failed-date recovery, baseline refresh, production alias, Scheduler, and Pages
remain unchanged and human-owned.

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
