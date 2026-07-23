# GLAP Project TODO

## Next session

- [ ] Move the complete daily business flow out of **System** and into the **OPS Dashboard**:
  `Shipment → Signal → Root Cause → Decision → Human Review → Action → Outcome → Learning`.
- [ ] Add a compact **Today's operational flow** summary to the **Control Tower**, including generated shipments, at-risk shipments, pending decisions, executed actions, outcomes, and pipeline health.
- [ ] Keep **System** focused on technical evidence only: AWS resources, Data Catalog, Lambda logic, SQL, monitoring, release controls, and lineage.
- [ ] Connect the OPS flow to automatically refreshed daily data rather than a dated HTML snapshot.
- [ ] Add per-stage freshness, record counts, duration, failure status, and drill-down links.
- [ ] Fix orchestration order so the flywheel starts only after shipment generation and validation succeed.
- [ ] Decide whether the stale legacy v1 anomaly feed should be repaired or formally retired.

## Current checkpoint — 23 July 2026

- Local customer-facing HTML demo is available in `offline/glap-demo.html`.
- System content has been split into focused subpages.
- Daily AWS output, KPI funnel, schedules, health checks, and freshness exception are represented.
- No AWS deployment or configuration change was made during the latest UI work.
