# COST_ANOMALY Decision Brief v1

**Status:** producer, authenticated API, and private cockpit deployed and
reader/RBAC verified in staging; no bound runtime Cost proposal observed

This contract turns one current governed `COST_ANOMALY` Alert into a bounded,
human-reviewable explanation. It reuses `decision-brief.v1`, the existing
immutable Action binding, and the authenticated private reader surfaces. It
adds no Action-creation endpoint and estimates neither financial exposure nor
intervention benefit.

## Entry contract

A Cost brief exists only when all of these conditions hold:

- `alert_type = COST_ANOMALY`;
- `alert_grain = SHIPMENT_COST`;
- `alert_dimension = TOTAL_COST`;
- `metric_name = cost_variance_pct`;
- `status = OPEN`;
- severity is one of the governed four levels;
- finite non-negative variance and threshold values are present, and variance
  strictly exceeds the threshold;
- the API cutoff is a valid Australia/Sydney operational date.

Mismatched grain, dimension, or metric does not receive a plausible-looking
brief. Invalid numeric, severity, or threshold inputs fail closed.

## Deterministic output

The brief reports the observed variance, governed threshold, percentage-point
breach margin, and one affected shipment at the Alert grain. It deterministically
selects `REVIEW_COST` and also exposes `MONITOR_COST` and `NO_ACTION` as bounded
alternatives. The immutable Action proposal stores:

```json
{
  "decision_brief_version": "decision-brief.v1",
  "selected_alternative": "REVIEW_COST",
  "selection_rationale": "Review the governed cost basis under stateful-cost-variance.v1; total cost variance is <margin> percentage points above threshold."
}
```

The selection remains a system proposal requiring named-human review. It is
not approval, carrier instruction, cost correction, or execution.

## Cost-source provenance

The source calculation contract is exact:

```json
{
  "source_contract_version": "stateful-cost-variance.v1",
  "rate_card_version": null,
  "rate_card_version_status": "UNAVAILABLE_IN_ALERT_CONTRACT"
}
```

The existing persisted Alert carries the governed cost-variance result but not
the shipment's rate-card version. V1 therefore preserves the exact calculation
source version and explicitly refuses to infer a rate-card identifier. Adding
immutable rate-card provenance would require a separately reviewed data-contract
migration; it is not silently claimed by this feature.

## Evidence and authority boundary

`OBSERVED_INPUT` means observed inside the synthetic operational-calendar
contract, never real logistics evidence. Variance exposure is
`DERIVED_EXPOSURE`; `monetary_value` stays `null`; benefit remains
`NOT_ESTIMATED` with no assumption set. Execution, Outcome, and financial-value
authority remain false.

Existing Cost Actions remain legacy-null and are never backfilled. The repository
validator revision permits a future new Cost binding only when the exact
`decision-brief.v1` / `REVIEW_COST` pair and a non-empty rationale are present.
The exact-pair validator revision has not run in staging.

## Staging release evidence

Commit `0e5b740` passed CI run `32982375432`. Generator plan run `32982600783`
accepted one non-replacing `LifecycleGeneratorFunction` modification, then
deleted the change set without upload or execution. Separately authorized
deploy run `32982946620` released only that independent Generator resource.
Operations API plan run `32982375374` and deploy run `32983721998` succeeded,
and the named human published the matching private cockpit without printing
protected deployment identifiers. The read-only verifier and the separately
authorized four-role matrix passed; all four temporary users were removed.

These runs establish staging delivery and reader/RBAC behavior only. The
Generator was not invoked, no new Action was created or mutated, and no bound
Cost Decision Brief was observed. No lifecycle continuation, schedule, alias,
Pages publication, policy activation, model promotion, or production change
occurred.
