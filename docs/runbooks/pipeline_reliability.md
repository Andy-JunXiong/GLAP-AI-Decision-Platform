# Pipeline reliability runbook

Use this runbook when the public OPS snapshot reports `failed`, `unverified`,
`running`, or `partial_or_stale`. The published status is deliberately
aggregate-only; investigate private resource details only in the authenticated
AWS account.

## Safety boundary

- Do not manually invoke a downstream stage while an upstream stage is failed.
- Do not set `AWS_OPS_PIPELINE_STATUS_REQUIRED=true` until the controller,
  validation stage, status object, and read permissions are deployed together.
- Do not copy Lambda names, ARNs, account IDs, S3 paths, Athena query IDs, raw
  records, or exception messages into the public snapshot.
- Keep the existing time-based schedules enabled until the replacement
  controller has passed a controlled-failure exercise; then disable the old
  schedules in a separate, reversible change.

## Triage by public failure category

| Category | Private checks | Safe recovery |
| --- | --- | --- |
| `quality_gate_failed` | Inspect the named validation check and its aggregate control totals | Correct or regenerate the source data, then rerun the complete controller |
| `quality_contract_invalid` | Verify the validator returned all five required checks | Restore the versioned response contract before retrying |
| `dependency_failure` | Inspect the failed stage's Lambda result and CloudWatch logs | Fix the dependency, then allow Scheduler retry or invoke the controller once |
| `invalid_response` | Check the stage returned JSON with `status: success` | Roll back or repair the stage response contract |
| `unexpected_failure` | Inspect controller and stage logs, throttles, duration, and IAM errors | Resolve the underlying fault; do not bypass the gate |
| `status_unavailable` | Check status-object existence, freshness, encryption, and read permission | Restore status publication/read access; keep OPS stale until verified |

## Required quality checks

The configured validation stage must return all five checks. Each check is
fail-closed: an omitted or unknown value blocks downstream execution.

1. `missing_dates` — the expected logical date and required recent dates exist.
2. `empty_inputs` — the logical run has at least one valid input record.
3. `duplicate_business_keys` — duplicate count for the documented stage grain is
   zero.
4. `abnormal_volume_change` — change from the approved comparison window is
   within its documented threshold or has an approved exception.
5. `stale_stage_outputs` — all outputs required at that gate match the allowed
   logical-run lag.

## Controlled-failure verification

Before replacing the current schedules:

1. Deploy the controller to staging with generation, validation, and the current
   v3/v2 flywheel as ordered targets.
2. Run a controller dry run and confirm no target is invoked and the latest
   production status object is not overwritten. This validates configuration,
   not target health.
3. In an isolated staging configuration, make the input validator return one
   failed check without changing production data.
4. Confirm the decision and flywheel targets were not invoked and remain `blocked` in the run
   status.
5. Confirm the controller invocation fails, Scheduler retry policy applies, and
   exhausted failures reach the encrypted DLQ.
6. Confirm an OPS export with required verification reports `failed` or `stale`,
   never `current`.
7. Restore the validator, run the complete staging chain, and confirm every stage and
   quality check succeeds before schedule cutover.

## Schedule cutover

Record the exact existing schedule names and targets privately. Enable the new
controller schedule first, observe one complete logical run, and only then
disable the separate generator/flywheel schedules. Keep their definitions for a
rollback window. Treat the legacy 08:00 pair as a separate retirement decision
after ownership and downstream dependencies are confirmed.

The repository cutover command is plan-only unless `-Apply` is supplied:

```powershell
.\ops\cutover_pipeline_reliability.ps1
.\ops\cutover_pipeline_reliability.ps1 -Apply
```

The apply path stores the complete pre-cutover schedule configuration beside the
private status object, disables the current schedules, and enables the
replacement. If any update fails, it disables the replacement and restores every
schedule already changed during that attempt.
