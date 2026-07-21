-- Sanitized representative Athena SQL derived from the implemented GLAP architecture.
-- Purpose: aggregate route/carrier performance and flag statistically abnormal lanes.

WITH route_daily_metrics AS (
    SELECT
        date(event_time) AS run_date,
        concat(origin_port, '->', destination_port, ' / ', carrier) AS entity_key,
        avg(leg_duration_days) AS avg_leg_duration_days,
        avg(CASE WHEN status = 'BREACHED' THEN 1.0 ELSE 0.0 END) AS breach_rate,
        count(*) AS shipment_count
    FROM fact_shipment_events_extended_iceberg
    WHERE event_time >= date_add('day', -14, current_date)
    GROUP BY 1, 2
),
route_baselines AS (
    SELECT
        entity_key,
        avg(avg_leg_duration_days) AS baseline_duration,
        stddev_samp(avg_leg_duration_days) AS duration_stddev,
        avg(breach_rate) AS baseline_breach_rate,
        stddev_samp(breach_rate) AS breach_stddev
    FROM route_daily_metrics
    GROUP BY 1
),
scored AS (
    SELECT
        m.run_date,
        m.entity_key,
        'avg_leg_duration_days' AS metric_name,
        round(m.avg_leg_duration_days, 2) AS metric_value,
        round(b.baseline_duration, 2) AS baseline_value,
        round(
            (m.avg_leg_duration_days - b.baseline_duration) / nullif(b.duration_stddev, 0),
            2
        ) AS z_score,
        m.shipment_count
    FROM route_daily_metrics m
    JOIN route_baselines b
        ON m.entity_key = b.entity_key
    WHERE m.shipment_count >= 8
)
SELECT
    run_date,
    entity_key,
    metric_name,
    metric_value,
    baseline_value,
    z_score,
    shipment_count,
    CASE
        WHEN z_score >= 2.5 THEN 'HIGH'
        WHEN z_score >= 1.8 THEN 'MEDIUM'
        ELSE 'MONITOR'
    END AS alert_band
FROM scored
WHERE z_score IS NOT NULL
  AND z_score >= 1.8
ORDER BY z_score DESC, shipment_count DESC;
