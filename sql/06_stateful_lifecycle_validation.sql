-- Stateful lifecycle staging validation. Replace {{SOURCE_DATABASE}} and
-- {{LOGICAL_RUN_DATE}} before execution. Every returned count must be zero.

WITH current_snapshot AS (
    SELECT *
    FROM {{SOURCE_DATABASE}}.fact_shipment_lifecycle_staging_v1
    WHERE try_cast(dt AS date) = DATE '{{LOGICAL_RUN_DATE}}'
      AND temporal_scope_id = '{{TEMPORAL_SCOPE_ID}}'
),
previous_snapshot AS (
    SELECT *
    FROM {{SOURCE_DATABASE}}.fact_shipment_lifecycle_staging_v1
    WHERE try_cast(dt AS date) = date_add('day', -1, DATE '{{LOGICAL_RUN_DATE}}')
      AND temporal_scope_id = '{{TEMPORAL_SCOPE_ID}}'
),
current_metrics AS (
    SELECT *
    FROM {{SOURCE_DATABASE}}.fact_shipment_lifecycle_metrics_staging_v1
    WHERE try_cast(dt AS date) = DATE '{{LOGICAL_RUN_DATE}}'
      AND temporal_scope_id = '{{TEMPORAL_SCOPE_ID}}'
),
current_signals AS (
    SELECT *
    FROM {{SOURCE_DATABASE}}.fact_shipment_signal_candidate_staging_v1
    WHERE try_cast(dt AS date) = DATE '{{LOGICAL_RUN_DATE}}'
      AND temporal_scope_id = '{{TEMPORAL_SCOPE_ID}}'
),
current_alerts AS (
    SELECT * FROM {{SOURCE_DATABASE}}.fact_lifecycle_alert_staging_v1
    WHERE try_cast(dt AS date) = DATE '{{LOGICAL_RUN_DATE}}'
      AND temporal_scope_id = '{{TEMPORAL_SCOPE_ID}}'
),
current_outcomes AS (
    SELECT * FROM {{SOURCE_DATABASE}}.fact_lifecycle_outcome_staging_v1
    WHERE try_cast(dt AS date) = DATE '{{LOGICAL_RUN_DATE}}'
      AND temporal_scope_id = '{{TEMPORAL_SCOPE_ID}}'
),
booking_cohort AS (
    SELECT DISTINCT shipment_id, carrier, coalesce(transport_mode, 'OCEAN') AS transport_mode
    FROM {{SOURCE_DATABASE}}.fact_shipment_lifecycle_staging_v1
    WHERE try_cast(dt AS date) BETWEEN date_add('day', -27, DATE '{{LOGICAL_RUN_DATE}}')
                                   AND DATE '{{LOGICAL_RUN_DATE}}'
      AND temporal_scope_id = '{{TEMPORAL_SCOPE_ID}}'
      AND CAST(booking_at AS date) BETWEEN DATE '2026-09-02' AND DATE '{{LOGICAL_RUN_DATE}}'
),
temporal_rows AS (
    SELECT temporal_scope_id, execution_mode, time_basis, as_of_date,
           execution_scenario_id
    FROM {{SOURCE_DATABASE}}.fact_shipment_lifecycle_staging_v1
    WHERE try_cast(dt AS date) = DATE '{{LOGICAL_RUN_DATE}}'
      AND temporal_scope_id = '{{TEMPORAL_SCOPE_ID}}'
    UNION ALL
    SELECT temporal_scope_id, execution_mode, time_basis, as_of_date,
           execution_scenario_id
    FROM {{SOURCE_DATABASE}}.fact_shipment_lifecycle_event_staging_v1
    WHERE logical_run_date = DATE '{{LOGICAL_RUN_DATE}}'
      AND temporal_scope_id = '{{TEMPORAL_SCOPE_ID}}'
    UNION ALL
    SELECT temporal_scope_id, execution_mode, time_basis, as_of_date,
           execution_scenario_id
    FROM {{SOURCE_DATABASE}}.fact_shipment_cost_staging_v1
    WHERE try_cast(dt AS date) = DATE '{{LOGICAL_RUN_DATE}}'
      AND temporal_scope_id = '{{TEMPORAL_SCOPE_ID}}'
    UNION ALL
    SELECT temporal_scope_id, execution_mode, time_basis, as_of_date,
           execution_scenario_id
    FROM {{SOURCE_DATABASE}}.fact_shipment_lifecycle_metrics_staging_v1
    WHERE try_cast(dt AS date) = DATE '{{LOGICAL_RUN_DATE}}'
      AND temporal_scope_id = '{{TEMPORAL_SCOPE_ID}}'
    UNION ALL
    SELECT temporal_scope_id, execution_mode, time_basis, as_of_date,
           execution_scenario_id
    FROM {{SOURCE_DATABASE}}.fact_shipment_signal_candidate_staging_v1
    WHERE try_cast(dt AS date) = DATE '{{LOGICAL_RUN_DATE}}'
      AND temporal_scope_id = '{{TEMPORAL_SCOPE_ID}}'
    UNION ALL
    SELECT temporal_scope_id, execution_mode, time_basis, as_of_date,
           execution_scenario_id
    FROM {{SOURCE_DATABASE}}.fact_lifecycle_alert_staging_v1
    WHERE try_cast(dt AS date) = DATE '{{LOGICAL_RUN_DATE}}'
      AND temporal_scope_id = '{{TEMPORAL_SCOPE_ID}}'
    UNION ALL
    SELECT temporal_scope_id, execution_mode, time_basis, as_of_date,
           execution_scenario_id
    FROM {{SOURCE_DATABASE}}.fact_lifecycle_action_staging_v1
    WHERE created_date = DATE '{{LOGICAL_RUN_DATE}}'
      AND temporal_scope_id = '{{TEMPORAL_SCOPE_ID}}'
    UNION ALL
    SELECT temporal_scope_id, execution_mode, time_basis, as_of_date,
           execution_scenario_id
    FROM {{SOURCE_DATABASE}}.fact_lifecycle_outcome_staging_v1
    WHERE try_cast(dt AS date) = DATE '{{LOGICAL_RUN_DATE}}'
      AND temporal_scope_id = '{{TEMPORAL_SCOPE_ID}}'
    UNION ALL
    SELECT temporal_scope_id, execution_mode, time_basis, as_of_date,
           execution_scenario_id
    FROM {{SOURCE_DATABASE}}.fact_policy_proposal_staging_v1
    WHERE created_date = DATE '{{LOGICAL_RUN_DATE}}'
      AND temporal_scope_id = '{{TEMPORAL_SCOPE_ID}}'
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
       OR (coalesce(destination_release_at, discharged_at) IS NOT NULL AND ata IS NULL)
       OR (coalesce(destination_release_at, discharged_at) IS NOT NULL
           AND coalesce(destination_release_at, discharged_at) < ata)
       OR (delivered_at IS NOT NULL
           AND coalesce(destination_release_at, discharged_at) IS NULL)
       OR (delivered_at IS NOT NULL
           AND delivered_at < coalesce(destination_release_at, discharged_at))
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
       OR (coalesce(previous.destination_release_at, previous.discharged_at) IS NOT NULL
           AND coalesce(current.destination_release_at, current.discharged_at)
               <> coalesce(previous.destination_release_at, previous.discharged_at))
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
          AND temporal_scope_id = '{{TEMPORAL_SCOPE_ID}}'
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
       OR origin_performance NOT IN ('NOT_APPLICABLE', 'PENDING', 'ON_TIME', 'LATE', 'OVERDUE')
       OR destination_release_performance NOT IN ('NOT_APPLICABLE', 'PENDING', 'ON_TIME', 'LATE', 'OVERDUE')
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
    UNION ALL
    SELECT 'duplicate_alert_key', count(*)
    FROM (
        SELECT alert_fingerprint, dt FROM current_alerts
        GROUP BY alert_fingerprint, dt HAVING count(*) > 1
    )
    UNION ALL
    SELECT 'invalid_alert_contract', count(*)
    FROM current_alerts
    WHERE alert_type NOT IN ('SLA_BREACH', 'COST_ANOMALY')
       OR status NOT IN ('OPEN', 'RESOLVED')
       OR provenance <> 'SIMULATED'
       OR first_detected_date > last_detected_date
       OR (status = 'RESOLVED' AND resolved_date IS NULL)
    UNION ALL
    SELECT 'invalid_action_contract', count(*)
    FROM {{SOURCE_DATABASE}}.fact_lifecycle_action_staging_v1
    WHERE temporal_scope_id = '{{TEMPORAL_SCOPE_ID}}'
      AND (status NOT IN ('PROPOSED', 'APPROVED', 'COMPLETED', 'OVERDUE')
       OR approval_required <> true
       OR provenance <> 'SIMULATED'
       OR (status IN ('APPROVED', 'COMPLETED') AND approved_by IS NULL)
       OR (status = 'COMPLETED' AND completed_at IS NULL))
    UNION ALL
    SELECT 'duplicate_outcome_key', count(*)
    FROM (
        SELECT outcome_id, dt FROM current_outcomes
        GROUP BY outcome_id, dt HAVING count(*) > 1
    )
    UNION ALL
    SELECT 'invalid_outcome_contract', count(*)
    FROM current_outcomes
    WHERE status NOT IN ('PENDING', 'SUCCESSFUL', 'PARTIALLY_SUCCESSFUL', 'FAILED', 'INCONCLUSIVE')
       OR provenance <> 'SIMULATED'
       OR (status = 'PENDING' AND (observed_date IS NOT NULL OR effect_pct IS NOT NULL))
       OR (status <> 'PENDING' AND observed_date IS NULL)
    UNION ALL
    SELECT 'invalid_policy_proposal_contract', count(*)
    FROM {{SOURCE_DATABASE}}.fact_policy_proposal_staging_v1
    WHERE temporal_scope_id = '{{TEMPORAL_SCOPE_ID}}'
      AND (status NOT IN ('PENDING_HUMAN_REVIEW', 'APPROVED', 'REJECTED')
       OR simulation_config_change <> false
       OR rollback_policy_version IS NULL
       OR provenance <> 'SIMULATED_LEARNING_EVIDENCE'
       OR (status = 'PENDING_HUMAN_REVIEW'
           AND (approved_by IS NOT NULL OR effective_date IS NOT NULL)))
    UNION ALL
    SELECT 'invalid_transport_contract', count(*)
    FROM current_snapshot AS shipment
    LEFT JOIN {{SOURCE_DATABASE}}.dim_provider_v1 AS provider
      ON shipment.carrier = provider.provider_code AND provider.status = 'ACTIVE'
    WHERE provider.provider_code IS NULL
       OR coalesce(shipment.transport_mode, 'OCEAN') NOT IN ('OCEAN', 'AIR')
       OR coalesce(shipment.transport_mode, 'OCEAN') <> provider.supported_mode
       OR (shipment.carrier = 'DHL' AND shipment.transport_mode <> 'AIR')
       OR (shipment.carrier IN ('MAERSK', 'KN')
           AND coalesce(shipment.transport_mode, 'OCEAN') <> 'OCEAN')
       OR (shipment.transport_mode = 'AIR' AND (
            shipment.container_count <> 0 OR shipment.chargeable_weight_kg <= 0
            OR shipment.origin_location_type <> 'AIRPORT'
            OR shipment.destination_location_type <> 'AIRPORT'
       ))
       OR (coalesce(shipment.transport_mode, 'OCEAN') = 'OCEAN' AND (
            shipment.container_count <= 0 OR shipment.origin_location_type <> 'PORT'
            OR shipment.destination_location_type <> 'PORT'
       ))
    UNION ALL
    SELECT 'missing_provider_coverage',
           IF(count(DISTINCT carrier) = 3
              AND count_if(carrier = 'MAERSK') > 0
              AND count_if(carrier = 'KN') > 0
              AND count_if(carrier = 'DHL') > 0, 0, 1)
    FROM current_snapshot
    WHERE CAST(booking_at AS date) = DATE '{{LOGICAL_RUN_DATE}}'
    UNION ALL
    SELECT 'air_booking_share_out_of_range',
           IF(count(*) < 70, 0,
              IF(100.0 * count_if(transport_mode = 'AIR') / count(*) BETWEEN 15.0 AND 20.0,
                 0, 1))
    FROM booking_cohort
    UNION ALL
    SELECT 'invalid_temporal_provenance', count(*)
    FROM temporal_rows
    WHERE as_of_date IS NULL
       OR execution_mode NOT IN ('OPERATIONAL', 'FUTURE_SIMULATION')
       OR time_basis <> IF(
            execution_mode = 'OPERATIONAL', 'ACTUAL_CALENDAR', 'FUTURE_SIMULATION'
       )
       OR temporal_scope_id <> IF(
            execution_mode = 'OPERATIONAL',
            'OPERATIONAL', concat('SIMULATION:', execution_scenario_id)
       )
       OR (execution_mode = 'OPERATIONAL' AND execution_scenario_id IS NOT NULL)
       OR (execution_mode = 'FUTURE_SIMULATION' AND execution_scenario_id IS NULL)
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
    SELECT transport_mode, origin_port, destination_port, carrier, service_code, equipment_type,
           charge_code, effective_from, count(*) AS row_count
    FROM {{SOURCE_DATABASE}}.dim_rate_card_v1
    WHERE status = 'ACTIVE'
    GROUP BY transport_mode, origin_port, destination_port, carrier, service_code, equipment_type,
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
