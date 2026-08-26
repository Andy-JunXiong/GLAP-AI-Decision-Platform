# COST_ANOMALY runtime evidence reconciler v1

**Status:** executed against staging on `2026-08-27`; failed closed because no
naturally generated Cost proposal existed

This read-only, aggregate-only reconciler prepares the final evidence check for
the deployed `COST_ANOMALY` Decision Brief. It validates a naturally generated
operational-calendar Cost proposal after a separately authorized lifecycle
continuation; it does not invoke the Generator and does not create, backfill,
edit, approve, reject, or complete an Action.

## Runtime observation

The separately authorized `2026-08-27` query completed successfully. The
required natural-proposal check returned `False`: the bounded actual-calendar
cohort contained zero Cost proposals. The other six aggregate checks returned
`True`, including zero invalid bindings and zero pre-release Cost Actions with
invented bindings. Because the candidate count was zero, the reconciler failed
closed and established no runtime Decision-binding evidence. It was not retried
and no data was manufactured.

## Pass contract

The reconciler fails closed unless all of these conditions hold:

- At least one naturally generated proposal exists on or after the bounded
  release date and no later than the current Australia/Sydney business date.
- Every proposal is `OPERATIONAL` / `ACTUAL_CALENDAR`, has no scenario ID, and
  traces to one same-date open `COST_ANOMALY` Alert with exact
  `SHIPMENT_COST` / `TOTAL_COST` / `cost_variance_pct` fields.
- The source variance and threshold are finite and non-negative, and variance
  strictly exceeds the threshold.
- Every immutable Action uses the exact `decision-brief.v1` / `REVIEW_COST`
  pair and a rationale bound to `stateful-cost-variance.v1`.
- Each source Action remains an unreviewed `PROPOSED` row requiring approval;
  the current view preserves the same immutable Decision binding.
- Pre-release Cost Actions remain legacy-null rather than being backfilled.

Future simulation cannot satisfy the gate. The output contains only named
boolean checks and never prints an Action, Alert, shipment, actor, request, AWS,
or storage identifier.

## Execution and authority boundary

Each run of `ops/reconcile_cost_anomaly_runtime_staging.ps1` starts one read-only
Athena `SELECT`. Athena writes its query-result object to the already configured
protected results location, so running the script is still an external AWS
operation and any future rerun requires separate human authorization. The script itself issues
no lifecycle invocation, table mutation, API mutation, workflow dispatch,
deployment, identity change, schedule, alias, Pages publication, policy action,
model action, or production action.

A passing result establishes only synthetic staging engineering evidence that
the deployed producer preserved the Cost Decision binding on a naturally
eligible proposal. It does not establish human approval, execution, realised
value, causal effect, real logistics performance, model readiness, policy
readiness, or production readiness.
