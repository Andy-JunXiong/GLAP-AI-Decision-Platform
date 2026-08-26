# Outcome Review decision provenance v1

**Status:** deployed and reader/RBAC verified in private staging; no eligible
bound cohort observed; COST_ANOMALY producer/readers deployed and RBAC verified

This contract lets an authenticated reviewer see which immutable Decision
Brief proposal produced the Action connected to each cutoff-eligible Outcome.
It extends the existing `GET /v1/outcomes` response; it adds no endpoint,
mutation, table, or approval authority.

## Read-only relationship

The Outcome remains linked to its Action only by the existing immutable
`action_id`. The Operations API joins that identifier to the current Action
view at read time and returns two nullable fields:

```json
{
  "decision_brief_version": "decision-brief.v1",
  "selected_alternative": "EXPEDITE_MILESTONE"
}
```

Both the Outcome and the joined Action must be `OPERATIONAL` /
`ACTUAL_CALENDAR` and cutoff-eligible under the server-derived Sydney date.
The API does not copy Decision provenance into the Outcome table. This keeps
the immutable Action proposal as the single source and avoids creating a
second history that could drift.

Legacy and pre-release `COST_ANOMALY` Actions return null provenance and are
never backfilled. A future newly generated eligible Cost Action may expose the
exact `decision-brief.v1` / `REVIEW_COST` pair only after a separately authorized
lifecycle continuation. The cockpit labels all null rows as legacy or
unbound rather than inferring a source.

## Evaluation and governance boundary

The added fields let a private evaluator group synthetic Outcome effects by
the proposal contract and selected alternative instead of only broad Action
type. They establish traceability, not causality. In particular, this contract:

- does not claim the selected alternative was human-approved or executed;
- does not treat a simulated effect as real logistics performance;
- does not estimate incremental impact, financial value, or model quality;
- does not change Learning thresholds, policy state, or deterministic rules;
- does not add an Outcome, Action, approval, completion, or activation write.

The Action-side fields depend on the additive staging migration in
`sql/16_decision_action_binding_v1.sql`. A named human applied it and all six
aggregate checks returned zero on `2026-08-25`. The deployed private readers
passed read-only and four-role verification, while the Generator remained
uninvoked and no eligible bound cohort was observed. Cost producer/API/cockpit
revisions are deployed and reader/RBAC verified. Tests establish query, API-type, cockpit-disclosure,
legacy-null, and drift behavior without creating runtime evidence.

The next repository-local consumer is the versioned Decision-contract Outcome
cohort summary. It uses these two nullable provenance fields as governed group
keys, admits only observed bound Outcomes, and reports descriptive synthetic
statistics without inferring causality or value. See
[`decision_contract_outcome_cohort_v1.md`](decision_contract_outcome_cohort_v1.md).
