-- Fail-closed validation for the frozen operational-calendar baseline.
-- Every returned failure_count must be zero.

WITH baseline AS (
    SELECT *
    FROM {{SOURCE_DATABASE}}.vw_multimodal_operational_baseline_v1
),
bounded_operational_source AS (
    SELECT shipment_id
    FROM {{SOURCE_DATABASE}}.vw_multimodal_shipment_daily_context_v1
    WHERE metric_date <= DATE '{{AS_OF_DATE}}'
      AND as_of_date <= DATE '{{AS_OF_DATE}}'
      AND temporal_scope_id = 'OPERATIONAL'
      AND execution_mode = 'OPERATIONAL'
      AND time_basis = 'ACTUAL_CALENDAR'
      AND execution_scenario_id IS NULL
),
expected AS (
    SELECT count(DISTINCT shipment_id) AS shipment_count
    FROM bounded_operational_source
),
checks AS (
    SELECT 'missing_baseline_output' AS check_name,
           IF((SELECT count(*) FROM baseline) = 0, 1, 0) AS failure_count
    UNION ALL
    SELECT 'missing_or_duplicate_all_dimension' AS check_name,
           IF((SELECT count(*) FROM baseline
               WHERE dimension_type = 'ALL' AND dimension_value = 'ALL') = 1, 0, 1)
    UNION ALL
    SELECT 'duplicate_dimension_key' AS check_name, count(*)
    FROM (
        SELECT dimension_type, dimension_value
        FROM baseline
        GROUP BY dimension_type, dimension_value
        HAVING count(*) > 1
    )
    UNION ALL
    SELECT 'invalid_cutoff_or_temporal_contract' AS check_name, count(*)
    FROM baseline
    WHERE baseline_as_of_date <> DATE '{{AS_OF_DATE}}'
       OR source_max_metric_date > DATE '{{AS_OF_DATE}}'
       OR temporal_scope_id <> 'OPERATIONAL'
       OR execution_mode <> 'OPERATIONAL'
       OR time_basis <> 'ACTUAL_CALENDAR'
       OR execution_scenario_id IS NOT NULL
    UNION ALL
    SELECT 'invalid_evidence_classification' AS check_name, count(*)
    FROM baseline
    WHERE real_world_evidence
       OR data_provenance <> 'SIMULATED_MULTIMODAL_V1'
       OR evidence_class <> 'SYNTHETIC_OPERATIONAL_CALENDAR_BASELINE'
       OR decision_use <> 'ENGINEERING_EVALUATION_ONLY'
    UNION ALL
    SELECT 'overall_shipment_count_does_not_reconcile' AS check_name,
           IF(
               coalesce((SELECT shipment_count FROM baseline
                         WHERE dimension_type = 'ALL' AND dimension_value = 'ALL'), -1)
                   = (SELECT shipment_count FROM expected),
               0, 1
           )
    UNION ALL
    SELECT 'mode_shipment_count_does_not_reconcile' AS check_name,
           IF(
               coalesce((SELECT sum(shipment_count) FROM baseline
                         WHERE dimension_type = 'TRANSPORT_MODE'), -1)
                   = (SELECT shipment_count FROM expected),
               0, 1
           )
    UNION ALL
    SELECT 'provider_shipment_count_does_not_reconcile' AS check_name,
           IF(
               coalesce((SELECT sum(shipment_count) FROM baseline
                         WHERE dimension_type = 'PROVIDER'), -1)
                   = (SELECT shipment_count FROM expected),
               0, 1
           )
    UNION ALL
    SELECT 'lane_shipment_count_does_not_reconcile' AS check_name,
           IF(
               coalesce((SELECT sum(shipment_count) FROM baseline
                         WHERE dimension_type = 'MARKET_LANE'), -1)
                   = (SELECT shipment_count FROM expected),
               0, 1
           )
    UNION ALL
    SELECT 'invalid_baseline_metric_range' AS check_name, count(*)
    FROM baseline
    WHERE shipment_count <= 0
       OR delivered_count < 0
       OR on_time_delivery_count < 0
       OR late_delivery_count < 0
       OR on_time_delivery_count + late_delivery_count > delivered_count
       OR on_time_delivery_rate_pct NOT BETWEEN 0.0 AND 100.0
       OR sla_breach_shipment_rate_pct NOT BETWEEN 0.0 AND 100.0
       OR signal_candidate_count < 0
       OR high_severity_signal_count < 0
       OR high_severity_signal_count > signal_candidate_count
)
SELECT check_name, failure_count
FROM checks
ORDER BY check_name;
