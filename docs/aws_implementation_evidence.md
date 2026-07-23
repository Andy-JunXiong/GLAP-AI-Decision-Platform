# AWS Implementation Evidence

This manifest records which public artifacts were checked against the deployed AWS environment. It intentionally excludes query IDs, account IDs, ARNs, bucket names, log-stream names, and credentials.

## Verification record

Verification was performed on **2026-07-21** against the GLAP resources in AWS `us-east-1` using read-only inspection wherever possible.

An orchestrator reliability update was deployed and smoke-tested on
**2026-07-23**. The deployed revision selects only anomalies without an existing
decision, can resume a missing decision from an existing root-cause record,
cancels timed-out Athena queries, and reads paginated Athena results. The
post-deployment synchronous invocation completed successfully with no function
error. With no pending anomalies, its measured duration was approximately 2.34
seconds, compared with approximately 55.37 seconds for the preceding duplicate-
only scheduled invocation. Immutable Lambda version `1` is the pre-deployment
rollback point and version `2` is the verified reliability release.
The `prod` Lambda alias points to version `2`, and the enabled daily EventBridge
Scheduler target was changed from the mutable function ARN to that alias after a
successful alias-qualified smoke test.

| Artifact | AWS source | Verification | Public location |
| --- | --- | --- | --- |
| Agent orchestrator | Deployed `glap-ai-agent-orchestrator` Lambda package | Source exported; Python 3.14 runtime and 2026-03-12 deployment metadata observed | [`../lambda/glap_ai_agent_orchestrator.py`](../lambda/glap_ai_agent_orchestrator.py) |
| Core Iceberg schemas | Athena `SHOW CREATE TABLE` for four deployed tables | All four statements completed successfully; S3 locations redacted | [`../sql/00_core_table_ddl.sql`](../sql/00_core_table_ddl.sql) |
| Agent input query | Deployed Lambda source and Athena query history | Query text matched and was observed in successful history | [`../sql/01_agent_orchestration.sql`](../sql/01_agent_orchestration.sql) |
| Validation patterns | Athena query history | Read and duplicate-check patterns observed; public queries generalized to avoid publishing entity records | [`../sql/02_validation_queries.sql`](../sql/02_validation_queries.sql) |
| Dashboard outputs | QuickSight-derived project exports | Synthetic dashboard outputs retained as images | [`ai_detection_dashboard.png`](ai_detection_dashboard.png) and related files |

## Capabilities evidenced by deployed source

The exported Lambda source directly demonstrates:

- Athena query submission and status polling
- timeout and failure handling
- Athena result parsing
- rule-based root-cause generation
- rule-based decision generation
- Iceberg inserts through Athena
- duplicate checks by run date, entity key, and metric
- inserted/skipped execution counters

## Evidence boundaries

- All logistics records and outcome examples are synthetic.
- Successful AWS execution demonstrates technical operation, not production scale, availability, cost, or business impact.
- Outcome, learning, and policy tables observed in Athena are synthetic validation paths; they are not evidence of autonomous improvement in a live logistics operation.
- The public DDL is faithful to Athena output except for redacted S3 locations.
- The repository does not include CloudWatch log excerpts because an authenticated read-only log session was unavailable during the final evidence pass.

## Re-verification

To re-verify without publishing environment identifiers:

1. Compare the deployed Lambda package with `lambda/glap_ai_agent_orchestrator.py`.
2. Run `SHOW CREATE TABLE` for each table listed in `sql/00_core_table_ddl.sql`.
3. Confirm the agent input query appears in Athena history after an orchestrator run.
4. Confirm root-cause and decision rows use the documented schema and duplicate key.
5. Redact all AWS identifiers before adding any new evidence to the public repository.
