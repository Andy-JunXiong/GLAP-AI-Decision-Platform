# Eligible Outcome cohort comparison view v1

**Implementation status:** implemented and locally verified
**Deployment status:** not deployed

This authenticated, read-only view places eligible Decision-contract Outcome
cohorts side by side. It is available only when at least two cohorts
independently pass the project-owner-approved 20 observed Outcome / two
represented result-state gate.

## Availability contract

`outcome-cohort-descriptive-comparison.v1` returns:

- `AVAILABLE` only when `eligible_cohort_count >= 2`;
- `INSUFFICIENT_ELIGIBLE_COHORTS` otherwise;
- an empty `cohorts` array while unavailable, so one eligible cohort is never
  presented as a comparison;
- eligible and excluded cohort counts so the unavailable state is explicit;
- comparison scope `DESCRIPTIVE_SYNTHETIC_ONLY`.

The existing `outcome-cohort-evidence-gap.v1` fields explain why excluded
cohorts do not pass. The unavailable state does not recommend collecting or
creating evidence.

## Displayed evidence

For each eligible cohort, the view projects only:

- immutable Decision Brief version and selected alternative;
- observed synthetic Outcome count;
- successful, partially successful, failed, and inconclusive percentages;
- descriptive minimum, average, and maximum effect percentages.

Status percentages are derived from reconciled counts already validated by the
cohort summary. The view preserves server query order and does not sort cohorts
by effect or status.

## Interpretation and authority boundary

Side-by-side display is not a ranking or treatment comparison. The contract
keeps `ranking_produced`, `preferred_alternative_selected`,
`causal_superiority_estimated`, `statistical_significance_estimated`, and
`action_recommended` false. It does not claim that one alternative caused a
result, is financially superior, or should be selected.

The source remains synthetic `OPERATIONAL` / `ACTUAL_CALENDAR` Outcome evidence
under the Sydney cutoff. The view establishes no real logistics performance,
realised value, statistical inference, Learning/model readiness, policy
authority, deployment approval, or production readiness.

This feature reuses the existing aggregate response and adds no query, route,
table, environment value, CloudFormation change, mutation, schedule, AWS call,
or external write. The prerequisite Action binding migration is applied and
six-check validated; staging activation requires separate producer and reader
deployment authority.

Each displayed cohort includes the aggregate-only provenance contract defined
in
[`outcome_cohort_comparison_provenance_v1.md`](outcome_cohort_comparison_provenance_v1.md).
That trace does not expose cohort member identifiers or create another query.
The complete comparison item is also covered by the unsigned deterministic
fingerprint defined in
[`outcome_cohort_comparison_fingerprint_v1.md`](outcome_cohort_comparison_fingerprint_v1.md).
