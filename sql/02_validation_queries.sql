-- Read-only checks derived from queries observed in Athena history.
SELECT *
FROM curated_iceberg.fact_ai_root_cause_v1
ORDER BY created_at DESC
LIMIT 20;

SELECT
    action_priority,
    COUNT(*) AS decision_count
FROM curated_iceberg.fact_ai_decision_explanations_v1
GROUP BY action_priority
ORDER BY decision_count DESC;

SELECT
    run_date,
    COUNT(*) AS decision_count
FROM curated_iceberg.fact_ai_decision_explanations_v1
GROUP BY run_date
ORDER BY run_date DESC
LIMIT 10;
