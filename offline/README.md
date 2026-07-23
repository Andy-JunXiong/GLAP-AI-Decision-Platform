# GLAP offline product demo

GLAP is a logistics decision-intelligence concept that turns emerging operational signals into explainable, human-reviewed actions and measurable outcomes.

This single-file demo presents the customer journey:

1. **Detect** port, schedule, inventory, and freight-market risks.
2. **Decide** by comparing constrained options and their economics.
3. **Operate** by connecting an approved decision to affected shipments.
4. **Learn** by comparing expected benefit with observed outcomes.

Open `glap-demo.html` directly in a modern browser. No installation, internet connection, server, AWS account, or build step is required.

## What is implemented

Navigation, filtering, scenario economics, approval invalidation, approve/reject/override reason capture, cross-page state changes, an in-memory decision ledger, expected-versus-observed outcome presentation, and a detailed AWS System evidence view all run locally in the browser.

The System view is split into six focused subpages: Daily E2E Flow, AWS Overview, Data Catalog, Logic & SQL, OPS Dashboard, and Release & Lineage. Together they translate the deployed platform into:

- core Iceberg data contracts and their business meaning;
- the complete daily journey from synthetic shipment generation through detection, decision, human review, action, outcome, and controlled learning;
- deployed Lambda decision rules and idempotency behavior;
- production Athena SQL patterns and the OPS questions they answer;
- a daily operations, monitoring, failure-recovery, deployment, and rollback runbook;
- a dated daily KPI funnel from alerts through outcomes, plus scheduler, alarm, Athena, and DLQ health;
- an explicit freshness exception showing that the current v3 chain is active while the legacy v1 anomaly feed is stale;
- explicit mappings from each product page to its AWS source tables.

## What is simulated

All operational records and values are synthetic. State is not persisted after the browser tab closes. Approval controls do not send instructions to carriers, terminals, or transport systems. The economic model is deliberately simplified and discloses its assumptions in the Decision Brief.

## Relationship to the full GLAP project

This file is the offline presentation layer, not the complete data platform. The full project documents an AWS reference architecture using S3, Glue, governed Iceberg tables, Athena models, Lambda/EventBridge automation, and decision-support outputs.

The System page reflects a read-only AWS inspection performed on 23 July 2026. It separates deployed resources, validated execution, retained dashboard artifacts, synthetic records, and designed product behavior. Account identifiers, ARNs, bucket names, and notification subscribers are not embedded in the demo.

## Known limitations

- One decision path has a detailed interactive brief.
- Live data sources and operational integrations are not connected.
- The ledger is session-local and not written to durable storage.
- Non-demo actions display a clear scope message instead of silently doing nothing.
