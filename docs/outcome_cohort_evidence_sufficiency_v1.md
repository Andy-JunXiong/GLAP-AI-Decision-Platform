# Outcome cohort evidence-sufficiency gate v1

**Implementation status:** implemented and locally verified
**Configuration status:** `HUMAN_APPROVED_CONTRACT`
**Deployment status:** not deployed

This gate prevents descriptive synthetic Outcome cohorts from being presented
as comparable before a human-approved evidence threshold exists. The project
owner approved the v1 values on the Sydney date `2026-08-25`, and the local
runtime contract now consumes them.

## Approved threshold contract

The machine-readable contract is
[`outcome_cohort_threshold_contract_v1.json`](outcome_cohort_threshold_contract_v1.json),
validated against
[`outcome_cohort_threshold_contract_v1.schema.json`](outcome_cohort_threshold_contract_v1.schema.json).
It records:

- contract version `outcome-cohort-threshold-contract.v1`;
- `minimum_observed_outcomes = 20` per Decision-contract cohort;
- `minimum_distinct_result_states = 2` among `SUCCESSFUL`,
  `PARTIALLY_SUCCESSFUL`, `FAILED`, and `INCONCLUSIVE`;
- comparison scope `DESCRIPTIVE_SYNTHETIC_ONLY`.

The values are fixed repository inputs, not environment defaults or
automatically selected thresholds. Changing either value requires a new
versioned contract and a new explicit human approval.

## Fail-closed runtime contract

The authenticated Outcome response now supplies all three approved inputs—the
two thresholds and the versioned threshold-contract identifier—and states:

```json
{
  "schema_version": "outcome-cohort-evidence-sufficiency.v1",
  "configuration_status": "HUMAN_APPROVED_CONTRACT",
  "threshold_contract_version": "outcome-cohort-threshold-contract.v1",
  "thresholds": {
    "minimum_observed_outcomes": 20,
    "minimum_distinct_result_states": 2
  },
  "comparison_scope": "DESCRIPTIVE_SYNTHETIC_ONLY",
  "any_comparison_eligible": false
}
```

The mechanism compares each cohort's sample count and distinct result-state
count with the approved values. Passing both may produce
`SUFFICIENT_FOR_DESCRIPTIVE_COMPARISON`; failing either produces
`INSUFFICIENT_EVIDENCE`. Even a passing cohort remains descriptive synthetic
evidence only. The lower-level builder still rejects partial or invalid
configuration, and repository drift checks reject any code/contract mismatch.
The companion
[`outcome_cohort_evidence_gap_v1.md`](outcome_cohort_evidence_gap_v1.md)
reports the exact non-negative shortfall to each target without recommending
Outcome creation or lifecycle continuation.

## Authority boundary

This approval authorizes only the two v1 descriptive-gate values. The gate
cannot select its own thresholds, change an approved contract,
create a cohort, change an Outcome, estimate causality or realised value,
establish real logistics performance, authorize a model or policy, or grant
deployment or production authority. It adds no route, table, CloudFormation
change, environment configuration, mutation, schedule, or external write.

The prerequisite Action binding migration is applied and six-check validated
in isolated staging. Activating this gate still separately requires producer
and reader deployment authority plus runtime verification.
