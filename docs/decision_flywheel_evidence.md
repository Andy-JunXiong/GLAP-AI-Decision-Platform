# Decision Flywheel Evidence

This artifact documents one sanitized example of the closed-loop behavior the GLAP architecture is designed to support.

## Synthetic Example: Port-to-Port Delay Escalation

| Step | Example evidence | Stored or executed in AWS |
| --- | --- | --- |
| Anomaly | Route `DEHAM->AUSYD / MAERSK` shows `avg_leg_duration_days = 35.4` vs baseline `27.8` | Athena over Iceberg table |
| Detection | Z-score breaches threshold and a row is written to `fact_ai_anomaly_scores_v1` | Athena + S3 + Glue |
| Decision | Rule engine maps the anomaly to `Investigate carrier transit delay` with `HIGH` priority | Lambda decision step |
| Action | Team notifies carrier manager and reviews impacted shipments | Operational step outside system |
| Outcome | Next-day output shows transit duration improving and no new SLA breach escalation | Athena output table + dashboard |
| Learning | Outcome tag is retained for future rule tuning or prompt refinement | Future policy or model update |

## Why This Matters

A reviewer can see that GLAP is trying to prove a practical loop:

1. the system detects a concrete logistics issue
2. the system produces an actionable recommendation
3. the output is written back into AWS-managed analytical artifacts
4. the outcome can inform later decision quality

## Replacement Guidance

If stronger evidence becomes available, replace this file with:

- a real Athena result export
- a Lambda execution log excerpt
- a QuickSight slice showing before and after behavior
- a measured KPI such as reduced breach rate or reduced review time
