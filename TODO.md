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

Repository checkpoint — 4 August 2026:

- [x] Add a configurable success-gated controller that stops after the first
  failed stage or data-quality gate and preserves blocked downstream stages.
- [x] Define the five required quality-check result names and fail closed on an
  incomplete validation response.
- [x] Implement input/output Athena gates against the verified v2 and v3/v2
  schemas; both aggregate queries passed against the 4 August logical run.
- [x] Persist only sanitized stage timing and failure state, and make controller
  failure trigger the existing Scheduler retry/DLQ path.
- [x] Add optional OPS snapshot verification that prevents `current` when a
  required pipeline-run status is missing, stale, incomplete, or failed.
- [x] Add a least-privilege CloudFormation template with a private status object,
  encrypted DLQ, alarms, and a replacement schedule that defaults to disabled.
- [x] Deploy an isolated staging stack with zero-write stage stubs; verify one
  controlled quality failure blocks all downstream stages, then restore the
  threshold and pass all six stages and ten quality checks.
- [x] Replace staging stubs with governed current-function targets, back up the
  prior configurations privately, disable five time-only/legacy schedules, and
  enable the success-gated 00:05 schedule with rollback protection.
- [ ] Observe the first real success-gated run on 5 August, verify six stages and
  ten checks, then enable required OPS verification.

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
- [x] Retire the separate legacy 08:00 generator/flywheel scheduling pair; the
  flywheel function now runs only inside the success-gated chain.
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

## P2 — Governed operational analytics assets

- [x] Inventory current AWS result tables and reusable analytics views before
  proposing new marts.
- [x] Connect daily KPIs, OLS forecast, alert/action/root-cause distributions,
  and latest decision traces to existing AWS assets.
- [x] Anchor shipment analysis to the logical run date and `dt`, not future
  shipment `event_time`.
- [x] Keep calculations in Athena and GitHub Actions limited to orchestration and
  aggregate snapshot publication.
- [ ] Document grain, ownership, and freshness for each remaining internal-only
  analytics view.
- [ ] Materialise a new mart only when reconciliation or performance evidence
  proves the existing assets cannot meet the requirement.
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

`P0 reliability → P1 write-back → P2 existing-asset analytics → P4 cockpit → P3 model upgrade → P5 production readiness`
