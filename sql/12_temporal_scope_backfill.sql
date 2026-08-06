-- One-time, idempotent classification for rows written before temporal scopes existed.
-- Review {{AS_OF_DATE}} and {{LEGACY_SCENARIO_ID}} before applying. Rows after the
-- cutoff are permanently classified as a legacy future simulation; they must never
-- age into the operational evidence set.

UPDATE {{SOURCE_DATABASE}}.fact_shipment_lifecycle_staging_v1
SET temporal_scope_id = IF(
        try_cast(dt AS date) <= DATE '{{AS_OF_DATE}}',
        'OPERATIONAL', 'SIMULATION:{{LEGACY_SCENARIO_ID}}'
    ),
    execution_mode = IF(
        try_cast(dt AS date) <= DATE '{{AS_OF_DATE}}',
        'OPERATIONAL', 'FUTURE_SIMULATION'
    ),
    time_basis = IF(
        try_cast(dt AS date) <= DATE '{{AS_OF_DATE}}',
        'ACTUAL_CALENDAR', 'FUTURE_SIMULATION'
    ),
    as_of_date = DATE '{{AS_OF_DATE}}',
    execution_scenario_id = IF(
        try_cast(dt AS date) <= DATE '{{AS_OF_DATE}}',
        NULL, '{{LEGACY_SCENARIO_ID}}'
    )
WHERE temporal_scope_id IS NULL;

UPDATE {{SOURCE_DATABASE}}.fact_shipment_lifecycle_event_staging_v1
SET temporal_scope_id = IF(
        logical_run_date <= DATE '{{AS_OF_DATE}}',
        'OPERATIONAL', 'SIMULATION:{{LEGACY_SCENARIO_ID}}'
    ),
    execution_mode = IF(
        logical_run_date <= DATE '{{AS_OF_DATE}}',
        'OPERATIONAL', 'FUTURE_SIMULATION'
    ),
    time_basis = IF(
        logical_run_date <= DATE '{{AS_OF_DATE}}',
        'ACTUAL_CALENDAR', 'FUTURE_SIMULATION'
    ),
    as_of_date = DATE '{{AS_OF_DATE}}',
    execution_scenario_id = IF(
        logical_run_date <= DATE '{{AS_OF_DATE}}',
        NULL, '{{LEGACY_SCENARIO_ID}}'
    )
WHERE temporal_scope_id IS NULL;

UPDATE {{SOURCE_DATABASE}}.fact_shipment_cost_staging_v1
SET temporal_scope_id = IF(
        try_cast(dt AS date) <= DATE '{{AS_OF_DATE}}',
        'OPERATIONAL', 'SIMULATION:{{LEGACY_SCENARIO_ID}}'
    ),
    execution_mode = IF(
        try_cast(dt AS date) <= DATE '{{AS_OF_DATE}}',
        'OPERATIONAL', 'FUTURE_SIMULATION'
    ),
    time_basis = IF(
        try_cast(dt AS date) <= DATE '{{AS_OF_DATE}}',
        'ACTUAL_CALENDAR', 'FUTURE_SIMULATION'
    ),
    as_of_date = DATE '{{AS_OF_DATE}}',
    execution_scenario_id = IF(
        try_cast(dt AS date) <= DATE '{{AS_OF_DATE}}',
        NULL, '{{LEGACY_SCENARIO_ID}}'
    )
WHERE temporal_scope_id IS NULL;

UPDATE {{SOURCE_DATABASE}}.fact_shipment_lifecycle_metrics_staging_v1
SET temporal_scope_id = IF(
        try_cast(dt AS date) <= DATE '{{AS_OF_DATE}}',
        'OPERATIONAL', 'SIMULATION:{{LEGACY_SCENARIO_ID}}'
    ),
    execution_mode = IF(
        try_cast(dt AS date) <= DATE '{{AS_OF_DATE}}',
        'OPERATIONAL', 'FUTURE_SIMULATION'
    ),
    time_basis = IF(
        try_cast(dt AS date) <= DATE '{{AS_OF_DATE}}',
        'ACTUAL_CALENDAR', 'FUTURE_SIMULATION'
    ),
    as_of_date = DATE '{{AS_OF_DATE}}',
    execution_scenario_id = IF(
        try_cast(dt AS date) <= DATE '{{AS_OF_DATE}}',
        NULL, '{{LEGACY_SCENARIO_ID}}'
    )
WHERE temporal_scope_id IS NULL;

UPDATE {{SOURCE_DATABASE}}.fact_shipment_signal_candidate_staging_v1
SET temporal_scope_id = IF(
        try_cast(dt AS date) <= DATE '{{AS_OF_DATE}}',
        'OPERATIONAL', 'SIMULATION:{{LEGACY_SCENARIO_ID}}'
    ),
    execution_mode = IF(
        try_cast(dt AS date) <= DATE '{{AS_OF_DATE}}',
        'OPERATIONAL', 'FUTURE_SIMULATION'
    ),
    time_basis = IF(
        try_cast(dt AS date) <= DATE '{{AS_OF_DATE}}',
        'ACTUAL_CALENDAR', 'FUTURE_SIMULATION'
    ),
    as_of_date = DATE '{{AS_OF_DATE}}',
    execution_scenario_id = IF(
        try_cast(dt AS date) <= DATE '{{AS_OF_DATE}}',
        NULL, '{{LEGACY_SCENARIO_ID}}'
    )
WHERE temporal_scope_id IS NULL;
