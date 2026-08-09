# Internal analytics view governance

**Scope:** private staging analytics only
**Business timezone:** `Australia/Sydney`
**Evidence boundary:** all rows described here are synthetic.  Operational-calendar
rows are not real-world performance evidence, and future simulations must use a
named `*_context_v1` view with exactly one temporal scope.

This register supplies the grain, accountable role, source, freshness, and
reconciliation rule required before an internal view can support a cockpit,
forecast evaluation, or aggregate export.  It does not create a schedule,
materialized copy, production table, or public entity-level output.

## Ownership and operating rule

The **staging lifecycle data steward** is accountable for source-contract and
temporal-boundary changes.  The **analytics steward** is accountable for query
cost, view use, and reconciliation evidence.  The project has not assigned
named humans to these roles; a human owner must be recorded before recurring
execution is proposed.  The **Operations API owner** is accountable for any
private cockpit query that consumes a view.

Freshness is a statement about a successful, manual staging run for a logical
date; it is not a claim that the underlying synthetic logistics data is
real-world current.  A default view admits only `OPERATIONAL`,
`ACTUAL_CALENDAR` rows at or before the system-derived Sydney cutoff.  A failed,
missing, or late validation result makes the consumer state stale or unavailable
rather than silently reusing the view as current.

## Governed analytics views

| View | Grain and intended use | Accountable role | Source and freshness expectation | Reconciliation rule |
| --- | --- | --- | --- | --- |
| `vw_multimodal_shipment_daily_v1` | One shipment snapshot per `shipment_id`, `metric_date`, and temporal scope; analytic base for private shipment, mode, and provider work. | Staging lifecycle data steward | Lifecycle snapshot plus one matching metric row; available only after the manual lifecycle and analytics validation for the logical date succeeds. | The shipment/metric join is one-to-one on shipment, date, and scope; the analytics contract rejects duplicate shipment-date keys. |
| `vw_multimodal_ops_daily_v1` | One `metric_date` and transport mode; daily operational aggregate. | Analytics steward | Aggregates the governed shipment-daily view after its source date has passed the same validation. | The sum of `shipment_snapshot_count` across mode rows equals the shipment-daily row count for the same date and scope. |
| `vw_multimodal_provider_daily_v1` | One `metric_date`, transport mode, and provider; provider comparison and forecast input. | Analytics steward | Aggregates the governed shipment-daily view after the source date is validated. | The sum of `shipment_snapshot_count` across provider rows equals the shipment-daily row count for the same date and scope. |
| `vw_multimodal_mode_decision_v1` | One `metric_date`, market lane, and transport mode; advisory Air-versus-Ocean comparison only. | Analytics steward | Derived from the daily shipment base and refreshed when that date is successfully validated. | Every Air comparison for a selected date/scope must have its Ocean reference; no decision may treat this synthetic comparison as a production instruction. |
| `vw_multimodal_forecast_feature_daily_v1` | One `feature_date`, transport mode, and provider; past-only booking-volume forecast feature row. | Analytics steward | Published after the closed feature date and successful lifecycle, compatibility, and analytics checks. | Key is unique and non-null; lag and trailing windows end before `feature_date`, so the feature cutoff cannot use future or same-day target data. |
| `vw_multimodal_outcome_label_v1` | Latest lifecycle outcome label per shipment and temporal scope; a delivery-label readiness input, distinct from the governed Action Outcome table. | Staging lifecycle data steward | Uses the latest shipment-daily row, available after its source date validates. | Exactly one latest snapshot is selected per shipment/scope. Pending deliveries retain null target labels; only observed lifecycle deliveries populate label fields. |
| `vw_multimodal_operational_baseline_v1` | One frozen as-of aggregate for `ALL`, transport mode, provider, or market lane; private aggregate baseline and Control Tower maturity input. | Analytics steward | Explicitly rebuilt for a reviewed Sydney as-of date; it is not an automatically refreshed daily mart. | Ten fail-closed checks require one `ALL` row, unique dimensions, no scenario leakage, a bounded cutoff, and equal overall/mode/provider/lane shipment totals. |

## Context-view safeguard

The matching `*_context_v1` views retain both operational and explicitly named
simulation scopes.  They are for governed analysis only: every query must filter
one `temporal_scope_id`, preserve execution-mode/time-basis fields, and state
its scenario.  They must not be substituted into a default cockpit, public
export, readiness report, or model-promotion evidence.

## Cost-control design before recurring analytics

No Athena workgroup setting or alarm has been changed by this document.  Before
any recurring analytics execution, the analytics steward must submit a reviewed
change that:

1. creates or selects a staging-only Athena workgroup with enforced result
   location, encryption, engine version 3, and a per-query data-scan cutoff;
2. sets query bytes-scanned budgets for each scheduled query class, beginning
   with the existing 100 MiB forecast/backtest limit, and records query ID,
   scan bytes, workgroup, logical date, and outcome in private evidence;
3. creates cost and failed-query alarms with an owner, response target,
   threshold, and runbook; alarms must not publish raw query text, S3 paths, or
   entity identifiers publicly;
4. defines each incremental refresh by source watermark, temporal scope,
   idempotent key, late-arrival rule, and reconciliation check; and
5. proves the workgroup has no production-table write, schedule-creation,
   policy-activation, or public-export permission.

The change review must include the projected scan cost, retention period for
query results, a rollback procedure, and proof that a failed refresh leaves the
last verified aggregate explicitly stale rather than fresh-looking.
