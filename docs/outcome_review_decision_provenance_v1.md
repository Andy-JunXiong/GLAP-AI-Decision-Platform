# Outcome Review decision provenance v1

**Status:** deployed and reader/RBAC verified in private staging; no eligible
bound cohort observed; COST_ANOMALY producer/readers deployed and RBAC verified;
bounded parallel-read correction deployed; one small-sample observation complete

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

## Bounded read-latency correction

The existing Outcome list and Decision-cohort aggregate are independent reads
needed by one complete authenticated response. The API correction starts
both unchanged Athena queries together with separate clients and exactly two
bounded workers, then restores their results to the existing list/summary
positions. It does not cache or omit either query, change either SQL statement,
alter the server-derived Sydney cutoff, add permissions, or change the response
contract.

If either read fails, the complete response still fails closed; no partial list
or cohort summary is returned. The existing per-query timeout and cancellation
behavior remains inside `_query_rows`. Commit `66eeb52` passed CI, and separately
authorized workflow run `33220634162` passed contract tests and updated the
private staging stack. It performed no post-deployment live read or latency
measurement at that deployment checkpoint. The earlier three-sample
`outcomes_pending` latency result motivated the bounded change but did not prove
its eventual runtime effect.
A later separately authorized frozen-workload observation returned three
`outcomes_pending` samples at p95 2,913 ms, compared descriptively with the
earlier 7,054 ms observation. All 20 requests were 2xx, but overall p95
4,996 ms still failed the unchanged gate because other routes remained above
it. The sample is too small to attribute the difference to parallel execution;
no causal improvement, production-performance, retry, or further-optimization
claim follows.

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
passed read-only and four-role verification. Actual-calendar run `33020683956`
later invoked the Generator. The subsequent Cost query found zero natural
proposals and therefore no eligible bound cohort. Cost producer/API/cockpit revisions are deployed and reader/RBAC
verified. Tests establish query, API-type, cockpit-disclosure,
legacy-null, and drift behavior without creating runtime evidence.

The next repository-local consumer is the versioned Decision-contract Outcome
cohort summary. It uses these two nullable provenance fields as governed group
keys, admits only observed bound Outcomes, and reports descriptive synthetic
statistics without inferring causality or value. See
[`decision_contract_outcome_cohort_v1.md`](decision_contract_outcome_cohort_v1.md).

The SLA Outcome provenance readiness audit is a second repository-local
consumer. It does not change the response contract; it checks whether the
runtime-verified natural SLA proposal is still waiting for named-human review,
an Outcome, or its due date, or whether a latest closed Outcome is ready for
provenance verification. The separately authorized `2026-08-27` run returned
`WAITING_HUMAN_REVIEW`: the exact-bound proposal exists, but no named-human
completion or Outcome exists, and every drift check remained valid.
See [`sla_outcome_provenance_readiness_v1.md`](sla_outcome_provenance_readiness_v1.md).
