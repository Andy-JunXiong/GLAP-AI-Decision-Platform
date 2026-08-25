# Outcome cohort comparison provenance drill-down v1

**Implementation status:** implemented and locally verified
**Deployment status:** not deployed

This authenticated, read-only drill-down explains where each cohort displayed
in `outcome-cohort-descriptive-comparison.v1` came from. It traces the aggregate
to its immutable Decision binding and the exact cutoff, evidence, aggregation,
and threshold contracts without exposing entity identifiers.

## Provenance contract

Every displayed eligible cohort includes
`outcome-cohort-comparison-provenance.v1` with:

- Decision Brief version and selected alternative;
- binding source `IMMUTABLE_ACTION_PROPOSAL`;
- Sydney `as_of_date`;
- `OPERATIONAL` / `ACTUAL_CALENDAR` evidence basis;
- evidence class `SYNTHETIC_OPERATIONAL_CALENDAR_OUTCOME_COHORT`;
- aggregation contract `outcome-cohort-summary.v1`;
- threshold contract `outcome-cohort-threshold-contract.v1`;
- explicit observed-only, pending-excluded, unbound-excluded, and future-
  simulation-excluded flags.

The private cockpit renders this information in a per-cohort disclosure under
the comparison card. It does not issue another query or fetch entity rows.

## Privacy and authority boundary

The drill-down is aggregate-only. Action, Outcome, and shipment identifiers are
not included, and the contract explicitly keeps all three identifier-exposure
flags false. It cannot be used to mutate or reclassify any underlying record.

Provenance establishes traceability, not validity of a preferred alternative.
It does not produce ranking, causal or statistical superiority, realised value,
real logistics performance, an Action recommendation, Learning/model readiness,
policy authority, deployment approval, or production readiness.

This feature reuses the existing authenticated aggregate response and adds no
query, route, table, environment value, CloudFormation change, mutation,
schedule, AWS call, public export, or external write. The prerequisite Action
binding migration is applied and six-check validated; staging activation
requires separate producer and reader deployment authority.

The companion
[`outcome_cohort_comparison_fingerprint_v1.md`](outcome_cohort_comparison_fingerprint_v1.md)
computes a deterministic digest over this provenance and its displayed
aggregate. It does not turn provenance into an authenticity claim.
