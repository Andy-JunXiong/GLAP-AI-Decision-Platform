-- Query embedded in the deployed glap-ai-agent-orchestrator Lambda and
-- observed successfully in Athena query history on 2026-07-21.
SELECT
    run_date,
    entity_key,
    metric_name,
    metric_value,
    baseline_value,
    z_score
FROM curated_iceberg.fact_ai_anomaly_scores_v1
ORDER BY abs(z_score) DESC
LIMIT 10;

-- The deployed Lambda performs parameterized duplicate checks and INSERTs for
-- each selected record. See lambda/glap_ai_agent_orchestrator.py for the exact
-- executed SQL templates and escaping logic.
