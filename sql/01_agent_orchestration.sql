-- Query used by the glap-ai-agent-orchestrator Lambda. The original form was
-- observed successfully in Athena query history on 2026-07-21; this revised
-- form selects only anomaly rows that do not yet have a decision.
SELECT
    anomaly.run_date,
    anomaly.entity_key,
    anomaly.metric_name,
    anomaly.metric_value,
    anomaly.baseline_value,
    anomaly.z_score
FROM curated_iceberg.fact_ai_anomaly_scores_v1 AS anomaly
WHERE anomaly.anomaly_flag = 1
  AND NOT EXISTS (
      SELECT 1
      FROM curated_iceberg.fact_ai_decision_explanations_v1 AS decision
      WHERE decision.run_date = anomaly.run_date
        AND decision.entity_key = anomaly.entity_key
        AND decision.metric_name = anomaly.metric_name
  )
ORDER BY anomaly.run_date DESC, abs(anomaly.z_score) DESC
LIMIT 10;

-- The orchestrator still performs duplicate checks before each INSERT as a
-- defensive control. Existing root-cause rows are loaded so a failed decision
-- insert can be resumed on the next invocation.
