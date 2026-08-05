-- Read-only compatibility views over isolated lifecycle staging data.
-- They match the deployed v2 input shapes without writing to current v2 tables.
-- All derived identity, allocation and risk values remain explicitly simulated.

CREATE OR REPLACE VIEW {{SOURCE_DATABASE}}.vw_lifecycle_shipment_v2_compat AS
SELECT
    shipment_id,
    route_service_id AS route_id,
    carrier,
    'OCEAN' AS ship_mode,
    origin_port,
    destination_port,
    etd AS estimate_departure_time,
    atd AS actual_departure_time,
    eta AS estimate_arrival_time,
    ata AS actual_arrival_time,
    CASE
        WHEN ata IS NULL OR discharged_at IS NULL THEN CAST(NULL AS double)
        ELSE greatest(0.0, date_diff('minute', ata, discharged_at) / 60.0)
    END AS customs_clearance_time,
    delivery_target_at AS estimate_delivery_date,
    delivered_at AS actual_delivery_date,
    'SIMULATED_LIFECYCLE_V1' AS data_source,
    equipment_type AS ocean_shipment_type,
    journey_exception_type AS customs_exception_type,
    dt
FROM {{SOURCE_DATABASE}}.fact_shipment_lifecycle_staging_v1;

CREATE OR REPLACE VIEW {{SOURCE_DATABASE}}.vw_lifecycle_shipment_event_v2_compat AS
SELECT
    shipment_id,
    CASE
        WHEN event_type IN ('BOOKED', 'GATE_IN') THEN 1
        WHEN event_type IN ('DEPARTED', 'ARRIVED') THEN 2
        ELSE 3
    END AS leg_seq,
    event_type,
    CAST(event_time AS varchar) AS event_ts,
    location AS location_code,
    'SIMULATED' AS event_source_flag,
    CAST(logical_run_date AS varchar) AS dt
FROM {{SOURCE_DATABASE}}.fact_shipment_lifecycle_event_staging_v1;

CREATE OR REPLACE VIEW {{SOURCE_DATABASE}}.vw_lifecycle_leg_metrics_v2_compat AS
SELECT
    metric.shipment_id,
    2 AS leg_seq,
    coalesce(metric.actual_p2p_hours, metric.planned_p2p_hours) / 24.0
        AS leg_duration_days,
    IF(metric.sla_breach_flag, 1, 0) AS leg_breach_flag,
    CASE
        WHEN greatest(
            coalesce(metric.departure_delay_hours, 0.0),
            coalesce(metric.arrival_delay_hours, 0.0),
            coalesce(metric.delivery_delay_hours, 0.0)
        ) >= 72.0 THEN 'CRITICAL'
        WHEN greatest(
            coalesce(metric.departure_delay_hours, 0.0),
            coalesce(metric.arrival_delay_hours, 0.0),
            coalesce(metric.delivery_delay_hours, 0.0)
        ) >= 24.0 THEN 'HIGH'
        WHEN metric.sla_breach_flag THEN 'MEDIUM'
        ELSE 'LOW'
    END AS severity_level,
    shipment.route_service_id AS route_id,
    shipment.carrier,
    'OCEAN' AS ship_mode,
    shipment.origin_port,
    shipment.destination_port,
    try_cast(metric.dt AS date) AS run_date,
    metric.dt
FROM {{SOURCE_DATABASE}}.fact_shipment_lifecycle_metrics_staging_v1 AS metric
JOIN {{SOURCE_DATABASE}}.fact_shipment_lifecycle_staging_v1 AS shipment
  ON metric.shipment_id = shipment.shipment_id
 AND metric.dt = shipment.dt;

CREATE OR REPLACE VIEW {{SOURCE_DATABASE}}.vw_lifecycle_cost_v2_compat AS
SELECT
    shipment_id,
    route_service_id AS route_id,
    carrier,
    'OCEAN' AS ship_mode,
    CAST(container_count * 24000.0 AS double) AS chargeable_weight,
    CAST(container_count * 67.7 AS double) AS chargeable_volume,
    container_count,
    CAST(expected_total_cost AS double) AS transport_cost,
    CAST(0.0 AS double) AS customs_cost,
    CAST(greatest(
        coalesce(actual_total_cost, accrued_total_cost, expected_total_cost)
            - expected_total_cost,
        DECIMAL '0.00'
    ) AS double) AS handling_cost,
    CAST(coalesce(actual_total_cost, accrued_total_cost, expected_total_cost) AS double)
        AS total_cost,
    CAST(
        coalesce(actual_total_cost, accrued_total_cost, expected_total_cost)
            / nullif(container_count, 0)
        AS double
    ) AS cost_per_unit,
    dt
FROM {{SOURCE_DATABASE}}.fact_shipment_lifecycle_staging_v1;

CREATE OR REPLACE VIEW {{SOURCE_DATABASE}}.vw_lifecycle_risk_v2_compat AS
SELECT
    shipment.shipment_id,
    least(1.0, greatest(
        coalesce(metric.departure_delay_hours, 0.0),
        coalesce(metric.arrival_delay_hours, 0.0),
        coalesce(metric.delivery_delay_hours, 0.0)
    ) / 96.0) AS delay_risk_score,
    IF(shipment.journey_exception_type IS NULL, 0.02, 0.08) AS damage_risk_score,
    IF(shipment.journey_exception_type IS NULL, 0.01, 0.06)
        AS compliance_risk_score,
    greatest(
        least(1.0, greatest(
            coalesce(metric.departure_delay_hours, 0.0),
            coalesce(metric.arrival_delay_hours, 0.0),
            coalesce(metric.delivery_delay_hours, 0.0)
        ) / 96.0),
        IF(shipment.journey_exception_type IS NULL, 0.02, 0.08),
        IF(shipment.journey_exception_type IS NULL, 0.01, 0.06)
    ) AS overall_risk_score,
    try_cast(shipment.dt AS date) AS risk_dt,
    shipment.dt
FROM {{SOURCE_DATABASE}}.fact_shipment_lifecycle_staging_v1 AS shipment
JOIN {{SOURCE_DATABASE}}.fact_shipment_lifecycle_metrics_staging_v1 AS metric
  ON shipment.shipment_id = metric.shipment_id
 AND shipment.dt = metric.dt;

CREATE OR REPLACE VIEW {{SOURCE_DATABASE}}.vw_lifecycle_product_allocation_v2_compat AS
SELECT
    shipment_id,
    concat('SIM-PRODUCT-', substr(to_hex(md5(to_utf8(shipment_id))), 1, 8))
        AS product_id,
    container_count * 100 AS unit_qty,
    CAST(container_count * 24000.0 AS double) AS allocated_weight,
    dt
FROM {{SOURCE_DATABASE}}.fact_shipment_lifecycle_staging_v1;
