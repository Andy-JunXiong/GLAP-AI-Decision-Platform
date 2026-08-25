# Outcome cohort evidence-gap explainer v1

**Implementation status:** implemented and locally verified
**Deployment status:** not deployed

This read-only projection explains how far each Decision-contract Outcome
cohort is from the project-owner-approved descriptive comparison gate. It uses
the same cutoff-eligible counts already returned by
`outcome-cohort-summary.v1` and the exact targets in
`outcome-cohort-threshold-contract.v1`.

## Contract

Each cohort includes `outcome-cohort-evidence-gap.v1` with:

- `additional_observed_outcomes`: `max(20 - observed_outcome_count, 0)`;
- `additional_distinct_result_states`: `max(2 - distinct_result_states, 0)`;
- `status = TARGET_MET` only when both gaps are zero;
- `status = GAP_REMAINS` when either gap is positive;
- `status = PENDING_HUMAN_APPROVAL` and null gaps if the lower-level builder is
  invoked without a complete approved threshold contract.

The private cockpit displays both arithmetic gaps beside the existing sample,
status, effect, and comparison-eligibility fields. A zero gap means only that
the approved minimum descriptive evidence shape is present.

## Evidence and authority boundary

The explainer is a calculation, not a data-collection plan. It does not
recommend creating Outcomes, advancing the lifecycle, changing result states,
targeting a desired conclusion, or continuing operational dates. The contract
therefore keeps `calculation_only=true` and all of
`outcome_collection_recommended`, `outcome_creation_authorized`, and
`lifecycle_continuation_authorized` false.

Meeting both targets permits descriptive comparison of synthetic actual-
calendar cohorts only. It does not establish causality, realised value, real
logistics performance, statistical significance, Learning or model readiness,
policy authority, deployment approval, or production readiness.

This feature adds no query, route, table, environment value, CloudFormation
change, mutation, schedule, AWS call, or external write. The prerequisite
Action binding migration is applied and six-check validated; staging activation
still requires separate producer and reader deployment authority.

The companion
[`outcome_cohort_descriptive_comparison_v1.md`](outcome_cohort_descriptive_comparison_v1.md)
uses zero-gap eligible cohorts only after at least two are available; it does
not convert a gap into collection authority.
