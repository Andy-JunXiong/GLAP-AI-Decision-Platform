# Decision-contract Outcome cohort summary v1

**Status:** deployed and reader/RBAC verified in private staging; no eligible
bound cohort observed

This contract adds a versioned, descriptive cohort summary to the existing
authenticated `GET /v1/outcomes` response. It groups eligible synthetic
Outcome evidence by the immutable Decision Brief version and selected
alternative that produced the connected Action proposal.

## Eligibility

The server derives the Australia/Sydney cutoff and includes only the latest
version of an Outcome when every condition below holds:

- Outcome scope and execution mode are `OPERATIONAL`;
- Outcome time basis is `ACTUAL_CALENDAR`;
- status is `SUCCESSFUL`, `PARTIALLY_SUCCESSFUL`, `FAILED`, or `INCONCLUSIVE`;
- `observed_date` is present and no later than the cutoff;
- `effect_pct` is numeric;
- the joined immutable Action is operational, actual-calendar, cutoff-eligible;
- both `decision_brief_version` and `selected_alternative` are non-empty.

Pending Outcomes, future simulations, legacy Actions, and Actions without an
implemented Decision Brief binding are excluded. The aggregate query has no
entity identifiers in its output and no list `LIMIT`; the cohort counts are not
derived from the separately bounded Outcome card list.

## Response

The existing Operations API response gains `cohort_summary`:

```json
{
  "schema_version": "outcome-cohort-summary.v1",
  "status": "AVAILABLE",
  "cohorts": [
    {
      "decision_brief_version": "decision-brief.v1",
      "selected_alternative": "EXPEDITE_MILESTONE",
      "observed_outcome_count": 3,
      "status_counts": {
        "successful": 1,
        "partially_successful": 1,
        "failed": 1,
        "inconclusive": 0
      },
      "effect_pct": {
        "minimum": -5.0,
        "average": 2.5,
        "maximum": 15.0
      }
    }
  ]
}
```

The server fails closed if status counts do not reconcile with the cohort
sample count, any effect statistic is non-finite, or the minimum/average/maximum
ordering is invalid. No eligible cohort returns
`NO_ELIGIBLE_BOUND_OUTCOMES`; it is not treated as zero effect or evidence of
success or failure.

## Governance boundary

The summary is descriptive synthetic engineering evidence only. Grouping and
averaging simulated effects does not establish treatment assignment,
counterfactual comparison, causal impact, realised financial value, real
logistics performance, model readiness, production readiness, or policy
activation authority.

The feature reuses the existing authenticated endpoint, tables, roles, and
read permissions. It adds no route, table, mutation, Learning threshold,
schedule, model, or production path. A named human applied the Action binding
migration in `sql/16_decision_action_binding_v1.sql` and all six aggregate
checks returned zero; producer/API/frontend deployment and cohort runtime
verification remain separate.

The response now also carries a fail-closed evidence-sufficiency gate. Its
mechanics evaluate the project-owner-approved minimum of 20 observed Outcomes
and two represented result states. A cohort passing both becomes eligible only
for descriptive synthetic comparison. See
[`outcome_cohort_evidence_sufficiency_v1.md`](outcome_cohort_evidence_sufficiency_v1.md).
It also exposes the exact arithmetic shortfall to each approved target without
recommending evidence collection; see
[`outcome_cohort_evidence_gap_v1.md`](outcome_cohort_evidence_gap_v1.md).
When at least two cohorts pass, the response can render their descriptive
status mixes and effect ranges side by side without ranking or selecting an
alternative; see
[`outcome_cohort_descriptive_comparison_v1.md`](outcome_cohort_descriptive_comparison_v1.md).
Each displayed comparison item also traces its aggregate-only Decision binding
and evidence contracts without identifiers; see
[`outcome_cohort_comparison_provenance_v1.md`](outcome_cohort_comparison_provenance_v1.md).
