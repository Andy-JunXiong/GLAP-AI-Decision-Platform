# Stateful Shipment Lifecycle Design

**Status:** approved design direction; not yet implemented

**Decision date:** 4 August 2026

**Scope:** synthetic AWS operations pipeline and its aggregate public evidence

## Decision summary

GLAP will evolve from generating an independent batch of roughly 400--500
shipments each day into a stateful synthetic operation. The same `shipment_id`
will remain active across logical run dates, progress through milestones, and
stop receiving active updates after delivery.

The existing success-gated AWS pipeline, six v2 input domains, and six governed
AI outputs remain the foundation. This change is about business state and causal
time, not adding more disconnected analytics tables or moving computation into
GitHub Actions.

```text
new and carried-over shipments
-> milestone and estimate updates
-> risk, SLA and cost exceptions
-> insight, decision and governed action
-> delayed simulated outcome
-> learning and human-reviewed policy proposal
```

All operational calculations remain in AWS Lambda, Athena and Iceberg. The
public GitHub Pages workflow may publish only a sanitized aggregate snapshot.

## Why the current data appears static

The deployed generator currently creates a largely independent daily population.
Only `A303_HIGH_RISK_ROUTE` is active in the inspected alert path, downstream
decisions therefore converge on `RISK_MITIGATION`, and the current outcome
template uses fixed values. The technical chain completes, but a shipment,
alert, action and outcome do not yet form one multi-day business story.

The public analytics path also has a known source mismatch: public shipment
volume currently comes from `fact_shipment_events_extended_iceberg`, while the
governed AI quality gates use `simulated_iceberg_m.fact_shipment_v2`. The target
public metric contract will use the v2 canonical path.

## Shipment time model

### Planned, estimated and actual timestamps

Initial commitments must never be overwritten. Current estimates may change as
new information arrives. Actual timestamps remain `NULL` until the milestone is
observed and are immutable afterwards, except through an explicit correction
event.

| Meaning | Field | Update rule |
| --- | --- | --- |
| Initial planned departure | `original_etd` | immutable |
| Latest estimated departure | `current_etd` | may be revised before departure |
| Actual departure | `atd` | `NULL` until departure, then immutable |
| Initial planned port arrival | `original_eta` | immutable |
| Latest estimated port arrival | `current_eta` | may be revised until arrival |
| Actual port arrival | `ata` | `NULL` until arrival, then immutable |
| Latest estimated customer delivery | `estimated_delivery_at` | may change through customs and last mile |
| Actual customer delivery | `actual_delivery_at` | set once when delivered |

This separation supports auditable measures such as departure schedule slip,
actual departure delay, arrival schedule slip and final delivery delay. It also
prevents a revised estimate from erasing the original commitment.

### Shanghai to Sydney ocean baseline

For the synthetic ocean route, GLAP will initially use a 16-day port-to-port
baseline, a normal range of 14--18 days, and a disrupted range of approximately
19--25 days. This is consistent with current published carrier schedules:

- [Maersk's 2026 Qilin launch](https://www.maersk.com/news/articles/2026/05/22/maersk-qilin-service-china-australia-launch)
  lists Shanghai to Sydney at 14 days on Qilin and 18 days on Dragon.
- [ONE's May 2026 Shanghai export schedule](https://ch.one-line.com/sites/china/files/schedules/2026-05/Sha-May-Schedule-2026.pdf)
  lists direct services at 14 and 16 days.

These are simulation baselines, not service commitments. `current_eta` means
estimated port arrival; final delivery should add a separate synthetic customs,
terminal and last-mile duration, initially 2--5 days.

New shipments will normally enter the system about one week before planned
departure. The first implementation should sample booking-to-ETD lead time from
a documented range, initially 5--10 days, instead of assigning exactly seven
days to every shipment.

Example for a shipment created on 4 August:

```text
booking date:                4 Aug
original/current ETD:       11 Aug
original/current ETA:       27 Aug
estimated final delivery:   30 Aug
```

If a rollover is learned on 9 August, `current_etd` and `current_eta` move while
the original fields remain unchanged. `atd` stays `NULL` until the vessel really
departs in the simulation.

## Lifecycle and daily processing

The minimum lifecycle is:

```text
PLANNED
-> BOOKED
-> ORIGIN_PROCESSING
-> DEPARTED
-> IN_TRANSIT
-> ARRIVED_PORT
-> CUSTOMS_CLEARANCE
-> OUT_FOR_DELIVERY
-> DELIVERED
```

For each governed logical run date, the generator will:

1. read all shipments not in `DELIVERED` or `CANCELLED`;
2. create a controlled number of new shipments;
3. advance eligible existing shipments and append new milestone events;
4. revise current ETD, ETA and estimated delivery only when conditions require;
5. set ATD, ATA and actual delivery when those milestones occur;
6. recalculate current risk, SLA metrics and accumulated cost;
7. write the current-date snapshot for active shipments and final snapshots for
   shipments delivered that day;
8. retain completed history but exclude delivered shipments from future active
   updates.

Volume, weight, product allocation and other shipment identity attributes are
stable after booking in the first simulation version. A later version may model
explicit pre-departure corrections, but it must not silently mutate them.

## Reusing the current v2 contract

The current input quality key for shipments is `(shipment_id, dt)`. That grain
already permits the same shipment to appear on multiple dates as a daily
snapshot. The first lifecycle implementation will therefore reuse the current
six input domains:

| Current asset | Lifecycle use |
| --- | --- |
| `fact_shipment_v2` | active shipment snapshot by `shipment_id, dt` |
| `fact_shipment_event_v2` | newly observed milestone events |
| `fact_shipment_leg_metrics_core_v2` | current leg duration and SLA state |
| `fact_shipment_cost_v2` | current or accumulated cost state |
| `fact_shipment_risk_v2` | current delay, damage, compliance and overall risk |
| `shipment_product_allocation_v2` | stable allocation copied at the governed snapshot grain where required |

A daily shipment-state view can be derived from the shipment and event history.
`fact_shipment_state_daily_v1` will be materialized only if documented grain,
as-of history, reconciliation or performance evidence proves that a view over
the current assets is insufficient.

## Population model

With an average booking-to-delivery lifecycle of roughly 25--30 days, maintaining
about 400--500 active shipments requires approximately 14--18 new shipments per
normal day. Demand regimes may vary that rate, but should remain versioned and
reproducible.

The first stateful run must seed the active population across lifecycle stages;
it must not create only newly booked shipments and wait several weeks for the
system to become representative. A starting population can be distributed
across planned, origin, in-transit, destination and last-mile stages, with
historically consistent milestone dates.

## Delay and disruption model

The initial target of 3--7% means the share of shipments encountering at least
one material delay across their journey. It must not be applied as an independent
3--7% daily probability: repeated daily sampling would make the cumulative
journey exception rate much larger than intended.

The first implementation may assign a reproducible journey-level exception
cohort. A later version can add versioned multi-day disruption episodes for
port congestion, carrier rollover, weather, customs holds, capacity shortages
and documentation errors.

An exception must propagate through milestones rather than directly changing a
dashboard result:

```text
carrier rollover
-> current ETD slips
-> current ETA slips
-> SLA and risk metrics worsen
-> alert is created or escalated
-> action is proposed
-> later shipment state provides outcome evidence
```

SLA breach and cost anomaly are the first additional alert types to add alongside
the existing high-risk-route alert. Every alert type requires an explicit grain,
stable fingerprint, lifecycle state, and affected-entity definition.

## Outcome, learning and governance boundary

Outcome variability must be causal rather than cosmetic. An outcome will be
created only after the action's observation lag and will depend on action type,
root cause, shipment stage, severity, carrier context, execution delay and any
active disruption. A deterministic seed based on stable entity and version
identifiers keeps the synthetic stochastic component reproducible.

Public outcomes must be labelled `SIMULATED` and distinguish pending, successful,
partially successful, failed and inconclusive states.

Simulation configuration and decision policy are separate controls:

```text
simulation configuration
  -> controls the synthetic world and disruption assumptions

decision policy
  -> controls thresholds, action ranking and approval requirements
```

Learning must not automatically modify the synthetic world. The governed loop is:

```text
delayed outcome
-> learning evidence
-> decision-policy change proposal
-> human review
-> approved version
-> effective date and rollback path
```

This avoids a self-confirming loop in which simulated outcomes change the same
generator assumptions that are then used to claim improvement.

## Delivery sequence

### P0 -- Restore metric correctness and observability

- use the governed v2 shipment source for public metrics;
- source root-cause distributions from `fact_ai_insights_v3`;
- source action distributions from `fact_ai_actions_v2`;
- remove legacy v1 and trace assets from the public governed contract;
- render an improvement ratio of `0.375` as `37.5%` and label it synthetic;
- publish existing six-stage controller and quality-gate status safely;
- define stable metric and public evidence-sanitization contracts;
- retain canonical daily aggregates for later trend validation.

### P1 -- Implement the stateful generator

- seed a representative active population;
- add a controlled daily new-shipment rate;
- carry active shipment IDs across dates;
- progress milestones and preserve original versus current estimates;
- stop active updates after delivery;
- update quality-gate semantics and thresholds where the meaning changes from
  daily generated population to active shipment snapshots.

### P2 -- Add exception lifecycle

- retain `HIGH_RISK_ROUTE`;
- add `SLA_BREACH` and `COST_ANOMALY` from existing v2 inputs;
- add stable alert grain, fingerprint, first/last detection and open/resolved
  behavior;
- add controlled journey-level delay cohorts and then multi-day episodes.

### P3 -- Add delayed action and outcome state

- progress actions through proposed, approved, completed and overdue states;
- observe context-conditioned outcomes only after the defined lag;
- preserve simulated provenance and deterministic replay;
- aggregate learning by sufficient context to compare policy performance.

### P4 -- Close the human-gated policy loop and expand presentation

- propose, review, version, activate and roll back decision-policy changes;
- keep simulation calibration independent;
- publish validated 28-day lifecycle, alert and outcome trends;
- add exception queue, Shipment 360 and sanitized evidence drill-down;
- add predictive models only after persistent labelled history exists.

## Acceptance criteria

The stateful lifecycle is complete only when:

1. the same `shipment_id` is present on multiple logical dates and progresses
   through valid milestone transitions;
2. original ETD and ETA remain unchanged while current estimates retain their
   revision history;
3. ATD, ATA and actual delivery are set only when observed and then remain stable;
4. delivered shipments stop receiving active updates without losing history;
5. journey-level exception incidence is measured against the documented 3--7%
   target rather than a daily probability;
6. distinct SLA, cost and risk conditions generate distinct governed alerts and
   downstream actions;
7. outcomes are delayed, reproducible, context-dependent and not uniformly
   successful;
8. learning changes decision policy only through a human-approved version;
9. public metrics reconcile to the governed v2/v3 quality-gate contract; and
10. GitHub Actions performs no business calculation and publishes only the
    sanitized AWS aggregate.

## Open implementation questions

- the exact mapping from the current deployed columns to original and current
  milestone fields, including whether compatible Iceberg column additions are
  required;
- route-specific baselines for modes and lanes beyond Shanghai--Sydney ocean;
- the initial active-population stage distribution and daily new-shipment rate;
- whether alert lifecycle fields fit the current v3 schema or require compatible
  schema evolution;
- whether the derived daily-state view requires materialization after measured
  Athena cost and reconciliation tests.
