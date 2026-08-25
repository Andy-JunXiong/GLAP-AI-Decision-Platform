# SLA_BREACH Decision Brief v1

**Status:** implemented and locally verified; not deployed

Decision Brief v1 turns one current governed `SLA_BREACH` Alert into a bounded,
human-reviewable decision explanation. It is intentionally narrow: it does not
support `COST_ANOMALY`, does not add an AI layer, and does not estimate an
intervention effect that the available data cannot support.

## Entry contract

A brief is created only when all of these conditions hold:

- `alert_type = SLA_BREACH`;
- `alert_grain = SHIPMENT_MILESTONE`;
- `status = OPEN`;
- the milestone and delay metric are one of the seven governed pairs emitted by
  the stateful lifecycle generator;
- the numeric delay exceeds a non-negative threshold;
- the API cutoff is a valid Australia/Sydney operational date.

`COST_ANOMALY`, resolved Alerts, mismatched milestone/metric pairs, non-finite
values, and non-breaches do not receive a Decision Brief. Invalid SLA inputs
fail closed rather than falling back to a plausible-looking recommendation.

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
is locally verified and has not been migrated or deployed.

## Evidence boundary

The input is `SYNTHETIC_OPERATIONAL_CALENDAR_ALERT`. Within the brief,
`OBSERVED_INPUT` means observed as an input to this decision contract; it does
not mean real-world logistics evidence. Derived delay exposure is
`DERIVED_EXPOSURE`. Expected benefit is `NOT_ESTIMATED`.

Local implementation and tests establish deterministic contract mechanics
only. No API deployment, private-frontend deployment, AWS call, Action
mutation, Outcome observation, production change, or Pages publication has
occurred.
