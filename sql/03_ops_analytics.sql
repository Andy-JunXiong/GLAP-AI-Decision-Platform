-- GLAP operational analytics and transparent forecast baselines.
-- These are read-only Athena Engine v3 queries. The route/carrier queries are
-- intended for the private analyst workspace; the public Pages exporter emits
-- only daily aggregate totals.

-- Runtime publication injects the governed pipeline logical_run_date. The
-- standalone examples use current_date as the safe upper bound and never use
-- future event_time values as a batch/run anchor.

-- 1. Current decision-flywheel stage counts and logical run dates.
WITH stage_metrics AS (
    SELECT 'shipments' AS stage, max(try_cast(dt AS date)) AS run_date,
        count(DISTINCT shipment_id) AS total_records
    FROM curated_iceberg.fact_shipment_events_extended_iceberg
    WHERE try_cast(dt AS date) <= current_date
    UNION ALL
    SELECT 'alerts', max(run_date), count(*) FROM curated_iceberg.fact_ai_alerts_v3
    WHERE run_date <= current_date
    UNION ALL
    SELECT 'root_causes', max(run_date), count(*) FROM curated_iceberg.fact_ai_insights_v3
    WHERE run_date <= current_date
    UNION ALL
    SELECT 'decisions', max(run_date), count(*) FROM curated_iceberg.fact_ai_decisions_v3
    WHERE run_date <= current_date
    UNION ALL
    SELECT 'actions', max(run_date), count(*) FROM curated_iceberg.fact_ai_actions_v2
    WHERE run_date <= current_date
    UNION ALL
    SELECT 'outcomes', max(run_date), count(*) FROM curated_iceberg.fact_ai_outcomes_v2
    WHERE run_date <= current_date
    UNION ALL
    SELECT 'learning', max(run_date), count(*) FROM curated_iceberg.fact_ai_learning_v1
    WHERE run_date <= current_date
)
SELECT stage, run_date, total_records
FROM stage_metrics
ORDER BY run_date DESC, stage;

-- 2. Private operations hotspot analysis by route, carrier, and severity.
WITH latest AS (
    SELECT max(run_date) AS run_date
    FROM curated_iceberg.fact_ai_alerts_v3
)
SELECT
    alerts.run_date,
    alerts.route_id,
    alerts.carrier,
    alerts.severity,
    count(*) AS alert_count,
    round(avg(alerts.deviation_pct), 2) AS avg_deviation_pct,
    round(max(alerts.deviation_pct), 2) AS max_deviation_pct
FROM curated_iceberg.fact_ai_alerts_v3 AS alerts
CROSS JOIN latest
WHERE alerts.run_date = latest.run_date
GROUP BY alerts.run_date, alerts.route_id, alerts.carrier, alerts.severity
ORDER BY alert_count DESC, max_deviation_pct DESC
LIMIT 100;

-- 3. Seven-day shipment-volume baseline using 28 calendar days and ordinary
-- least squares. Missing calendar days are retained as zero-volume days so
-- ingestion gaps remain visible instead of silently disappearing.
WITH bounds AS (
    SELECT current_date AS latest_date
),
calendar AS (
    SELECT day
    FROM bounds
    CROSS JOIN UNNEST(
        sequence(date_add('day', -27, latest_date), latest_date, INTERVAL '1' DAY)
    ) AS dates(day)
),
observed AS (
    SELECT try_cast(dt AS date) AS day,
        count(DISTINCT shipment_id) AS shipments
    FROM curated_iceberg.fact_shipment_events_extended_iceberg
    CROSS JOIN bounds
    WHERE try_cast(dt AS date) BETWEEN date_add('day', -27, latest_date) AND latest_date
    GROUP BY try_cast(dt AS date)
),
series AS (
    SELECT
        calendar.day,
        coalesce(observed.shipments, 0) AS shipments,
        row_number() OVER (ORDER BY calendar.day) - 1 AS x
    FROM calendar
    LEFT JOIN observed ON calendar.day = observed.day
),
terms AS (
    SELECT
        count(*) AS n,
        sum(CAST(x AS double)) AS sum_x,
        sum(CAST(shipments AS double)) AS sum_y,
        sum(CAST(x AS double) * CAST(shipments AS double)) AS sum_xy,
        sum(CAST(x AS double) * CAST(x AS double)) AS sum_xx,
        max(day) AS anchor_date
    FROM series
),
model AS (
    SELECT
        anchor_date,
        (n * sum_xy - sum_x * sum_y) / nullif(n * sum_xx - sum_x * sum_x, 0) AS slope,
        (sum_y - ((n * sum_xy - sum_x * sum_y)
            / nullif(n * sum_xx - sum_x * sum_x, 0)) * sum_x) / n AS intercept
    FROM terms
)
SELECT
    date_add('day', horizon, anchor_date) AS forecast_date,
    greatest(0, CAST(round(intercept + slope * (27 + horizon)) AS bigint))
        AS predicted_shipments,
    'OLS_28D_BASELINE' AS model_version
FROM model
CROSS JOIN UNNEST(sequence(1, 7)) AS future(horizon)
ORDER BY forecast_date;

-- 4. Decision-to-outcome effectiveness for operator and policy review.
WITH latest_outcome AS (
    SELECT max(run_date) AS run_date
    FROM curated_iceberg.fact_ai_outcomes_v2
)
SELECT
    outcomes.action_type,
    count(*) AS measured_outcomes,
    round(100.0 * sum(CASE WHEN outcomes.improvement_pct > 0 THEN 1 ELSE 0 END)
        / nullif(count(*), 0), 1) AS success_rate_pct,
    round(avg(outcomes.improvement_pct), 2) AS avg_improvement_pct,
    round(avg(outcomes.effectiveness_score), 3) AS avg_effectiveness_score,
    round(avg(CAST(outcomes.lag_days AS double)), 1) AS avg_lag_days
FROM curated_iceberg.fact_ai_outcomes_v2 AS outcomes
CROSS JOIN latest_outcome
WHERE outcomes.run_date = latest_outcome.run_date
GROUP BY outcomes.action_type
ORDER BY avg_effectiveness_score DESC, measured_outcomes DESC;

-- 5. Existing deployed analysis assets. Inventory these before proposing a new
-- mart. v_ai_latest_decision_trace is safe to reuse at its current date grain;
-- Athena also requires catalog access to its ai_decision_trace_v1 dependency.
SELECT count(*) AS latest_decision_traces
FROM curated_iceberg.v_ai_latest_decision_trace
WHERE run_date = current_date;

-- The older ai_decision_trace_v1 and v_ai_*_distribution views join several
-- one-to-many stages. Inspection showed join fan-out, so the public aggregate
-- path does not use those views. It reuses the existing result tables directly
-- at one exact logical run date; it does not create replacement tables.
SELECT alert_type, count(*) AS alert_count
FROM curated_iceberg.fact_ai_alerts_v3
WHERE run_date = current_date
GROUP BY alert_type
ORDER BY alert_count DESC;

SELECT action_type, count(*) AS action_count
FROM curated_iceberg.fact_ai_decisions_v3
WHERE run_date = current_date
GROUP BY action_type
ORDER BY action_count DESC;

SELECT root_cause_title, count(*) AS cause_count
FROM curated_iceberg.fact_ai_root_causes_v1
WHERE run_date = current_date
GROUP BY root_cause_title
ORDER BY cause_count DESC;

-- Existing feedback is retained as a learning input and freshness dependency.
SELECT max(run_date) AS latest_feedback_date, count(*) AS feedback_records
FROM curated_iceberg.fact_ai_learning_feedback_v1
WHERE run_date <= current_date;

-- Public publication counts distinct hotspots from the existing alerts result
-- table; route and carrier values remain inside the authenticated AWS boundary.
SELECT count(*) AS risk_hotspots_tracked
FROM (
    SELECT DISTINCT route_id, carrier, alert_type
    FROM curated_iceberg.fact_ai_alerts_v3
    WHERE run_date = current_date
);
