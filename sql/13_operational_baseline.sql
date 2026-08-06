-- Frozen operational-calendar baseline through one governed Sydney as-of date.
-- The staging source is synthetic; this contract must never be described as
-- real-world performance evidence.

CREATE OR REPLACE VIEW {{SOURCE_DATABASE}}.vw_multimodal_operational_baseline_v1 AS
WITH operational_snapshots AS (
    SELECT *
    FROM {{SOURCE_DATABASE}}.vw_multimodal_shipment_daily_context_v1
    WHERE metric_date <= DATE '{{AS_OF_DATE}}'
      AND as_of_date <= DATE '{{AS_OF_DATE}}'
      AND temporal_scope_id = 'OPERATIONAL'
      AND execution_mode = 'OPERATIONAL'
      AND time_basis = 'ACTUAL_CALENDAR'
      AND execution_scenario_id IS NULL
),
shipment_rollup AS (
    SELECT
        shipment_id,
        coalesce(max_by(transport_mode, metric_date), 'UNKNOWN') AS transport_mode,
        coalesce(max_by(carrier, metric_date), 'UNKNOWN') AS provider_code,
        coalesce(max_by(market_lane, metric_date), 'UNKNOWN') AS market_lane,
        min(metric_date) AS first_observed_date,
        max(metric_date) AS last_observed_date,
        count_if(new_booking_flag) > 0 AS new_booking_observed,
        count_if(delivered_today_flag) > 0 AS delivery_observed,
        max_by(delivery_performance, metric_date) AS delivery_performance,
        max_by(delivery_delay_hours, metric_date) AS delivery_delay_hours,
        count_if(sla_breach_flag) > 0 AS sla_breach_observed,
        max_by(expected_total_cost, metric_date) AS expected_total_cost,
        max_by(current_total_cost, metric_date) AS current_total_cost
    FROM operational_snapshots
    GROUP BY shipment_id
),
signal_rollup AS (
    SELECT
        shipment_id,
        count(*) AS signal_candidate_count,
        count_if(upper(coalesce(severity, '')) IN ('HIGH', 'CRITICAL'))
            AS high_severity_signal_count
    FROM {{SOURCE_DATABASE}}.fact_shipment_signal_candidate_staging_v1
    WHERE try_cast(dt AS date) <= DATE '{{AS_OF_DATE}}'
      AND as_of_date <= DATE '{{AS_OF_DATE}}'
      AND temporal_scope_id = 'OPERATIONAL'
      AND execution_mode = 'OPERATIONAL'
      AND time_basis = 'ACTUAL_CALENDAR'
      AND execution_scenario_id IS NULL
    GROUP BY shipment_id
),
shipment_level AS (
    SELECT
        shipment.*,
        coalesce(signal.signal_candidate_count, 0) AS signal_candidate_count,
        coalesce(signal.high_severity_signal_count, 0) AS high_severity_signal_count
    FROM shipment_rollup AS shipment
    LEFT JOIN signal_rollup AS signal ON shipment.shipment_id = signal.shipment_id
),
dimension_membership AS (
    SELECT 'ALL' AS dimension_type, 'ALL' AS dimension_value, shipment.*
    FROM shipment_level AS shipment
    UNION ALL
    SELECT 'TRANSPORT_MODE', transport_mode, shipment.*
    FROM shipment_level AS shipment
    UNION ALL
    SELECT 'PROVIDER', provider_code, shipment.*
    FROM shipment_level AS shipment
    UNION ALL
    SELECT 'MARKET_LANE', market_lane, shipment.*
    FROM shipment_level AS shipment
)
SELECT
    DATE '{{AS_OF_DATE}}' AS baseline_as_of_date,
    min(first_observed_date) AS source_start_date,
    max(last_observed_date) AS source_max_metric_date,
    dimension_type,
    dimension_value,
    count(*) AS shipment_count,
    count_if(new_booking_observed) AS new_booking_count,
    count_if(delivery_observed) AS delivered_count,
    count_if(delivery_observed AND delivery_performance = 'ON_TIME')
        AS on_time_delivery_count,
    count_if(delivery_observed AND delivery_performance IN ('LATE', 'OVERDUE'))
        AS late_delivery_count,
    round(
        100.0 * count_if(delivery_observed AND delivery_performance = 'ON_TIME')
        / nullif(count_if(delivery_observed), 0),
        2
    ) AS on_time_delivery_rate_pct,
    round(avg(
        IF(
            delivery_observed,
            greatest(coalesce(delivery_delay_hours, 0.0), 0.0),
            CAST(NULL AS double)
        )
    ), 2) AS avg_delivery_delay_hours,
    count_if(sla_breach_observed) AS sla_breach_shipment_count,
    round(
        100.0 * count_if(sla_breach_observed) / nullif(count(*), 0),
        2
    ) AS sla_breach_shipment_rate_pct,
    round(sum(expected_total_cost), 2) AS expected_cost_total,
    round(sum(current_total_cost), 2) AS current_cost_total,
    round(
        100.0 * (
            sum(IF(delivery_observed, current_total_cost, CAST(NULL AS double)))
            / nullif(
                sum(IF(delivery_observed, expected_total_cost, CAST(NULL AS double))),
                0.0
            ) - 1.0
        ),
        2
    ) AS cost_variance_pct,
    sum(signal_candidate_count) AS signal_candidate_count,
    sum(high_severity_signal_count) AS high_severity_signal_count,
    'OPERATIONAL' AS temporal_scope_id,
    'OPERATIONAL' AS execution_mode,
    'ACTUAL_CALENDAR' AS time_basis,
    CAST(NULL AS varchar) AS execution_scenario_id,
    false AS real_world_evidence,
    'SIMULATED_MULTIMODAL_V1' AS data_provenance,
    'SYNTHETIC_OPERATIONAL_CALENDAR_BASELINE' AS evidence_class,
    'ENGINEERING_EVALUATION_ONLY' AS decision_use
FROM dimension_membership
GROUP BY dimension_type, dimension_value;
