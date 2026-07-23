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

- `curated_iceberg.fact_shipment_events_extended_iceberg`
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

The deployed CloudWatch alarms publish both alarm and recovery transitions to
the existing `glap-pipeline-alerts` SNS topic. Subscriber endpoints are managed
in AWS and are deliberately not published in this repository.

## IAM model

The Lambda execution role needs permission to start and inspect Athena queries, read Glue catalog metadata, and access the relevant S3 data and result locations. The scheduler needs permission to invoke the Lambda function. This repository does not publish account IDs, role ARNs, policies, or bucket names.

## Security and redaction

Public artifacts exclude credentials, account IDs, ARNs, bucket names, query output paths, and internal URLs. Configuration remains environment-driven. Sample data and dashboard outputs are synthetic.
