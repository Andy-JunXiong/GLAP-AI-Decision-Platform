-- Stateful lifecycle staging validation. Replace {{SOURCE_DATABASE}} and
-- {{LOGICAL_RUN_DATE}} before execution. Every returned count must be zero.

WITH current_snapshot AS (
    SELECT *
    FROM {{SOURCE_DATABASE}}.fact_shipment_lifecycle_staging_v1
    WHERE try_cast(dt AS date) = DATE '{{LOGICAL_RUN_DATE}}'
),
previous_snapshot AS (
    SELECT *
    FROM {{SOURCE_DATABASE}}.fact_shipment_lifecycle_staging_v1
    WHERE try_cast(dt AS date) = date_add('day', -1, DATE '{{LOGICAL_RUN_DATE}}')
),
current_metrics AS (
    SELECT *
    FROM {{SOURCE_DATABASE}}.fact_shipment_lifecycle_metrics_staging_v1
    WHERE try_cast(dt AS date) = DATE '{{LOGICAL_RUN_DATE}}'
),
current_signals AS (
    SELECT *
    FROM {{SOURCE_DATABASE}}.fact_shipment_signal_candidate_staging_v1
    WHERE try_cast(dt AS date) = DATE '{{LOGICAL_RUN_DATE}}'
),
checks AS (
    SELECT 'duplicate_snapshot_key' AS check_name, count(*) AS failure_count
    FROM (
        SELECT shipment_id, dt
        FROM current_snapshot
        GROUP BY shipment_id, dt
        HAVING count(*) > 1
    )
    UNION ALL
    SELECT 'invalid_milestone_order', count(*)
    FROM current_snapshot
    WHERE (atd IS NOT NULL AND atd < booking_at)
       OR (ata IS NOT NULL AND atd IS NULL)
       OR (ata IS NOT NULL AND ata < atd)
       OR (discharged_at IS NOT NULL AND ata IS NULL)
       OR (discharged_at IS NOT NULL AND discharged_at < ata)
       OR (delivered_at IS NOT NULL AND discharged_at IS NULL)
       OR (delivered_at IS NOT NULL AND delivered_at < discharged_at)
    UNION ALL
    SELECT 'p2p_commitment_mutated', count(*)
    FROM current_snapshot AS current
    JOIN previous_snapshot AS previous USING (shipment_id)
    WHERE current.etd <> previous.etd OR current.eta <> previous.eta
    UNION ALL
    SELECT 'actual_milestone_mutated', count(*)
    FROM current_snapshot AS current
    JOIN previous_snapshot AS previous USING (shipment_id)
    WHERE (previous.atd IS NOT NULL AND current.atd <> previous.atd)
       OR (previous.ata IS NOT NULL AND current.ata <> previous.ata)
       OR (previous.discharged_at IS NOT NULL AND current.discharged_at <> previous.discharged_at)
       OR (previous.delivered_at IS NOT NULL AND current.delivered_at <> previous.delivered_at)
    UNION ALL
    SELECT 'invalid_terminal_state', count(*)
    FROM current_snapshot
    WHERE terminal_state <> (lifecycle_stage = 'DELIVERED')
       OR lifecycle_status <> IF(lifecycle_stage = 'DELIVERED', 'CLOSED', 'OPEN')
    UNION ALL
    SELECT 'unknown_route_version', count(*)
    FROM current_snapshot AS shipment
    LEFT JOIN {{SOURCE_DATABASE}}.dim_route_service_v1 AS route
      ON shipment.route_service_id = route.route_service_id
     AND shipment.route_config_version = route.config_version
    WHERE route.route_service_id IS NULL
    UNION ALL
    SELECT 'unknown_rate_version', count(*)
    FROM current_snapshot AS shipment
    LEFT JOIN (
        SELECT DISTINCT config_version
        FROM {{SOURCE_DATABASE}}.dim_rate_card_v1
    ) AS rate ON shipment.rate_card_version = rate.config_version
    WHERE rate.config_version IS NULL
    UNION ALL
    SELECT 'cost_detail_does_not_reconcile', count(*)
    FROM current_snapshot AS shipment
    LEFT JOIN (
        SELECT shipment_id, round(sum(amount), 2) AS expected_cost
        FROM {{SOURCE_DATABASE}}.fact_shipment_cost_staging_v1
        WHERE cost_status = 'EXPECTED'
        GROUP BY shipment_id
    ) AS cost USING (shipment_id)
    WHERE shipment.expected_total_cost IS NOT NULL
      AND coalesce(cost.expected_cost, -1) <> shipment.expected_total_cost
    UNION ALL
    SELECT 'duplicate_metric_key', count(*)
    FROM (
        SELECT shipment_id, dt
        FROM current_metrics
        GROUP BY shipment_id, dt
        HAVING count(*) > 1
    )
    UNION ALL
    SELECT 'metric_snapshot_mismatch', count(*)
    FROM current_snapshot AS shipment
    FULL OUTER JOIN current_metrics AS metric
      ON shipment.shipment_id = metric.shipment_id AND shipment.dt = metric.dt
    WHERE shipment.shipment_id IS NULL OR metric.shipment_id IS NULL
    UNION ALL
    SELECT 'invalid_metric_contract', count(*)
    FROM current_metrics
    WHERE lifecycle_status NOT IN ('OPEN', 'CLOSED')
       OR gate_in_performance NOT IN ('NOT_APPLICABLE', 'PENDING', 'ON_TIME', 'LATE', 'OVERDUE')
       OR departure_performance NOT IN ('NOT_APPLICABLE', 'PENDING', 'ON_TIME', 'LATE', 'OVERDUE')
       OR arrival_performance NOT IN ('NOT_APPLICABLE', 'PENDING', 'ON_TIME', 'LATE', 'OVERDUE')
       OR discharge_performance NOT IN ('NOT_APPLICABLE', 'PENDING', 'ON_TIME', 'LATE', 'OVERDUE')
       OR delivery_performance NOT IN ('NOT_APPLICABLE', 'PENDING', 'ON_TIME', 'LATE', 'OVERDUE')
    UNION ALL
    SELECT 'duplicate_signal_key', count(*)
    FROM (
        SELECT signal_fingerprint, dt
        FROM current_signals
        GROUP BY signal_fingerprint, dt
        HAVING count(*) > 1
    )
    UNION ALL
    SELECT 'invalid_signal_contract', count(*)
    FROM current_signals
    WHERE signal_type NOT IN ('SLA_BREACH', 'COST_ANOMALY')
       OR severity NOT IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')
       OR candidate_status NOT IN ('ACTIVE', 'RESOLVED')
       OR simulation_provenance <> 'SIMULATED'
)
SELECT check_name, failure_count
FROM checks
ORDER BY check_name;

-- Configuration checks. Every returned count must be zero.
WITH route_duplicates AS (
    SELECT route_service_id, config_version
    FROM {{SOURCE_DATABASE}}.dim_route_service_v1
    WHERE status = 'ACTIVE'
    GROUP BY route_service_id, config_version
    HAVING count(*) > 1
),
rate_ambiguity AS (
    SELECT origin_port, destination_port, carrier, service_code, equipment_type,
           charge_code, effective_from, count(*) AS row_count
    FROM {{SOURCE_DATABASE}}.dim_rate_card_v1
    WHERE status = 'ACTIVE'
    GROUP BY origin_port, destination_port, carrier, service_code, equipment_type,
             charge_code, effective_from
    HAVING count(*) > 1
),
tier_order AS (
    SELECT *, lag(to_day) OVER (
        PARTITION BY port_code, carrier, equipment_type, charge_code, config_version
        ORDER BY from_day
    ) AS prior_to_day
    FROM {{SOURCE_DATABASE}}.dim_rate_tier_v1
    WHERE status = 'ACTIVE'
)
SELECT 'duplicate_route_config' AS check_name, count(*) AS failure_count FROM route_duplicates
UNION ALL
SELECT 'ambiguous_rate_card', count(*) FROM rate_ambiguity
UNION ALL
SELECT 'invalid_rate_tier', count(*) FROM tier_order
WHERE from_day <= 0 OR (to_day IS NOT NULL AND to_day < from_day)
   OR (prior_to_day IS NOT NULL AND from_day <> prior_to_day + 1);
