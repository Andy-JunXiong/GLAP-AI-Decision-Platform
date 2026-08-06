# Governed exception-to-outcome contract

**Business-date boundary:** Australia/Sydney
**Implementation status:** private AWS staging persistence deployed and verified on 2026-08-06

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

## Deployment evidence and boundary

[`glap_governed_closed_loop.py`](../lambda/glap_governed_closed_loop.py) remains
a pure, deterministic domain layer. The existing private lifecycle adapter now
persists its state to four isolated Iceberg staging tables using
scenario-aware, retry-safe keys.

The `2026-08-06` actual-calendar staging run produced 15 Alert rows and 15
proposed Action rows. A repeat run produced zero new Actions. Athena
reconciliation found 15/15 distinct Alert keys, 15/15 distinct Action keys,
zero future-simulation rows, and no Outcomes or policy proposals before their
human-completion and observation gates. All six new closed-loop quality checks
passed.

The full 26-check lifecycle gate retained one pre-existing failure:
`missing_provider_coverage`. The actual-calendar baseline for this date contains
only Maersk Ocean; future DHL/KN simulation rows were not used to manufacture
operational coverage.

This deployment does not enable a recurring schedule, create a production
alias, expose entity records publicly, complete an Action automatically, or
activate a policy.
