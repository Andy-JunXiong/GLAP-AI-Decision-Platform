# Governed exception-to-outcome contract

**Business-date boundary:** Australia/Sydney
**Implementation status:** private AWS staging persistence deployed and verified on 2026-08-06;
Action assignment application chain verified in staging; operator EDIT recorded,
response fix release and separate approver decision pending; read-only
Action–Outcome and Outcome–Learning review source merged to `main` but undeployed

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

The proposed Action row is immutable. A private, manual-only mutation function
appends every `EDIT`, `APPROVE`, `REJECT`, or `COMPLETE` event to an Iceberg audit table.
Valid transitions are fail closed, and stable request IDs make retries
idempotent. A view overlays the latest audit event to expose current Action
state without erasing its history.

The repository now also exposes that relationship as one authenticated,
read-only evidence chain: immutable proposal, chronological audit events,
current Action state, and the latest cutoff-eligible Outcome. The chain uses
only operational actual-calendar rows through the current Sydney date. It
labels pending Outcomes as not observed and all closed-loop effects as
synthetic; it creates no mutation, approval, real-performance, or production
claim. The endpoint and cockpit timeline are merged and source-verified but remain
undeployed pending a separately authorized staging release.

The repository extension uses `PROPOSED -> EDITED` to record a named owner and
due date without approving the Action. `EDITED` then requires a separate
approver to approve or reject it. Assignment is carried forward into later
audit events, while the source proposal remains unchanged. The additive staging
schema migration was applied by a named human on 2026-08-13 and passed all five
read-only checks with zero failures. The migration itself executed no Action
mutation. A later named-human canary recorded one `EDIT`; it remains at
`EDITED` pending a response-fix release, stable retry, and a separate approver
decision.

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

The authenticated Learning Review now exposes this gate as a read-only
contract. It de-duplicates closed Outcomes, applies the Sydney cutoff and the
`OPERATIONAL` / `ACTUAL_CALENDAR` eligibility rules, reports progress toward the
20-Outcome minimum, and attaches only the latest eligible stored proposal. It
cannot approve or activate that proposal, cannot replace deterministic safety
rules, and labels all summarized effects as synthetic rather than real
logistics performance. Passing this synthetic policy-review threshold is not
model readiness or production readiness. The implementation is merged and
source-verified but remains undeployed and runtime-unverified.

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
human-completion and observation gates. All six original closed-loop quality
checks passed.

The controlled Action-mutation verification appended exactly two events,
`APPROVE` then `COMPLETE`, for one operational-calendar engineering Action.
Replaying the approval returned the original event. The current-state view
reports `COMPLETED`, and the same-date generator continuation created one
`PENDING` Outcome whose observation is due on `2026-08-09`. It has no observed
date and is not actual outcome evidence as of `2026-08-06`.

On the Sydney business date `2026-08-09`, an authenticated `viewer` refreshed
private Outcome Review and verified that the dated record had matured without
rewriting its historical Action or execution evidence. The response contained
zero pending Outcomes and one observed `SUCCESSFUL` Outcome with
`observed_date=2026-08-09`, `time_basis=ACTUAL_CALENDAR`, and a 20.0% simulated
effect. This is one eligible synthetic staging record; it is not real logistics
performance, sufficient label maturity, model readiness, production readiness,
or authority to activate a policy.

The same-date broader readiness run kept the governed Action Outcome separate
from the multimodal shipment-label contract. Its operational, actual-calendar
cohort contained 67 pending Maersk shipment labels and zero observed shipment
labels, so every supervised target remained
`blocked_insufficient_observed_labels`. This is expected: an Action Outcome
records a delayed simulated intervention effect, while a shipment label becomes
observed only after delivery. The pending labels were excluded from training,
and no future-simulation scope contributed to the result.

The expanded 28-check lifecycle gate passed the duplicate-request and invalid
audit-transition checks, while retaining one pre-existing failure:
`missing_provider_coverage`. The actual-calendar baseline for this date contains
only Maersk Ocean; future DHL/KN simulation rows were not used to manufacture
operational coverage.

On 17 August, read-only diagnosis confirmed that the persisted `2026-08-09`
controller status still failed only that check. The repository recovery
correction now compares the booking cohort with providers whose active route
configuration is effective on the logical date, rather than requiring the later
three-provider roadmap on every earlier date. This does not rewrite the
historical failure, add provider rows, or establish provider/model readiness;
deployment and runtime recovery remain pending human actions.

This deployment does not enable a recurring schedule, create a production
alias, expose entity records publicly, complete an Action automatically, or
activate a policy.
