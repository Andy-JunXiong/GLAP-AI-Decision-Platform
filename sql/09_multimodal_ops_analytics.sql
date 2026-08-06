-- Read-only multimodal operational analytics over isolated lifecycle staging.
-- Air and Ocean share the same lifecycle stages, while their commercial units
-- stay explicit: Air is measured per chargeable kilogram and Ocean per container.

CREATE OR REPLACE VIEW {{SOURCE_DATABASE}}.vw_multimodal_shipment_daily_context_v1 AS
SELECT
    try_cast(shipment.dt AS date) AS metric_date,
    shipment.temporal_scope_id,
    shipment.execution_mode,
    shipment.time_basis,
    shipment.as_of_date,
    shipment.execution_scenario_id,
    shipment.shipment_id,
    coalesce(shipment.transport_mode, 'OCEAN') AS transport_mode,
    shipment.carrier,
    shipment.provider_type,
    shipment.operating_carrier,
    shipment.route_service_id,
    shipment.service_level,
    shipment.lifecycle_stage,
    shipment.lifecycle_status,
    shipment.terminal_state,
    shipment.origin_port,
    shipment.destination_port,
    CASE shipment.origin_port
        WHEN 'CNSHA' THEN 'SHA'
        WHEN 'PVG' THEN 'SHA'
        WHEN 'CNNGB' THEN 'NGB'
        WHEN 'NGB' THEN 'NGB'
        WHEN 'SGSIN' THEN 'SIN'
        WHEN 'SIN' THEN 'SIN'
        WHEN 'KRPUS' THEN 'PUS'
        WHEN 'PUS' THEN 'PUS'
        ELSE shipment.origin_port
    END AS origin_market,
    CASE shipment.destination_port
        WHEN 'AUSYD' THEN 'SYD'
        WHEN 'SYD' THEN 'SYD'
        WHEN 'AUMEL' THEN 'MEL'
        WHEN 'MEL' THEN 'MEL'
        WHEN 'AUBNE' THEN 'BNE'
        WHEN 'BNE' THEN 'BNE'
        ELSE shipment.destination_port
    END AS destination_market,
    concat(
        CASE shipment.origin_port
            WHEN 'CNSHA' THEN 'SHA' WHEN 'PVG' THEN 'SHA'
            WHEN 'CNNGB' THEN 'NGB' WHEN 'NGB' THEN 'NGB'
            WHEN 'SGSIN' THEN 'SIN' WHEN 'SIN' THEN 'SIN'
            WHEN 'KRPUS' THEN 'PUS' WHEN 'PUS' THEN 'PUS'
            ELSE shipment.origin_port
        END,
        '-',
        CASE shipment.destination_port
            WHEN 'AUSYD' THEN 'SYD' WHEN 'SYD' THEN 'SYD'
            WHEN 'AUMEL' THEN 'MEL' WHEN 'MEL' THEN 'MEL'
            WHEN 'AUBNE' THEN 'BNE' WHEN 'BNE' THEN 'BNE'
            ELSE shipment.destination_port
        END
    ) AS market_lane,
    IF(CAST(shipment.booking_at AS date) = try_cast(shipment.dt AS date), true, false)
        AS new_booking_flag,
    IF(CAST(shipment.delivered_at AS date) = try_cast(shipment.dt AS date), true, false)
        AS delivered_today_flag,
    metric.origin_performance,
    metric.origin_delay_hours,
    metric.departure_performance,
    metric.departure_delay_hours,
    metric.arrival_performance,
    metric.arrival_delay_hours,
    metric.destination_release_performance,
    metric.destination_release_delay_hours,
    metric.delivery_performance,
    metric.delivery_delay_hours,
    metric.planned_p2p_hours,
    metric.actual_p2p_hours,
    metric.sla_breach_flag,
    IF(metric.origin_performance IN ('LATE', 'OVERDUE'), true, false)
        AS origin_breach_flag,
    IF(metric.actual_p2p_hours IS NOT NULL
       AND metric.actual_p2p_hours > metric.planned_p2p_hours, true, false)
        AS p2p_breach_flag,
    IF(metric.destination_release_performance IN ('LATE', 'OVERDUE'), true, false)
        AS destination_breach_flag,
    CAST(shipment.expected_total_cost AS double) AS expected_total_cost,
    CAST(coalesce(
        shipment.actual_total_cost,
        shipment.accrued_total_cost,
        shipment.expected_total_cost
    ) AS double) AS current_total_cost,
    IF(coalesce(shipment.transport_mode, 'OCEAN') = 'AIR',
       CAST(shipment.chargeable_weight_kg AS double),
       CAST(shipment.container_count AS double)) AS cargo_unit_quantity,
    IF(coalesce(shipment.transport_mode, 'OCEAN') = 'AIR',
       'CHARGEABLE_KG', 'CONTAINER') AS cargo_unit,
    IF(coalesce(shipment.transport_mode, 'OCEAN') = 'AIR',
       CAST(shipment.chargeable_weight_kg AS double),
       CAST(shipment.gross_weight_kg AS double)) AS comparison_weight_kg,
    CAST(
        shipment.expected_total_cost / nullif(
            IF(coalesce(shipment.transport_mode, 'OCEAN') = 'AIR',
               shipment.chargeable_weight_kg,
               CAST(shipment.container_count AS decimal(18,2))),
            DECIMAL '0.00'
        ) AS double
    ) AS expected_cost_per_unit,
    'SIMULATED_MULTIMODAL_V1' AS data_provenance
FROM {{SOURCE_DATABASE}}.fact_shipment_lifecycle_staging_v1 AS shipment
JOIN {{SOURCE_DATABASE}}.fact_shipment_lifecycle_metrics_staging_v1 AS metric
 ON shipment.shipment_id = metric.shipment_id
 AND shipment.dt = metric.dt
 AND shipment.temporal_scope_id = metric.temporal_scope_id;

CREATE OR REPLACE VIEW {{SOURCE_DATABASE}}.vw_multimodal_ops_daily_context_v1 AS
SELECT
    metric_date,
    temporal_scope_id,
    execution_mode,
    time_basis,
    as_of_date,
    execution_scenario_id,
    transport_mode,
    count(*) AS shipment_snapshot_count,
    count_if(lifecycle_status = 'OPEN') AS active_shipment_count,
    count_if(new_booking_flag) AS new_booking_count,
    count_if(delivered_today_flag) AS delivered_count,
    count_if(sla_breach_flag) AS sla_breach_count,
    round(100.0 * count_if(sla_breach_flag) / nullif(count(*), 0), 2)
        AS sla_breach_rate_pct,
    count_if(origin_breach_flag) AS origin_breach_count,
    count_if(p2p_breach_flag) AS p2p_breach_count,
    count_if(destination_breach_flag) AS destination_breach_count,
    round(avg(planned_p2p_hours), 2) AS avg_planned_p2p_hours,
    round(avg(actual_p2p_hours), 2) AS avg_actual_p2p_hours,
    round(sum(expected_total_cost), 2) AS expected_cost_total,
    round(sum(current_total_cost), 2) AS current_cost_total,
    round(sum(cargo_unit_quantity), 2) AS cargo_unit_quantity,
    max(cargo_unit) AS cargo_unit,
    round(sum(expected_total_cost) / nullif(sum(cargo_unit_quantity), 0.0), 2)
        AS expected_cost_per_unit,
    'SIMULATED_MULTIMODAL_V1' AS data_provenance
FROM {{SOURCE_DATABASE}}.vw_multimodal_shipment_daily_context_v1
GROUP BY metric_date, temporal_scope_id, execution_mode, time_basis, as_of_date,
         execution_scenario_id, transport_mode;

CREATE OR REPLACE VIEW {{SOURCE_DATABASE}}.vw_multimodal_provider_daily_context_v1 AS
SELECT
    metric_date,
    temporal_scope_id,
    execution_mode,
    time_basis,
    as_of_date,
    execution_scenario_id,
    transport_mode,
    carrier AS provider_code,
    count(*) AS shipment_snapshot_count,
    count_if(lifecycle_status = 'OPEN') AS active_shipment_count,
    count_if(new_booking_flag) AS new_booking_count,
    count_if(delivered_today_flag) AS delivered_count,
    count_if(sla_breach_flag) AS sla_breach_count,
    round(100.0 * count_if(sla_breach_flag) / nullif(count(*), 0), 2)
        AS sla_breach_rate_pct,
    count_if(origin_breach_flag) AS origin_breach_count,
    count_if(p2p_breach_flag) AS p2p_breach_count,
    count_if(destination_breach_flag) AS destination_breach_count,
    round(avg(planned_p2p_hours), 2) AS avg_planned_p2p_hours,
    round(avg(actual_p2p_hours), 2) AS avg_actual_p2p_hours,
    round(sum(expected_total_cost), 2) AS expected_cost_total,
    round(sum(current_total_cost), 2) AS current_cost_total,
    round(sum(cargo_unit_quantity), 2) AS cargo_unit_quantity,
    max(cargo_unit) AS cargo_unit,
    round(sum(expected_total_cost) / nullif(sum(cargo_unit_quantity), 0.0), 2)
        AS expected_cost_per_unit,
    'SIMULATED_MULTIMODAL_V1' AS data_provenance
FROM {{SOURCE_DATABASE}}.vw_multimodal_shipment_daily_context_v1
GROUP BY metric_date, temporal_scope_id, execution_mode, time_basis, as_of_date,
         execution_scenario_id, transport_mode, carrier;

CREATE OR REPLACE VIEW {{SOURCE_DATABASE}}.vw_multimodal_mode_decision_context_v1 AS
WITH lane_mode AS (
    SELECT
        metric_date,
        temporal_scope_id,
        execution_mode,
        time_basis,
        as_of_date,
        execution_scenario_id,
        market_lane,
        origin_market,
        destination_market,
        transport_mode,
        count(*) AS shipment_snapshot_count,
        round(avg(planned_p2p_hours), 2) AS avg_planned_p2p_hours,
        round(avg(actual_p2p_hours), 2) AS avg_actual_p2p_hours,
        round(avg(expected_total_cost), 2) AS avg_expected_cost_per_shipment,
        round(sum(expected_total_cost) / nullif(sum(comparison_weight_kg), 0.0), 4)
            AS expected_cost_per_comparison_kg,
        round(100.0 * count_if(sla_breach_flag) / nullif(count(*), 0), 2)
            AS sla_breach_rate_pct
    FROM {{SOURCE_DATABASE}}.vw_multimodal_shipment_daily_context_v1
    GROUP BY metric_date, temporal_scope_id, execution_mode, time_basis, as_of_date,
             execution_scenario_id, market_lane, origin_market, destination_market,
             transport_mode
),
ocean_reference AS (
    SELECT
        metric_date,
        temporal_scope_id,
        market_lane,
        avg_planned_p2p_hours AS ocean_planned_p2p_hours,
        avg_expected_cost_per_shipment AS ocean_expected_cost_per_shipment,
        expected_cost_per_comparison_kg AS ocean_expected_cost_per_comparison_kg,
        sla_breach_rate_pct AS ocean_sla_breach_rate_pct
    FROM lane_mode
    WHERE transport_mode = 'OCEAN'
)
SELECT
    lane.metric_date,
    lane.temporal_scope_id,
    lane.execution_mode,
    lane.time_basis,
    lane.as_of_date,
    lane.execution_scenario_id,
    lane.market_lane,
    lane.origin_market,
    lane.destination_market,
    lane.transport_mode,
    lane.shipment_snapshot_count,
    lane.avg_planned_p2p_hours,
    lane.avg_actual_p2p_hours,
    lane.avg_expected_cost_per_shipment,
    lane.expected_cost_per_comparison_kg,
    lane.sla_breach_rate_pct,
    ocean.ocean_planned_p2p_hours,
    ocean.ocean_expected_cost_per_shipment,
    ocean.ocean_expected_cost_per_comparison_kg,
    ocean.ocean_sla_breach_rate_pct,
    round(ocean.ocean_planned_p2p_hours - lane.avg_planned_p2p_hours, 2)
        AS planned_hours_saved_vs_ocean,
    round(100.0 * (
        lane.expected_cost_per_comparison_kg / nullif(
            ocean.ocean_expected_cost_per_comparison_kg, 0.0
        ) - 1.0
    ), 2) AS expected_cost_premium_vs_ocean_pct,
    'AIR_CHARGEABLE_KG_VS_OCEAN_GROSS_KG' AS cost_comparison_basis,
    IF(ocean.market_lane IS NULL, 'REFERENCE_PENDING', 'COMPARABLE')
        AS comparison_status,
    'ADVISORY_SIMULATION_ONLY' AS decision_use,
    'SIMULATED_MULTIMODAL_V1' AS data_provenance
FROM lane_mode AS lane
LEFT JOIN ocean_reference AS ocean
  ON lane.metric_date = ocean.metric_date
 AND lane.market_lane = ocean.market_lane
 AND lane.temporal_scope_id = ocean.temporal_scope_id;

CREATE OR REPLACE VIEW {{SOURCE_DATABASE}}.vw_multimodal_forecast_feature_daily_context_v1 AS
WITH source AS (
    SELECT
        metric_date AS feature_date,
        temporal_scope_id,
        execution_mode,
        time_basis,
        as_of_date,
        execution_scenario_id,
        transport_mode,
        provider_code,
        shipment_snapshot_count,
        active_shipment_count,
        new_booking_count,
        delivered_count,
        sla_breach_rate_pct,
        avg_planned_p2p_hours,
        avg_actual_p2p_hours,
        expected_cost_per_unit,
        cargo_unit_quantity,
        cargo_unit
    FROM {{SOURCE_DATABASE}}.vw_multimodal_provider_daily_context_v1
)
SELECT
    feature_date,
    temporal_scope_id,
    execution_mode,
    time_basis,
    as_of_date,
    execution_scenario_id,
    day_of_week(feature_date) AS feature_day_of_week,
    transport_mode,
    provider_code,
    shipment_snapshot_count,
    active_shipment_count,
    new_booking_count,
    delivered_count,
    sla_breach_rate_pct,
    avg_planned_p2p_hours,
    avg_actual_p2p_hours,
    expected_cost_per_unit,
    cargo_unit_quantity,
    cargo_unit,
    lag(new_booking_count, 1) OVER (
        PARTITION BY temporal_scope_id, transport_mode, provider_code ORDER BY feature_date
    ) AS booking_count_lag_1d,
    lag(new_booking_count, 7) OVER (
        PARTITION BY temporal_scope_id, transport_mode, provider_code ORDER BY feature_date
    ) AS booking_count_lag_7d,
    round(avg(CAST(new_booking_count AS double)) OVER (
        PARTITION BY temporal_scope_id, transport_mode, provider_code ORDER BY feature_date
        ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING
    ), 2) AS booking_count_trailing_7d_avg,
    round(avg(sla_breach_rate_pct) OVER (
        PARTITION BY temporal_scope_id, transport_mode, provider_code ORDER BY feature_date
        ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING
    ), 2) AS sla_breach_rate_trailing_7d_avg,
    feature_date AS feature_cutoff_date,
    'multimodal_forecast_feature_daily_v1' AS feature_contract_version,
    'NO_FUTURE_DATA' AS leakage_policy,
    'SIMULATED_MULTIMODAL_V1' AS data_provenance
FROM source;

CREATE OR REPLACE VIEW {{SOURCE_DATABASE}}.vw_multimodal_outcome_label_context_v1 AS
WITH ranked AS (
    SELECT
        analytics.*,
        row_number() OVER (
            PARTITION BY temporal_scope_id, shipment_id ORDER BY metric_date DESC
        ) AS snapshot_rank
    FROM {{SOURCE_DATABASE}}.vw_multimodal_shipment_daily_context_v1 AS analytics
)
SELECT
    CAST(shipment.booking_at AS date) AS booking_cohort_date,
    latest.temporal_scope_id,
    latest.execution_mode,
    latest.time_basis,
    latest.as_of_date,
    latest.execution_scenario_id,
    latest.shipment_id,
    latest.transport_mode,
    latest.carrier AS provider_code,
    latest.route_service_id,
    latest.market_lane,
    latest.planned_p2p_hours,
    latest.actual_p2p_hours,
    IF(shipment.delivered_at IS NULL, 'PENDING', 'OBSERVED') AS outcome_status,
    IF(shipment.delivered_at IS NULL, CAST(NULL AS boolean), latest.sla_breach_flag)
        AS sla_breach_label,
    IF(shipment.delivered_at IS NULL, CAST(NULL AS boolean),
       coalesce(latest.delivery_delay_hours, 0.0) > 0.0) AS delivery_late_label,
    IF(shipment.delivered_at IS NULL, CAST(NULL AS double), latest.current_total_cost)
        AS actual_cost_label,
    IF(shipment.delivered_at IS NULL, CAST(NULL AS double),
       round(100.0 * (
           latest.current_total_cost / nullif(latest.expected_total_cost, 0.0) - 1.0
       ), 2)) AS cost_variance_pct_label,
    latest.metric_date AS label_observed_through_date,
    'SIMULATED_MULTIMODAL_V1' AS data_provenance
FROM ranked AS latest
JOIN {{SOURCE_DATABASE}}.fact_shipment_lifecycle_staging_v1 AS shipment
 ON latest.shipment_id = shipment.shipment_id
 AND latest.metric_date = try_cast(shipment.dt AS date)
 AND latest.temporal_scope_id = shipment.temporal_scope_id
WHERE latest.snapshot_rank = 1;

-- Existing names are the operational contract. Explicit simulations must use
-- the *_context_v1 views and select exactly one temporal_scope_id.
CREATE OR REPLACE VIEW {{SOURCE_DATABASE}}.vw_multimodal_shipment_daily_v1 AS
SELECT * FROM {{SOURCE_DATABASE}}.vw_multimodal_shipment_daily_context_v1
WHERE temporal_scope_id = 'OPERATIONAL'
  AND execution_mode = 'OPERATIONAL'
  AND time_basis = 'ACTUAL_CALENDAR';

CREATE OR REPLACE VIEW {{SOURCE_DATABASE}}.vw_multimodal_ops_daily_v1 AS
SELECT * FROM {{SOURCE_DATABASE}}.vw_multimodal_ops_daily_context_v1
WHERE temporal_scope_id = 'OPERATIONAL'
  AND execution_mode = 'OPERATIONAL'
  AND time_basis = 'ACTUAL_CALENDAR';

CREATE OR REPLACE VIEW {{SOURCE_DATABASE}}.vw_multimodal_provider_daily_v1 AS
SELECT * FROM {{SOURCE_DATABASE}}.vw_multimodal_provider_daily_context_v1
WHERE temporal_scope_id = 'OPERATIONAL'
  AND execution_mode = 'OPERATIONAL'
  AND time_basis = 'ACTUAL_CALENDAR';

CREATE OR REPLACE VIEW {{SOURCE_DATABASE}}.vw_multimodal_mode_decision_v1 AS
SELECT * FROM {{SOURCE_DATABASE}}.vw_multimodal_mode_decision_context_v1
WHERE temporal_scope_id = 'OPERATIONAL'
  AND execution_mode = 'OPERATIONAL'
  AND time_basis = 'ACTUAL_CALENDAR';

CREATE OR REPLACE VIEW {{SOURCE_DATABASE}}.vw_multimodal_forecast_feature_daily_v1 AS
SELECT * FROM {{SOURCE_DATABASE}}.vw_multimodal_forecast_feature_daily_context_v1
WHERE temporal_scope_id = 'OPERATIONAL'
  AND execution_mode = 'OPERATIONAL'
  AND time_basis = 'ACTUAL_CALENDAR';

CREATE OR REPLACE VIEW {{SOURCE_DATABASE}}.vw_multimodal_outcome_label_v1 AS
SELECT * FROM {{SOURCE_DATABASE}}.vw_multimodal_outcome_label_context_v1
WHERE temporal_scope_id = 'OPERATIONAL'
  AND execution_mode = 'OPERATIONAL'
  AND time_basis = 'ACTUAL_CALENDAR';
