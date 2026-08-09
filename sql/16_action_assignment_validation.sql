-- Read-only post-migration validation. It must fail closed if the additive
-- columns or view fields do not exist. It is not wired to an automatic job.

WITH audit_columns AS (
    SELECT column_name
    FROM information_schema.columns
    WHERE table_schema = '{{SOURCE_DATABASE}}'
      AND table_name = 'fact_lifecycle_action_audit_staging_v1'
      AND column_name IN ('action_owner', 'action_due_date')
),
view_columns AS (
    SELECT column_name
    FROM information_schema.columns
    WHERE table_schema = '{{SOURCE_DATABASE}}'
      AND table_name = 'vw_lifecycle_action_current_staging_v1'
      AND column_name IN ('action_owner', 'action_due_date')
),
checks AS (
    SELECT 'missing_action_audit_assignment_columns' AS check_name,
           greatest(2 - count(*), 0) AS failure_count
    FROM audit_columns
    UNION ALL
    SELECT 'missing_action_current_assignment_columns',
           greatest(2 - count(*), 0)
    FROM view_columns
    UNION ALL
    SELECT 'invalid_action_edit_event', count(*)
    FROM {{SOURCE_DATABASE}}.fact_lifecycle_action_audit_staging_v1
    WHERE event_type = 'EDIT'
      AND (
        previous_status <> 'PROPOSED' OR new_status <> 'EDITED'
        OR action_owner IS NULL OR trim(action_owner) = ''
        OR action_due_date IS NULL OR action_due_date < as_of_date
      )
    UNION ALL
    SELECT 'missing_assignment_on_edited_followup', count(*)
    FROM {{SOURCE_DATABASE}}.fact_lifecycle_action_audit_staging_v1
    WHERE previous_status = 'EDITED'
      AND event_type IN ('APPROVE', 'REJECT')
      AND (action_owner IS NULL OR action_due_date IS NULL)
    UNION ALL
    SELECT 'invalid_current_edited_action', count(*)
    FROM {{SOURCE_DATABASE}}.vw_lifecycle_action_current_staging_v1
    WHERE status = 'EDITED'
      AND (action_owner IS NULL OR trim(action_owner) = '' OR action_due_date IS NULL)
)
SELECT check_name, failure_count
FROM checks
ORDER BY check_name;
