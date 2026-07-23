# Case Study: Port Congestion, Strike Risk and FCL Diversion

## Executive decision

GLAP detects that congestion at the original destination port is materially
above baseline while an industrial-action signal increases the probability of a
multi-day disruption. Twelve FCL containers carry a critical SKU and available
inventory is unlikely to cover the expected delay.

The system recommends diverting eight high-priority containers to an alternate
port and moving them to the destination distribution centre by rail or truck.
Four lower-priority containers remain on the original route and are reviewed
daily.

This is a synthetic, business-realistic demonstration. It does not claim that
GLAP executed a real port diversion or produced measured savings.

## 1. Detection

| Signal | Current | Baseline or threshold | Interpretation |
| --- | ---: | ---: | --- |
| Sydney port congestion index | `0.87` | `0.35` | Material operational deviation |
| Labour-strike probability | `82%` | `60%` escalation threshold | Disruption likely to persist |
| Expected dwell time | `9 days` | `3 free days` | Six chargeable storage days |
| Inventory cover | `8 days` | `9-day expected dwell` | Stockout exposure |

Detection is not based on a single headline. GLAP combines an operational
anomaly with an external disruption signal and the inventory position.

## 2. Business exposure

The no-action storage estimate is:

```text
12 FCL × (9 expected dwell days − 3 free days) × AUD 220
= AUD 15,840
```

Storage fee alone understates the risk. The same delay could exhaust the current
inventory cover before the critical SKU reaches the Sydney distribution centre,
affecting customer availability and replenishment planning.

## 3. Recommended action

| Action | Scope | Rationale |
| --- | ---: | --- |
| Divert to Melbourne | 8 high-priority FCL | Protect critical inventory |
| Rail/truck to Sydney DC | 8 FCL | Bypass destination-port dwell |
| Remain on original route | 4 lower-priority FCL | Avoid unnecessary diversion cost |
| Review disruption | Daily | Reassess congestion and strike status |

The decision is marked `HIGH` priority and `human_review_required=true`. An
operator can approve, reject or adjust the number of diverted containers.

## 4. Synthetic outcome

Assume the disruption lasts four additional days and the diverted containers
reach the distribution centre before available inventory is exhausted.

| Outcome measure | Synthetic result |
| --- | ---: |
| Diverted FCL | `8` |
| Reroute cost | `AUD 4,800` |
| Storage exposure avoided on diverted FCL | `AUD 10,560` |
| Net modelled storage benefit | `AUD 5,760` |
| Critical-SKU stockout | `avoided` |
| Containers remaining at original port | `4` |

The outcome record should retain the original estimate, approved action, actual
disruption duration, realised fees and in-stock result. That makes later policy
tuning auditable.

## 5. Sample evidence chain

- Signal input: [`../samples/port_disruption_signal.csv`](../samples/port_disruption_signal.csv)
- Decision output: [`../samples/port_reroute_decision.csv`](../samples/port_reroute_decision.csv)
- Outcome output: [`../samples/port_reroute_outcome.csv`](../samples/port_reroute_outcome.csv)

## 6. What would make this production-ready

- ingest authoritative port congestion and industrial-action feeds
- connect SKU/container contents to inventory and demand planning
- model diversion capacity, sailing schedules and inland transport constraints
- add operator approval, ownership and action timestamps
- compare estimated exposure with realised storage, demurrage and stockout cost
- tune decision thresholds using reviewed outcomes rather than synthetic labels
