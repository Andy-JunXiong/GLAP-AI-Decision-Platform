# Stateful Shipment Lifecycle Design

**Status:** lifecycle and multimodal analytics foundation implemented and
validated in isolated AWS staging; production boundary not enabled

**Decision date:** 4 August 2026

**Scope:** synthetic AWS operations pipeline and its aggregate public evidence

## Implementation checkpoint -- 5 August 2026

The repository and isolated AWS staging now implement the lifecycle foundation
described here. A 28-day AWS replay proved cross-date identity, immutable P2P
commitments, milestone progression, final closure, and journey-level exception
incidence. The staging contract was then extended to Maersk/KN Ocean and DHL
Air, followed by six read-only operational analytics, feature, and label views.

The future-dated synthetic `2026-09-07` manual controller scenario passed
generation, 19 lifecycle checks, 5 v2 compatibility checks, and 8 multimodal
analytics checks. This validates staging mechanics, not real September history.
The environment
still has no lifecycle schedule, production alias change, or write into the
current v2 production boundary. Exception-to-action state, delayed outcomes,
human-approved policy feedback, and trained forecasts remain later phases.

## Recovery correction -- 17 August 2026

A failed actual-calendar continuation exposed that the provider-coverage check
was comparing every date with the later three-provider roadmap, even when only
the Maersk route configuration was effective on that date. The repository now
defines `missing_provider_coverage` against the active route and provider
configuration effective on the requested logical date. Once KN and DHL routes
become effective, the same fail-closed check requires them as well.

This correction does not relabel future simulations, manufacture historical
KN/DHL rows, or clear provider/model readiness. The AWS quality-gate update,
controlled recovery of the failed `2026-08-09` status, later actual-calendar
continuation, operational-baseline refresh, and public publication were
defined as separate runtime steps requiring human authority. The recovery and
baseline refresh were later separately authorized and completed; aggregate-only
public publication was subsequently authorized and completed as its own step.

## Cross-gap prior-state correction -- 23 August 2026

The first separately authorized recovery attempt for `2026-08-09` passed the
28-check lifecycle gate but failed closed at compatibility input validation.
The current snapshot contained 17 shipments, while an exact `2026-08-08`
lookup found zero; all six required tables were populated and current, and no
duplicate business keys were present. The failure was therefore
`abnormal_volume_change`, not missing tables or duplicate data.

The repository correction keeps the volume threshold and missing-baseline
failure intact. For lifecycle continuation only, the generator, prior-alert
reconciliation, immutable-state validation, and compatibility volume gate now
use the latest earlier populated snapshot in the same `temporal_scope_id`.
Consecutive dates still resolve to the immediately preceding day. A governed
calendar gap resolves to the most recent earlier state in that scope; if no
earlier state exists, the compatibility gate still fails closed.

The correction was later released through protected isolated-staging plan and
deployment runs. A separately authorized retry for only `2026-08-09` completed
all four stages and 41 checks: 28 lifecycle, 5 compatibility, and 8 analytics.
The controller persisted terminal success. A later separately authorized
baseline run created or replaced one aggregate view at cutoff `2026-08-09`
and passed 10/10 fail-closed checks. Both runtime results remain synthetic
engineering evidence; they do not fabricate a missing calendar date, alter an
evidence classification, or authorize production, schedules, aliases, Pages,
or another recovery attempt.

A later aggregate-only Pages run `32673379142` succeeded from commit `fed2462`
and exposed the point-in-time distinction clearly: the published baseline
cutoff remained `2026-08-09`, while its latest eligible source metric date was
`2026-08-06`. This was not a cache failure. The recovery rows were created with
the system-derived `2026-08-24` availability date and therefore could not be
retroactively included in a 9 August baseline. The repository correction now
requires source coverage to equal the requested cutoff and renders both dates;
that correction is locally verified and awaits publication and runtime
verification.

The source continuation and baseline replacement were later separately
authorized. Run `32674455765` extended 10–21 August; run `32676988757`
extended 22–24 August and passed four stages plus 41 checks per date. Redundant
run `32728891520` failed closed before processing because its older start date
could not overwrite the newer 24 August status. Baseline run `32729202007`
then replaced one aggregate view at cutoff `2026-08-24` and passed the deployed
10-check contract. The repository equality check has not yet been exercised by
a connected export or Pages publication.

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

### Origin, port-to-port and destination timestamps

The port-to-port contract has exactly four key milestones. ETD and ETA are the
single immutable schedule commitments; there are no `original_*` and
`current_*` variants. ATD and ATA remain `NULL` until observed and are then
immutable, except through an explicit correction event.

| Meaning | Field | Update rule |
| --- | --- | --- |
| Planned port departure | `etd` | immutable after booking |
| Actual departure | `atd` | `NULL` until departure, then immutable |
| Planned port arrival | `eta` | immutable after booking |
| Actual port arrival | `ata` | `NULL` until arrival, then immutable |
| Origin gate-in target | `gate_in_target_at` | booking plus seven days |
| Actual origin gate-in | `gate_in_at` | set once when observed |
| Discharge target | `discharge_target_at` | ATA plus three days |
| Actual discharge | `discharged_at` | set once when observed |
| Delivery target | `delivery_target_at` | discharge plus four days |
| Actual delivery | `delivered_at` | set once when observed |

Origin and destination targets remain separate from the P2P metric. ATA is not
discharge, customs clearance, pickup or final delivery.

### Shanghai to Sydney ocean baseline

The route-service master now carries a versioned baseline instead of one global
16-day value. Shanghai--Sydney starts at 14 days for Qilin premium and 17 days
for Dragon standard. Other configured Asia--Australia routes use their own
published schedule or explicitly labelled calibrated assumption.

- [Maersk's 2026 Qilin launch](https://www.maersk.com/news/articles/2026/05/22/maersk-qilin-service-china-australia-launch)
  lists Shanghai to Sydney at 14 days on Qilin and 18 days on Dragon.
- [ONE's May 2026 Shanghai export schedule](https://ch.one-line.com/sites/china/files/schedules/2026-05/Sha-May-Schedule-2026.pdf)
  lists direct services at 14 and 16 days.

These are simulation baselines, not service commitments. The lifecycle target
is seven days from booking to gate-in, one terminal-buffer day from gate-in to
ETD, three days from ATA to discharge, and four days from discharge to final
delivery.

Example for a shipment created on 4 August:

```text
booking date:                4 Aug
gate-in target:             11 Aug
ETD:                        12 Aug
ETA:                        26 Aug (Qilin)
discharge target:           29 Aug after ATA
delivery target:             2 Sep after discharge
```

A rollover makes ATD later than ETD. It never rewrites ETD or ETA. Downstream
delay is expressed by ATA against the same immutable ETA.

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

The lifecycle is mode-neutral at its three governed boundaries:

| Boundary | Ocean events | Air events |
| --- | --- | --- |
| Origin | gate-in and terminal acceptance | pickup/origin receipt and airport acceptance |
| P2P | vessel departure and arrival | flight departure and arrival |
| Destination | discharge/release and delivery | cargo availability/release and delivery |

`etd`, `atd`, `eta`, and `ata` remain the common immutable/observed P2P
contract. Mode-specific events are appended to the event history and must not
be forced into Ocean-only fields.

For each governed logical run date, the generator will:

1. read all shipments not in `DELIVERED` or `CANCELLED`;
2. create a controlled number of new shipments;
3. advance eligible existing shipments and append new milestone events;
4. preserve ETD and ETA and set ATD/ATA only when those P2P milestones occur;
5. set gate-in, discharge and delivery actuals only when observed;
6. recalculate current risk, SLA metrics and accumulated cost;
7. write the current-date snapshot for active shipments and final snapshots for
   shipments delivered that day;
8. retain completed history but exclude delivered shipments from future active
   updates.

On the delivery date the final snapshot records `lifecycle_stage=DELIVERED`,
`lifecycle_status=CLOSED` and `terminal_state=true`, together with the immutable
DELIVERED event. Later logical dates read only `OPEN` non-terminal shipments, so
the delivered shipment is retained in history but never updated again.

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

The first multimodal simulation uses a deterministic 17-booking cycle: 7
Maersk Ocean, 7 KN Ocean, and 3 DHL Air. This yields 41.18%, 41.18%, and 17.65%
respectively, keeping Air inside the approved 15--20% range over a governed
rolling cohort. The percentages are simulation controls, not market-share
claims.

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
-> ATD occurs after ETD
-> ATA may occur after ETA
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

Rate Cards are selected and locked by `booking_at`, not by ETD, ATD, ETA, ATA
or invoice date. A shipment booked in Q1 retains its Q1 version and price even
when ETD falls in Q2. Active Rate Card versions are immutable; quarterly market
calibration creates a new version for new Bookings only.

## Future external intelligence and LLM boundary

A later capability will proactively monitor authorised external information for
conditions that may affect active operations, including severe weather, origin
container or equipment shortages, geopolitical disruption, destination-port
congestion, labour action and strikes. External feeds provide the evidence; an
LLM may extract events, normalize locations/time windows, classify disruption
type and draft an explanation. It must not invent evidence or directly mutate a
Shipment, milestone, Rate Card, Alert status or Decision policy.

The governed flow is:

```text
weather / port / carrier / government / news evidence
-> source capture with publication time and URL
-> LLM extraction into a versioned event schema
-> deterministic validation, deduplication and port/route matching
-> exposure calculation against active OPEN shipments
-> external-risk insight or early warning
-> human-reviewed action where required
```

Every extracted event requires source provenance, observed and effective time,
affected geography/entity, confidence, expiry, evidence excerpt/hash and model
version. Low-confidence or conflicting evidence remains advisory and cannot
trigger an autonomous operational action.

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
- progress Origin, immutable P2P and Destination milestones;
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
2. the single ETD and ETA remain unchanged for the full shipment lifecycle;
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

- whether the six proven read-only v2 compatibility views should remain virtual
  or be materialized after measured Athena cost and reconciliation tests;
- whether alert lifecycle fields fit the current v3 schema or require compatible
  schema evolution;
- how much governed feature and outcome-label history is required before the
  first route/carrier forecast can be evaluated beyond the benchmark.
