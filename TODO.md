# GLAP Project TODO

Implementation details, dependencies, and acceptance criteria are maintained in
[`docs/implementation_roadmap.md`](docs/implementation_roadmap.md).

## Current checkpoint — 3 August 2026

- [x] Publish a versioned AWS OPS snapshot through GitHub OIDC with an explicit
  non-live fallback.
- [x] Read the current
  `alerts_v3 → insights_v3 → decisions_v3 → actions_v2 → outcomes_v2 → learning_v1`
  flywheel instead of the stale legacy v1 feed.
- [x] Publish per-stage dates, aggregate operational KPIs, 28-day history, and a
  transparent seven-day volume baseline.
- [x] Add the live Analytics page and deploy it to GitHub Pages.
- [x] Confirm the current daily path schedules generation at 00:05 and v2
  orchestration at 00:30 `Australia/Sydney` before the public refresh.
- [x] Keep public output aggregate-only and exclude operational identifiers.

## P0 — Pipeline reliability and truthful health

- [ ] Replace time-only sequencing with success-gated orchestration from data
  generation and validation through the current v3/v2 flywheel.
- [ ] Add data-quality gates for missing dates, empty inputs, duplicate business
  keys, abnormal volume changes, and stale stage outputs.
- [ ] Publish per-stage start time, duration, completion state, and safe failure
  category in the OPS health contract.
- [ ] Add runbook links and failed-stage drill-down from Analytics and the OPS
  Dashboard without exposing private AWS identifiers.
- [ ] Verify CloudWatch alarms, retries, and DLQ coverage for every function in
  the current v3/v2 path.
- [ ] Retire or reschedule the separate legacy 08:00 generator/flywheel pair.
- [ ] Ensure downstream processing and Pages refresh cannot claim `current` after
  any upstream validation or stage failure.

## P1 — Authenticated operator write-back loop

- [ ] Define versioned request/response contracts for decision review, action
  updates, outcome reconciliation, and audit events.
- [ ] Add an authenticated internal Operations API using API Gateway and Lambda.
- [ ] Add Cognito or IAM-based identities and role-based authorization for
  viewer, operator, approver, and administrator responsibilities.
- [ ] Read the real internal decision queue with pagination and safe filters.
- [ ] Record approve, edit, and reject events with actor, timestamp, reason, and
  immutable source-decision version.
- [ ] Create and update owned Actions with due date and controlled status values.
- [ ] Record observed Outcomes separately from expected impact.
- [ ] Add an append-only audit contract and idempotency keys for all writes.
- [ ] Keep the public Pages deployment read-only and aggregate-only.

## P2 — Governed operational SQL marts

- [ ] Build `mart_ops_daily` for network volume, risk, and flow conversion.
- [ ] Build `mart_route_performance_daily` for route-level SLA and delay trends.
- [ ] Build `mart_carrier_performance_daily` for carrier reliability analysis.
- [ ] Build `mart_decision_effectiveness` for acceptance, execution, outcome, and
  time-to-value metrics.
- [ ] Build `mart_forecast_accuracy` for prediction-versus-actual evaluation.
- [ ] Build `mart_pipeline_health` for stage duration, freshness, and failures.
- [ ] Add schema tests, uniqueness checks, freshness checks, and documented metric
  definitions for every mart.
- [ ] Add Athena cost controls and incremental refresh rules.

## P3 — Forecast validation and model upgrade

- [ ] Retain the 28-day OLS forecast as the required benchmark model.
- [ ] Add moving-average, weekday-seasonal, and recent-level baselines.
- [ ] Add rolling time-based backtests with MAE, RMSE, MAPE, bias, and interval
  coverage where the metric is defined.
- [ ] Add route/carrier forecasts only to the authenticated internal analytics
  boundary.
- [ ] Add SLA-breach or delay-risk probability modelling after enough labelled
  history is available.
- [ ] Compare any XGBoost/LightGBM candidate against simple baselines before
  promotion.
- [ ] Record model version, feature contract, training window, generated time,
  and prediction interval with every forecast.
- [ ] Add drift, data-completeness, and prediction-error monitoring.

## P4 — Internal operations cockpit and product cleanup

- [ ] Move the complete daily business flow into the OPS experience:
  `Shipment → Signal → Root Cause → Decision → Human Review → Action → Outcome → Learning`.
- [ ] Keep **System** focused on AWS resources, Data Catalog, Lambda logic, SQL,
  monitoring, release controls, and lineage.
- [ ] Add authenticated Risk Hotspots, Decision Queue, Action Board, Outcome
  Review, Forecast Accuracy, and Pipeline Health views.
- [ ] Add route/carrier/entity drill-down only for authorised internal users.
- [ ] Distinguish synthetic scenario cards, live aggregate analytics, and measured
  operational outcomes everywhere in the UI.
- [ ] Add accessible loading, empty, stale, partial, and failed states.

## P5 — Governance and production readiness

- [ ] Define data classification, redaction, retention, and deletion policies.
- [ ] Apply least-privilege IAM and Lake Formation permissions to internal read
  and write paths.
- [ ] Configure Athena workgroup budgets and query-cost monitoring.
- [ ] Configure Iceberg compaction, snapshot expiration, and orphan-file cleanup.
- [ ] Add API audit logging, lineage, operational SLOs, and cost dashboards.
- [ ] Add backup, recovery, incident response, and operator runbooks.
- [ ] Add load, concurrency, security, and failure-injection tests.
- [ ] Preserve explicit labels for synthetic, validation, forecast, and measured
  production evidence.

## Delivery order

`P0 reliability → P1 write-back → P2 marts → P4 cockpit → P3 model upgrade → P5 production readiness`
