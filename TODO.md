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

## Design checkpoint — 4 August 2026

- [x] Record the diagnosis that the AWS execution chain is complete while the
  synthetic business state is still a largely independent daily population.
- [x] Define the target cross-day shipment milestone model, including a single
  immutable P2P ETD/ETA, observed ATD/ATA, separate Origin/Destination targets,
  final delivery and terminal delivered state.
- [x] Document versioned route-service P2P targets, including Shanghai--Sydney
  Qilin 14-day and Dragon 17-day baselines.
- [x] Define 3--7% as a journey-level exception incidence rather than an
  independent daily probability.
- [x] Separate simulation calibration from decision policy and require human
  approval before a learned policy version becomes effective.
- [x] Record the phased design and acceptance criteria in
  [`docs/shipment_lifecycle_design.md`](docs/shipment_lifecycle_design.md).

## Next product slice — Stateful shipment lifecycle

Repository implementation checkpoint — 4 August 2026:

- [x] Add isolated Iceberg contracts for lifecycle targets, route services,
  synthetic rate cards, charge tiers, FX and staging shipment/event/cost data.
- [x] Implement deterministic seed population, 14–18 daily arrivals, immutable
  P2P ETD/ETA, observed ATD/ATA and separate Origin/Destination milestones.
- [x] Implement expected-cost selection, percentage surcharges, FX conversion
  and tiered time-based charges.
- [x] Lock the applicable quarterly Rate Card by `booking_at`, including the
  cross-quarter case where a Q1 Booking has a Q2 ETD.
- [x] Add fail-closed validation SQL and a plan-only AWS schema deployment command.
- [x] Add the governed, retry-safe Athena persistence adapter for isolated staging.
- [x] Add per-snapshot Origin/P2P/Destination lifecycle metrics and stable,
  simulated `SLA_BREACH` / `COST_ANOMALY` candidate contracts.
- [x] Validate a deterministic 28-day multi-date replay locally, including ID
  carryover, terminal closure and 3--7% journey exception incidence.
- [x] Add a manual GitHub OIDC staging workflow for plan, isolated stack deploy,
  replay and fail-closed daily reconciliation; it creates no schedule and does
  not modify a production alias.
- [x] Run the private 28-day replay in AWS staging and reconcile every logical
  date before changing the production alias.
  - 5 August evidence: workflow run `30967670110` replayed `2026-08-04` through
    `2026-08-31` from an initial population of 450 and passed 16 fail-closed
    checks for every date (448 checks total). The aggregate staging audit found
    28 dates, 16,037 snapshots, 895 shipment IDs, 4.58% journey exception
    incidence, 309 delivered shipments, zero post-delivery rows, zero invalid
    terminal rows, and zero duplicate snapshot keys. No schedule or production
    alias was created or changed.
- [x] Add six read-only v2 compatibility views and prove the isolated manual
  controller chain for `2026-09-01`: lifecycle generation, all 16 lifecycle
  checks, then all 5 existing-input contract checks. Workflow run `30972254011`
  passed without a schedule, Lambda alias, event-source mapping, EventBridge
  rule, or write to the current v2 tables.
- [x] Extend the isolated contracts for Maersk and KN Ocean plus DHL Air,
  preserving common Origin/P2P/Destination semantics and adding Air airport
  milestones, pieces/chargeable weight, per-kg cost, provider metadata, and
  mode-aware compatibility views. The deterministic 28-day local replay
  produced 449 new bookings with 17.37% Air.
- [x] Prove the multimodal schema evolution and `2026-09-02` through
  `2026-09-06` controller runs in AWS staging before enabling any recurring
  execution. The five-day booking cohort contained 35 Maersk Ocean, 33 KN
  Ocean, and 15 DHL Air shipments; Air was 18.07%. The first three DHL Air
  shipments completed Origin receipt, P2P flight departure/arrival,
  Destination cargo availability, and final delivery. All 19 lifecycle and 5
  compatibility checks passed on every date, with no schedule or alias.

- [x] Correct the public metric contract: v2 shipment volume, insights v3 root
  causes, actions v2 action distribution, no legacy v1 or trace claims.
- [x] Correct outcome ratio display (`0.375` means `37.5%`) and label every
  public outcome as simulated.
- [ ] Publish the existing six-stage controller and quality-gate status without
  exposing private AWS identifiers.
- [x] Seed a representative active population across lifecycle stages.
- [x] Add approximately 14--18 new shipments per normal day while carrying
  active shipment IDs across logical dates.
- [x] Preserve the single immutable P2P ETD/ETA and set ATD/ATA only when their
  milestones occur in the governed AWS writer.
- [x] Stop active updates after delivery while retaining completed history.
- [ ] Add SLA breach and cost anomaly alongside the existing high-risk-route
  alert, with explicit grain and stable lifecycle identity.
- [ ] Add delayed, reproducible and context-dependent simulated outcomes.
- [ ] Route learning into a human-reviewed decision-policy proposal, not an
  automatic simulation-generator change.

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
  - 5 August Pages export stopped safely before publication because the updated
    canonical shipment query needs source-database Glue/Lake Formation access.
    Re-run `ops/configure_ops_snapshot_access.ps1` with the AWS admin/read
    profiles, then re-dispatch Pages; keep required pipeline verification off
    until the first governed controller run is confirmed.

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
- [ ] Add a governed External Intelligence pipeline for weather, equipment
  shortage, geopolitical disruption, port congestion and labour-action evidence.
- [ ] Use an LLM only to extract, normalize, classify and summarize sourced
  external events; use deterministic matching to identify exposed OPEN shipments.
- [ ] Require source URL/publication time, effective window, confidence, expiry,
  deduplication key and model version for every external-risk insight or warning.

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

`P0 metric correctness and reliability → stateful shipment lifecycle → alert lifecycle → delayed outcome and governed policy feedback → internal write-back/cockpit → forecast validation → production readiness`
