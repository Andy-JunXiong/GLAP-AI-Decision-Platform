-- Read-only post-migration validation for Decision-to-Action binding v1.
-- Every returned failure_count must be zero before any producer or reader
-- package is released. The query emits aggregate checks only.

WITH action_columns AS (
    SELECT column_name
    FROM information_schema.columns
    WHERE table_schema = '{{SOURCE_DATABASE}}'
      AND table_name = 'fact_lifecycle_action_staging_v1'
      AND column_name IN (
          'decision_brief_version',
          'selected_alternative',
          'selection_rationale'
      )
),
view_columns AS (
    SELECT column_name
    FROM information_schema.columns
    WHERE table_schema = '{{SOURCE_DATABASE}}'
      AND table_name = 'vw_lifecycle_action_current_staging_v1'
      AND column_name IN (
          'decision_brief_version',
          'selected_alternative',
          'selection_rationale'
      )
),
checks AS (
    SELECT 'missing_action_binding_columns' AS check_name,
           greatest(CAST(3 AS bigint) - count(*), CAST(0 AS bigint)) AS failure_count
    FROM action_columns
    UNION ALL
    SELECT 'missing_action_current_binding_columns',
           greatest(CAST(3 AS bigint) - count(*), CAST(0 AS bigint))
    FROM view_columns
    UNION ALL
    SELECT 'partial_action_binding', count(*)
    FROM {{SOURCE_DATABASE}}.fact_lifecycle_action_staging_v1
    WHERE (
        CASE WHEN decision_brief_version IS NULL THEN 0 ELSE 1 END
        + CASE WHEN selected_alternative IS NULL THEN 0 ELSE 1 END
        + CASE WHEN selection_rationale IS NULL THEN 0 ELSE 1 END
    ) BETWEEN 1 AND 2
    UNION ALL
    SELECT 'invalid_decision_brief_v1_binding', count(*)
    FROM {{SOURCE_DATABASE}}.fact_lifecycle_action_staging_v1
    WHERE decision_brief_version IS NOT NULL
      AND (
          decision_brief_version <> 'decision-brief.v1'
          OR trim(selection_rationale) = ''
          OR NOT (
              (
                  alert_type = 'SLA_BREACH'
                  AND action_type = 'EXPEDITE_MILESTONE'
                  AND selected_alternative = 'EXPEDITE_MILESTONE'
              )
              OR (
                  alert_type = 'COST_ANOMALY'
                  AND action_type = 'REVIEW_COST'
                  AND selected_alternative = 'REVIEW_COST'
              )
          )
      )
    UNION ALL
    SELECT 'invalid_cost_decision_brief_v1_binding', count(*)
    FROM {{SOURCE_DATABASE}}.fact_lifecycle_action_staging_v1
    WHERE alert_type = 'COST_ANOMALY'
      AND decision_brief_version IS NOT NULL
      AND (
          decision_brief_version <> 'decision-brief.v1'
          OR action_type <> 'REVIEW_COST'
          OR selected_alternative <> 'REVIEW_COST'
          OR trim(selection_rationale) = ''
      )
    UNION ALL
    SELECT 'current_view_binding_mismatch', count(*)
    FROM {{SOURCE_DATABASE}}.fact_lifecycle_action_staging_v1 AS action
    JOIN {{SOURCE_DATABASE}}.vw_lifecycle_action_current_staging_v1 AS current
      ON action.temporal_scope_id = current.temporal_scope_id
     AND action.action_id = current.action_id
    WHERE coalesce(action.decision_brief_version, '')
              <> coalesce(current.decision_brief_version, '')
       OR coalesce(action.selected_alternative, '')
              <> coalesce(current.selected_alternative, '')
       OR coalesce(action.selection_rationale, '')
              <> coalesce(current.selection_rationale, '')
)
SELECT check_name, failure_count
FROM checks
ORDER BY check_name;
