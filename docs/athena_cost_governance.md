# Athena cost governance RFC

**Status:** designed, not deployed

**Scope:** private GLAP staging analytics

This RFC defines the review gate before any recurring lifecycle, forecast, or
analytics execution is proposed. It does not change an Athena workgroup, IAM,
CloudFormation, alarms, schedules, or production data.

## Workgroup boundary

The approved implementation must create or select one staging-only Athena
workgroup with engine version 3, an enforced encrypted result location, and no
permission to write production tables. A named human analytics steward must own
the workgroup, alarm response, budget changes, and rollback decision.

The initial per-query ceiling is 100 MiB for the existing forecast-feature and
label-readiness readers because those callers already measure and fail on that
budget. Operations API and operational-baseline queries must first collect a
reviewed scan baseline; this RFC does not invent a cutoff without evidence.

Every governed query record must retain, privately:

- query ID and query class;
- workgroup and logical date;
- execution mode and temporal scope;
- bytes scanned and applicable budget;
- terminal outcome and safe failure category.

Raw SQL, S3 paths, entity identifiers, account IDs, and ARNs must not enter a
public artifact or alarm notification.

## Alarm design

The future change set must include separate alarms for failed queries and
budget-cutoff events. Each alarm needs a named owner, response target, private
runbook, threshold justification, and recovery signal. A budget event must fail
the requesting workflow; it cannot silently reuse an old result as current.

Cost dashboards may aggregate scan bytes by query class, logical date, and
outcome. They must not expose query text or shipment-level values.

## Rollout and rollback

1. Measure Operations API and baseline-query scan distributions without
   changing enforcement.
2. Review projected scan cost, result retention, late-arrival behavior, and
   rollback with the analytics steward.
3. Create a plan-only change set for a staging workgroup and alarms.
4. Exercise one successful query, one cutoff, and one failed query.
5. Confirm the last verified consumer state becomes explicitly stale on failure.
6. Require separate human approval before applying or enabling any schedule.

Rollback restores the prior workgroup reference and disables the proposed
caller, but it must not erase query evidence or mark the failed interval fresh.

The machine-readable design is
[`production_readiness_contract.json`](production_readiness_contract.json).
