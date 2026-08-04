# Success-gated pipeline reliability

## Verified current path

Read-only AWS inspection on 4 August 2026 confirmed that the current daily
decision path is split across four independently scheduled functions:

| Local time (`Australia/Sydney`) | Responsibility | Current function |
| --- | --- | --- |
| 00:05 | Generate the daily raw logistics dataset | `glap-daily-incremental-generator-v2` |
| 00:30 | Load six raw domains into current Iceberg v2 tables | `glap-v2-orchestrator` |
| 07:00 | Produce alerts v3, insights v3, decisions v3, and actions v2 | `glap-ai-orchestrator-v1` |
| 08:00 | Produce policy selection, outcomes v2, and learning v1 | `glap-ai-flywheel-orchestrator` |

These schedules are ordered only by time. The 07:00 AI schedule has no DLQ and
zero configured retries, so an enabled schedule does not prove that the complete
daily chain succeeded. Separate legacy schedules also remain enabled and require
an explicit retirement decision.

## Replacement chain

`lambda/glap_pipeline_controller.py` executes this ordered contract:

```text
generation
→ raw_to_iceberg
→ input_validation
→ decision_pipeline
→ decision_flywheel
→ output_validation
```

Every stage is invoked synchronously. A failed Lambda response, malformed
response, incomplete quality contract, or failed quality check stops the chain;
all later stages remain `blocked`. The controller writes a sanitized latest-run
object after each transition and then raises on failure so EventBridge Scheduler
can apply retries and its DLQ policy.

The deployed functions use two success response forms: `status: ok` and
`ok: true`. The controller accepts both, forwards the same logical date as
`logical_run_date` and `run_date`, and never copies target names, query IDs,
exception text, ARNs, or storage paths into the status object.

Controller dry-run mode validates only its ordered configuration. It does not
invoke any target or write the latest status object because the existing
generator does not implement a non-writing dry run.

## Athena quality gates

`lambda/glap_data_quality_gate.py` runs aggregate-only checks before the AI
decision stages and after the flywheel. It validates:

- presence of the expected logical date in every required table;
- non-empty input and output control totals;
- duplicate counts at each table's documented business-key grain;
- shipment-volume change against the previous logical day;
- exact alignment of every required table's latest date.

Both gates use `simulated_iceberg_m.fact_shipment_v2` as their volume baseline,
because that table drives the current AI path. The public
`fact_shipment_events_extended_iceberg` contract is a separate display source
and is not used for this gate.

The generated SQL was executed successfully in Athena on 4 August 2026:

| Gate | Current tables | Aggregate rows | Duplicate keys | Shipments today / prior day |
| --- | ---: | ---: | ---: | ---: |
| Input v2 domains | 6 / 6 | 5,827 | 0 | 402 / 486 |
| Current AI outputs | 6 / 6 | 26 | 0 | 402 / 486 |

The observed volume change was approximately `17.3%`, below the initial `50%`
guardrail. The threshold is a deployment parameter and should be tightened only
after a longer daily distribution is measured.

## Deployment boundary

`infrastructure/pipeline-reliability.yaml` creates:

- the controller and quality-gate Lambdas;
- least-privilege Lambda roles scoped to the configured tables, prefixes, and
  existing stage functions;
- a private, encrypted, versioned status bucket;
- an encrypted 14-day Scheduler DLQ;
- controller, quality-gate, duration, and DLQ alarms;
- a replacement 00:05 schedule with two retries over 24 hours.

The replacement schedule defaults to `DISABLED`. Deployment does not authorize
schedule cutover. Package the controller, quality gate, and staging stub as
`lambda_function.py`, upload the artifacts to a private deployment bucket,
validate the template, and create a
reviewable CloudFormation change set with environment-specific result and data
prefixes.

For the first staging deployment, point all four mutating stage parameters to
`glap-pipeline-stage-stub-staging`. The bundled stub returns the deployed
`status: ok` contract but performs zero writes. The real input and output Athena
quality gates can then be exercised around those stubs, including a deliberately
low volume threshold to prove downstream blocking, without invoking any current
generator or decision function.

Only after the controlled-failure procedure in the
[pipeline reliability runbook](runbooks/pipeline_reliability.md) passes should
the replacement schedule be enabled, the four separate current schedules be
disabled, and required OPS verification be turned on. Keep schedule definitions
available for rollback and handle the separate legacy 08:00/09:00 schedules as
a later, explicit cleanup.

## Isolated staging evidence — 4 August 2026

The `glap-pipeline-reliability-staging` CloudFormation stack is deployed with:

- a disabled `00:05 Australia/Sydney` replacement schedule;
- all four mutating stages pointed to the bundled zero-write stub;
- real Athena input and output quality gates;
- a private versioned status object, encrypted DLQ, and CloudWatch alarms.

A controlled failure used a temporary `0%` volume-change threshold. Generation
and raw-to-Iceberg stubs succeeded, input validation recorded
`quality_gate_failed`, and decision, flywheel, and output-validation stages all
remained `blocked`. The controller invocation returned a Lambda function error,
proving that Scheduler retry and DLQ handling can observe the failure.

The stack was then restored to the `50%` threshold and manually invoked again.
All six stages succeeded and both validation stages reported all five checks as
passed (`10/10` total). The replacement schedule remained disabled throughout.
No current generator, loader, decision, flywheel, or existing schedule was
modified or invoked by these staging exercises.

This proves the isolated control path, not production cutover. Required OPS
verification remains disabled until the controller targets the governed current
functions, a complete live-path run succeeds, and the old schedules are disabled
with a documented rollback window.

## Production schedule cutover — 4 August 2026

Before cutover, the controller was updated to reuse any same-day persisted
status. A repeated invocation against the staging success record returned in
approximately 2.5 seconds, did not invoke a stage, and left the versioned status
object unchanged. Same-day failed or indeterminate state also fails closed;
automatic retries cannot replay the current non-idempotent AI inserts.

The CloudFormation stack now targets the four governed current functions and
the real Athena quality gate. A configuration-only dry run reported all six
stages as `not_invoked`, confirming that no production target was called during
the configuration check.

The reversible cutover command then:

- stored the complete prior schedule configuration in the private status bucket;
- disabled `glap_daily_generator`, `glap_daily_orchestrator`,
  `glap-ai-orchestrator-daily`, `glap-ai-flywheel-orchestrator-daily`, and the
  legacy `glap-generator-daily` schedule;
- enabled `glap-success-gated-daily` at `00:05 Australia/Sydney`;
- preserved two retries, a 24-hour maximum event age, and the encrypted DLQ;
- aligned the CloudFormation desired schedule state to `ENABLED`.

The first real success-gated run is scheduled for 5 August 2026 at 00:05 Sydney
time. Required OPS status verification remains disabled until that run completes
all six stages and all ten quality checks. The unrelated historical 09:00
schedules remain outside this cutover and continue to be reported as legacy
contracts rather than current OPS health.
