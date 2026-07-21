"""Sanitized representative Lambda snippet derived from the GLAP architecture."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

athena = boto3.client("athena")
s3 = boto3.client("s3")
ATHENA_DATABASE = os.environ.get("ATHENA_DATABASE", "glap")
RESULTS_BUCKET = os.environ.get("RESULTS_BUCKET", "glap-athena-results")
OUTPUT_PREFIX = os.environ.get("OUTPUT_PREFIX", "decision-output/")


def lambda_handler(event, context):
    trigger_time = event.get("time") or datetime.now(timezone.utc).isoformat()
    schedule_arn = event.get("resources", ["manual-run"])[0]
    logger.info("Starting GLAP decision orchestration at %s from %s", trigger_time, schedule_arn)

    sql = """
    SELECT run_date, entity_key, metric_name, metric_value, baseline_value, z_score, shipment_count
    FROM fact_ai_anomaly_scores_v1
    WHERE run_date = current_date
      AND z_score >= 1.8
    """

    try:
        response = athena.start_query_execution(
            QueryString=sql,
            QueryExecutionContext={"Database": ATHENA_DATABASE},
            ResultConfiguration={"OutputLocation": f"s3://{RESULTS_BUCKET}/athena-results/"},
        )
        query_id = response["QueryExecutionId"]
        result_uri = f"s3://{RESULTS_BUCKET}/{OUTPUT_PREFIX}{query_id}.json"

        payload = {
            "query_execution_id": query_id,
            "trigger_time": trigger_time,
            "schedule_arn": schedule_arn,
            "status": "STARTED",
        }
        s3.put_object(
            Bucket=RESULTS_BUCKET,
            Key=f"{OUTPUT_PREFIX}{query_id}.json",
            Body=json.dumps(payload).encode("utf-8"),
            ContentType="application/json",
        )
        logger.info("Queued Athena query %s and wrote execution marker to %s", query_id, result_uri)
        return {"statusCode": 200, "body": payload}
    except Exception:
        logger.exception("Failed to start GLAP Athena workflow")
        return {"statusCode": 500, "body": {"message": "GLAP orchestration failed"}}
