# Governed exception-to-outcome contract

**Business-date boundary:** Australia/Sydney
**Implementation status:** repository logic and tests complete; new AWS persistence tables are not deployed

The governed closed loop connects lifecycle evidence without allowing synthetic
learning to change either the generator or an effective policy automatically:

```text
Lifecycle snapshot
-> stable SLA_BREACH / COST_ANOMALY candidate
-> cross-day alert (OPEN / RESOLVED)
-> human-approved action
-> delayed simulated outcome
-> learning evidence
-> PENDING_HUMAN_REVIEW policy proposal
-> separately approved policy version with rollback target
```

## Alert contract

An alert keeps the candidate's stable fingerprint, shipment grain and explicit
dimension. The first and last detection dates survive daily reconciliation. A
missing candidate resolves an open alert; it does not delete its history.

`SLA_BREACH` is emitted per shipment milestone. `COST_ANOMALY` is emitted per
shipment total-cost comparison. Public use is aggregate-only and every row is
labelled simulated.

## Action and outcome contract

Every proposed action requires a named human reviewer. System, automation and
model actors cannot approve it. Only an approved and completed action may
produce an outcome.

Outcomes remain `PENDING` until their observation lag expires. Once due, the
result is reproducible from stable entity/version identifiers and depends on
action type, alert type and severity, shipment stage, carrier, execution delay,
and active-disruption context. Result states are `SUCCESSFUL`,
`PARTIALLY_SUCCESSFUL`, `FAILED`, and `INCONCLUSIVE`; all are `SIMULATED`.

## Learning and calendar gate

Learning may create a `PENDING_HUMAN_REVIEW` policy proposal after the configured
minimum observed-outcome count. A proposal cannot modify simulation
configuration, has no effective date before approval, and retains the current
policy version as its rollback target.

Operational model-readiness inputs must satisfy every condition below:

- `execution_mode = OPERATIONAL`;
- `time_basis = ACTUAL_CALENDAR`;
- outcome state is closed rather than pending;
- `observed_date` is on or before the Sydney as-of date.

`FUTURE_SIMULATION` outcomes are useful for workflow testing only. They never
count as observed labels, operational backtest evidence, or promotion evidence.

## Deployment boundary

[`glap_governed_closed_loop.py`](../lambda/glap_governed_closed_loop.py) is a
pure, deterministic domain layer. It is ready to be connected to private,
append-only alert/action/outcome/proposal tables. This change does not create
those tables, enable a recurring schedule, expose entity records publicly, or
activate a policy.
