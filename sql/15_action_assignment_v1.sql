-- PLAN ONLY. Do not run automatically or against production.
-- Existing staging deployments need this additive migration before the
-- repository's EDIT Action contract can be enabled.

ALTER TABLE {{SOURCE_DATABASE}}.fact_lifecycle_action_audit_staging_v1
ADD COLUMNS (
    action_owner string,
    action_due_date date
);

CREATE OR REPLACE VIEW {{SOURCE_DATABASE}}.vw_lifecycle_action_current_staging_v1 AS
WITH latest_event AS (
    SELECT *, row_number() OVER (
        PARTITION BY temporal_scope_id, action_id
        ORDER BY
            occurred_at DESC,
            CASE event_type
                WHEN 'COMPLETE' THEN 4
                WHEN 'REJECT' THEN 3
                WHEN 'APPROVE' THEN 2
                WHEN 'EDIT' THEN 1
                ELSE 0
            END DESC,
            event_id DESC
    ) AS event_rank
    FROM {{SOURCE_DATABASE}}.fact_lifecycle_action_audit_staging_v1
)
SELECT
    action.action_id,
    action.alert_fingerprint,
    action.shipment_id,
    action.action_type,
    action.alert_type,
    action.alert_severity,
    action.policy_version,
    coalesce(event.new_status, action.status) AS status,
    action.approval_required,
    coalesce(event.approved_by, action.approved_by) AS approved_by,
    coalesce(event.approved_at, action.approved_at) AS approved_at,
    coalesce(event.completed_at, action.completed_at) AS completed_at,
    event.action_owner,
    event.action_due_date,
    action.provenance,
    action.created_date,
    action.temporal_scope_id,
    action.execution_mode,
    action.time_basis,
    action.as_of_date,
    action.execution_scenario_id
FROM {{SOURCE_DATABASE}}.fact_lifecycle_action_staging_v1 AS action
LEFT JOIN latest_event AS event
  ON action.temporal_scope_id = event.temporal_scope_id
 AND action.action_id = event.action_id
 AND event.event_rank = 1;
