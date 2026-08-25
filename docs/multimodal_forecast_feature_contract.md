# Multimodal Forecast Feature Contract v1

**Contract:** `multimodal_forecast_feature_daily_v1`

**Source view:** `vw_multimodal_forecast_feature_daily_v1`

**Status:** frozen for private staging validation

**Decision use:** advisory only

## Grain and target

One row represents one `feature_date`, `transport_mode`, and `provider_code`.
The initial target is `new_booking_count` for the next provider-day. Air and
Ocean are evaluated separately; their commercial cost units are not combined.

The business key is unique and non-null. Missing provider-days are missing
observations, not implicit zero-volume days. A caller may create a complete
calendar only if it records that transformation in the model metadata.

## Availability and cutoff

The row becomes available only after `feature_date` has closed and the isolated
controller has passed its lifecycle, compatibility, and analytics checks.
`feature_cutoff_date` is the latest business date represented by the row.

For a forecast with target date `T`, training rows and fitted features must have
`feature_date < T`. Same-day operational fields describe the closed feature day;
they must never be used to predict that same day's booking count. Lag and
trailing fields are calculated with windows ending at least one row before the
feature date. The contract does not forward-fill future or pending values.

Operational callers may select only dates on or before the current
`Australia/Sydney` business date. Future logical dates require an explicit,
staging-only `FUTURE_SIMULATION` scenario and are not operational history.

## Null rules

| Field class | Rule |
| --- | --- |
| Key and target | Reject nulls and duplicate keys. Booking count must be non-negative. |
| Lag features | Null until enough prior observations exist; do not replace with future values. |
| Actual-duration and SLA measures | May be null while milestones or denominators are unavailable. |
| Cost per unit | May be null when its mode-specific denominator is unavailable; never convert Air per-kg and Ocean per-container values into one operational unit. |
| Outcome labels | Train only where `outcome_status = 'OBSERVED'`; `PENDING` labels and their null values are excluded. |

## Backtest policy

[`ops/backtest_multimodal_forecast.py`](../ops/backtest_multimodal_forecast.py)
runs rolling, one-step-ahead evaluations independently for each mode/provider.
It compares recent level, seven-observation moving average, weekday seasonal,
and 28-observation OLS trend baselines. Each prediction records its training
start, training end, and row count.

Reports include MAE, RMSE, signed bias, 95% residual interval coverage, and MAPE
only for non-zero actuals. Model selection retains the simplest healthy baseline
unless a candidate lowers both MAE and RMSE and wins at least 60% of comparable
held-out points across at least seven forecast windows. Reports also expose
calendar completeness, missing dates,
recent-versus-prior seven-day booking drift, normalized MAE, and providers that
do not yet have enough history to evaluate. Both Athena reads record a default
100 MiB per-query scan budget and an explicit `within_budget` or `exceeded`
status. This contract does not authorize recurring execution, production
writes, or policy changes.

A future-simulation backtest can validate time ordering and evaluation code,
but its metrics are not real forecast-performance or model-promotion evidence.
Operational model decisions must use actual-calendar data only.

## Private AWS execution

The manual `backtest-multimodal-forecast-staging.yml` workflow queries only the
aggregate feature view through the staging OIDC role. It records Athena bytes
scanned, validates the contract fields, and stores the CSV and JSON report as a
14-day workflow artifact. It does not publish to Pages, create a schedule, or
write any production or staging business table. Run `plan` first; `backtest`
performs the explicitly requested read-only query.

Before the first backtest, deploy this frozen view definition with the manual
stateful-lifecycle workflow action `deploy-analytics-contract`. That action uses
the existing `AnalyticsOnly` path, replaces only the six read-only staging view
definitions, and runs the staging validation contract for the selected existing
logical date. It does not invoke lifecycle generation or update a table.

## Supervised-label readiness gate

The same private workflow reads an aggregate-only summary from
`vw_multimodal_outcome_label_v1`; it never exports shipment identifiers. For an
operational run, the selected cutoff cannot exceed the current Sydney date and
the query excludes outcomes observed after that cutoff. A future scenario must
be explicit and cannot contribute to operational readiness.

The initial governed thresholds apply independently to every mode/provider:

- at least 200 observed outcomes before any supervised target is eligible;
- at least 20 positive and 20 negative observations for SLA-breach or delay-risk
  classification;
- at least 10 distinct observed cost-variance values for cost regression.

`PENDING` outcomes are counted for coverage but excluded from every target and
can never be interpreted as a negative label. The readiness report returns
`blocked_insufficient_observed_labels`, `partially_ready`, or `ready`, plus
target-specific blockers. These thresholds permit evaluation only; they do not
authorize deployment or recurring prediction.

### Authenticated provider-readiness surface

The repository implements a private, read-only `GET /v1/label-readiness`
projection over the governed operational label view. It groups only by
transport mode and provider, returns exact gaps to each frozen threshold, and
contains no entity identifiers. The server derives the Sydney cutoff; callers
cannot supply an `as_of_date`. `PENDING` labels remain visible only as excluded
coverage, while `FUTURE_SIMULATION` rows cannot enter the query or response.

The private cockpit renders provider and target blockers without changing the
gate. Even a `ready` response means eligible for supervised evaluation only.
The response fixes `model_training_authorized`, `model_promotion_authorized`,
and `production_readiness` to false. The implementation and its plan-first
staging route, least-privilege resource inventory, tests, and verifier are
locally complete but have not been deployed or runtime-verified.
