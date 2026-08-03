# GLAP Project TODO

## Next session

- [ ] Move the complete daily business flow out of **System** and into the **OPS Dashboard**:
  `Shipment → Signal → Root Cause → Decision → Human Review → Action → Outcome → Learning`.
- [x] Add a compact **Today's operational flow** summary to the **Control Tower**, including generated shipments, at-risk shipments, pending decisions, executed actions, outcomes, and pipeline health.
- [ ] Keep **System** focused on technical evidence only: AWS resources, Data Catalog, Lambda logic, SQL, monitoring, release controls, and lineage.
- [x] Connect the OPS presentation to a versioned daily snapshot contract with an optional scheduled Athena export and explicit non-live fallback.
- [x] Configure the repository's `AWS_OPS_READ_ROLE_ARN` and Athena variables to activate the scheduled AWS export.
- [x] Switch public pipeline health from stale legacy v1 tables to the current
  `alerts_v3 → insights_v3 → decisions_v3 → actions_v2 → outcomes_v2 → learning_v1` flywheel.
- [x] Add current-stage freshness, public-safe operational KPIs, and a transparent
  seven-day shipment-volume baseline to the OPS snapshot and Analytics page.
- [ ] Add per-stage duration, failure status, and drill-down links beyond the implemented snapshot-level freshness and record counts.
- [x] Confirm the current v2 daily path schedules generation at 00:05 and
  orchestration at 00:30 Australia/Sydney before the public analytics refresh.
- [ ] Retire or reschedule the separate legacy 08:00 generator/flywheel pair;
  it is not used by the current public v3/v2 health contract.
- [x] Retire the stale legacy v1 anomaly/root-cause/decision feed from current
  public health claims; retain it only as historical implementation evidence.

## Current checkpoint — 23 July 2026

- Local customer-facing HTML demo is available in `offline/glap-demo.html`.
- System content has been split into focused subpages.
- Daily AWS output, KPI funnel, schedules, health checks, and freshness exception are represented.
- Control Tower now summarises today's shipment-to-outcome flow and updates decision, action, and pending-outcome counts during the demo.
- No AWS deployment or configuration change was made during the latest UI work.
