# SLA_BREACH Decision Brief v1

**Status:** deployed private staging readers and producer verified; Generator
invoked on `2026-08-27`; corrected aggregate-only SLA runtime reconciliation
found natural proposals and passed all seven exact-source, exact-binding,
immutable-state, current-view, and legacy-null checks; named-human review is
still pending behind a private-cockpit navigation gap

Decision Brief v1 turns one current governed `SLA_BREACH` Alert into a bounded,
human-reviewable decision explanation. It is intentionally narrow, adds no AI
layer, and estimates no intervention effect that the available data cannot
support. `COST_ANOMALY` now has a deployed staging companion contract under the
same schema version; see
[`cost_anomaly_decision_brief_v1.md`](cost_anomaly_decision_brief_v1.md).

## Entry contract

A brief is created only when all of these conditions hold:

- `alert_type = SLA_BREACH`;
- `alert_grain = SHIPMENT_MILESTONE`;
- `status = OPEN`;
- the milestone and delay metric are one of the seven governed pairs emitted by
  the stateful lifecycle generator;
- the numeric delay exceeds a non-negative threshold;
- the API cutoff is a valid Australia/Sydney operational date.

Resolved Alerts, mismatched milestone/metric pairs, non-finite values, and
non-breaches do not receive an SLA Decision Brief. Invalid SLA inputs fail
closed rather than falling back to a plausible-looking recommendation. Cost
Alerts are dispatched only to their separately validated Cost contract.

## Output contract

The versioned `decision-brief.v1` response contains:

- observed Alert input: severity and affected milestone;
- derived exposure: delay hours, threshold, breach margin, and one affected
  shipment at the Alert's governed grain;
- deterministic urgency derived only from severity;
- the existing `EXPEDITE_MILESTONE` recommendation;
- three bounded alternatives: expedite, monitor the next milestone, or take no
  action;
- no-action exposure expressed in delay hours, never invented currency;
- an explicit unestimated benefit contract;
- all-false execution, Outcome, and financial-value authority.

The benefit shape is deliberately minimal:

```json
{
  "status": "NOT_ESTIMATED",
  "estimate_evidence_class": "NOT_ESTIMATED",
  "assumption_set_version": null
}
```

`assumption_set_version` remains `null` because v1 has no intervention-effect
assumptions. Calculation-contract, uncertainty-method, and provenance metadata
for estimates are not added until a genuine estimate exists.

## Business process connection

```text
OPEN SLA_BREACH Alert
  -> deterministic Decision Brief v1
  -> immutable Action proposal binding
  -> named-human append-only review
```

The brief itself performs no mutation. The repository now implements the next
schema-level step: newly generated eligible SLA Actions preserve the brief
version, deterministic selected alternative, and proposal rationale on the
immutable Action row. Named-human review reasons remain append-only audit
events because they do not exist when the system creates the proposal. See
[`decision_action_binding_v1.md`](decision_action_binding_v1.md). The binding
is schema-deployed and reader/RBAC verified. The Generator was invoked on
`2026-08-27`, but that workflow exposed no aggregate SLA proposal or binding
count. The later separately authorized SLA reconciliation found natural
proposals whose source and immutable-state checks passed, but at least one
proposal failed the exact binding and the invalid-binding count was non-zero.
The aggregate result established no root cause or bound SLA runtime evidence. See
[`sla_breach_runtime_evidence_v1.md`](sla_breach_runtime_evidence_v1.md).

The same reconciler's separately authorized binding diagnostic retained the
full gate and separately reported brief version, Action type, selected
alternative, rationale shape, and rationale value. The first three passed; both
rationale checks failed. Versioned deployed source matches the expected
template, but the aggregate result cannot distinguish persisted-text from
verifier-expression drift and therefore establishes no root cause.

A regex-independent `-RationaleDiagnostic` mode splits presence, exact
milestone prefix, governed suffix, numeric token, and numeric equality into
five identifier-free booleans. Its first separately authorized execution
failed before results on `ENDS_WITH_EXPRESSION`; after a local `length` plus
`substr` correction, the separately authorized retry returned all five
rationale-only booleans true while the legacy regex checks remained false.
This validates the persisted rationale and isolates verifier-expression drift:
`[A-Z_]+` excludes digits in governed `P2P_*` milestones. The local full-gate
verifier now reuses the compositional rationale checks and contains no rationale
regex. The separately authorized corrected full reconciliation returned all
seven aggregate booleans true, establishing synthetic staging runtime evidence
for the natural SLA Decision binding. The mode cannot repair a proposal and no
Action was mutated.

## Evidence boundary

The input is `SYNTHETIC_OPERATIONAL_CALENDAR_ALERT`. Within the brief,
`OBSERVED_INPUT` means observed as an input to this decision contract; it does
not mean real-world logistics evidence. Derived delay exposure is
`DERIVED_EXPOSURE`. Expected benefit is `NOT_ESTIMATED`.

Local tests plus private reader/RBAC verification establish deterministic
contract and access mechanics. The later lifecycle continuation establishes
Generator invocation only. The local aggregate-only reconciler validates an
exactly-one same-date source Alert, one of seven governed milestone/metric
pairs, the exact immutable rationale, current-view agreement, and the legacy-
null boundary. Its original `2026-08-27` staging run passed the source,
immutable-state, current-view, and legacy-null checks but failed the two
regex-based exact-binding checks. The later diagnostics validated the persisted
rationale, isolated digit-excluding verifier drift, and the corrected full
reconciliation returned all seven booleans true. This establishes synthetic
staging runtime binding evidence only. No named-human judgment, Action
execution, Outcome observation attributable to this contract, production
change, or Pages publication has been established.

The subsequent named-human staging inspection found that Decision Queue's
`Review now` control opens the unscoped Action Board rather than the selected
full brief. Navigation labels the risk entry `Signals` while the destination
page title is `Risk hotspots`. The reviewer submitted no mutation. The next
frontend slice must preserve selected-Action context and expose its complete
bound brief before the human review journey is treated as usable.
