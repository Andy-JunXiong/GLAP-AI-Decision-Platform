-- Fail-closed multimodal analytics validation for one governed logical date.
-- Every returned failure_count must be zero.

WITH base AS (
    SELECT *
    FROM {{SOURCE_DATABASE}}.vw_multimodal_shipment_daily_v1
    WHERE metric_date = DATE '{{LOGICAL_RUN_DATE}}'
),
mode_rollup AS (
    SELECT *
    FROM {{SOURCE_DATABASE}}.vw_multimodal_ops_daily_v1
    WHERE metric_date = DATE '{{LOGICAL_RUN_DATE}}'
),
provider_rollup AS (
    SELECT *
    FROM {{SOURCE_DATABASE}}.vw_multimodal_provider_daily_v1
    WHERE metric_date = DATE '{{LOGICAL_RUN_DATE}}'
),
checks AS (
    SELECT 'duplicate_analytics_shipment_key' AS check_name, count(*) AS failure_count
    FROM (
        SELECT shipment_id, metric_date
        FROM base
        GROUP BY shipment_id, metric_date
        HAVING count(*) > 1
    )
    UNION ALL
    SELECT 'mode_rollup_does_not_reconcile', IF(
        coalesce((SELECT sum(shipment_snapshot_count) FROM mode_rollup), -1)
            = (SELECT count(*) FROM base), 0, 1
    )
    UNION ALL
    SELECT 'provider_rollup_does_not_reconcile', IF(
        coalesce((SELECT sum(shipment_snapshot_count) FROM provider_rollup), -1)
            = (SELECT count(*) FROM base), 0, 1
    )
    UNION ALL
    SELECT 'invalid_mode_unit_contract', count(*)
    FROM base
    WHERE transport_mode NOT IN ('AIR', 'OCEAN')
       OR cargo_unit_quantity <= 0
       OR (transport_mode = 'AIR' AND cargo_unit <> 'CHARGEABLE_KG')
       OR (transport_mode = 'OCEAN' AND cargo_unit <> 'CONTAINER')
       OR expected_cost_per_unit IS NULL
       OR expected_cost_per_unit <= 0
       OR comparison_weight_kg IS NULL
       OR comparison_weight_kg <= 0
    UNION ALL
    SELECT 'invalid_sla_rate_contract', count(*)
    FROM mode_rollup
    WHERE sla_breach_rate_pct NOT BETWEEN 0.0 AND 100.0
    UNION ALL
    SELECT 'air_decision_missing_ocean_reference', count(*)
    FROM {{SOURCE_DATABASE}}.vw_multimodal_mode_decision_v1
    WHERE metric_date = DATE '{{LOGICAL_RUN_DATE}}'
      AND transport_mode = 'AIR'
      AND comparison_status <> 'COMPARABLE'
    UNION ALL
    SELECT 'duplicate_forecast_feature_key', count(*)
    FROM (
        SELECT feature_date, transport_mode, provider_code
        FROM {{SOURCE_DATABASE}}.vw_multimodal_forecast_feature_daily_v1
        WHERE feature_date = DATE '{{LOGICAL_RUN_DATE}}'
        GROUP BY feature_date, transport_mode, provider_code
        HAVING count(*) > 1
    )
    UNION ALL
    SELECT 'invalid_outcome_label_contract', count(*)
    FROM {{SOURCE_DATABASE}}.vw_multimodal_outcome_label_v1
    WHERE label_observed_through_date <= DATE '{{LOGICAL_RUN_DATE}}'
      AND (
          outcome_status NOT IN ('PENDING', 'OBSERVED')
          OR (outcome_status = 'PENDING' AND (
              sla_breach_label IS NOT NULL OR delivery_late_label IS NOT NULL
              OR actual_cost_label IS NOT NULL OR cost_variance_pct_label IS NOT NULL
          ))
          OR (outcome_status = 'OBSERVED' AND (
              sla_breach_label IS NULL OR delivery_late_label IS NULL
              OR actual_cost_label IS NULL OR cost_variance_pct_label IS NULL
          ))
      )
)
SELECT check_name, failure_count
FROM checks
ORDER BY check_name;
