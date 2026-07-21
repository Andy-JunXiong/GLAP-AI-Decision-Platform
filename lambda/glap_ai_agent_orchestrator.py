import boto3
import os
import time

ATHENA_DATABASE = os.environ["ATHENA_DATABASE"]
ATHENA_OUTPUT = os.environ["ATHENA_OUTPUT"]
ATHENA_WORKGROUP = os.environ.get("ATHENA_WORKGROUP", "primary")

athena = boto3.client("athena")


def start_query(sql):
    response = athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": ATHENA_DATABASE},
        ResultConfiguration={"OutputLocation": ATHENA_OUTPUT},
        WorkGroup=ATHENA_WORKGROUP
    )
    return response["QueryExecutionId"]


def wait_for_query(query_id, timeout_seconds=120):
    start_time = time.time()

    while True:
        response = athena.get_query_execution(QueryExecutionId=query_id)
        state = response["QueryExecution"]["Status"]["State"]

        if state in ["SUCCEEDED", "FAILED", "CANCELLED"]:
            return state, response

        if time.time() - start_time > timeout_seconds:
            raise TimeoutError(f"Athena query timed out after {timeout_seconds} seconds")

        time.sleep(2)


def run_query(sql):
    qid = start_query(sql)
    state, response = wait_for_query(qid)

    if state != "SUCCEEDED":
        reason = response["QueryExecution"]["Status"].get("StateChangeReason", "Unknown Athena error")
        raise Exception(f"Athena query failed: {reason}")

    return qid


def get_query_results(query_id):
    result = athena.get_query_results(QueryExecutionId=query_id)

    columns = [c["Label"] for c in result["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]]
    rows = []

    for row in result["ResultSet"]["Rows"][1:]:
        values = [col.get("VarCharValue", None) for col in row["Data"]]
        rows.append(dict(zip(columns, values)))

    return rows


def escape_sql_string(value):
    if value is None:
        return ""
    return str(value).replace("'", "''")


def to_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def record_exists(table_name, run_date, entity_key, metric_name):
    check_sql = f"""
    SELECT COUNT(*) AS cnt
    FROM {table_name}
    WHERE run_date = DATE '{escape_sql_string(run_date)}'
      AND entity_key = '{escape_sql_string(entity_key)}'
      AND metric_name = '{escape_sql_string(metric_name)}'
    """

    qid = run_query(check_sql)
    rows = get_query_results(qid)

    if not rows:
        return False

    try:
        return int(rows[0]["cnt"]) > 0
    except Exception:
        return False


def generate_root_cause(metric_name, metric_value, baseline_value, z_score):
    metric_name = str(metric_name).lower()
    metric_value = to_float(metric_value)
    baseline_value = to_float(baseline_value)
    z_score = to_float(z_score)

    if metric_name == "avg_leg_duration_days" and metric_value > baseline_value:
        return (
            "Transit time increased relative to historical baseline, suggesting potential carrier delay, port congestion, or downstream handling slowdown.",
            "avg_leg_duration_days",
            0.80
        )

    elif metric_name == "breach_rate" and metric_value > baseline_value:
        return (
            "Higher SLA breach rate indicates potential service reliability degradation, possibly due to operational disruption or capacity imbalance.",
            "breach_rate",
            0.75
        )

    elif abs(z_score) >= 2:
        return (
            "Operational metric shows significant deviation from historical baseline, indicating abnormal operational behavior.",
            metric_name,
            0.65
        )

    else:
        return (
            "Metric deviation from baseline detected, suggesting potential early-stage operational instability.",
            metric_name,
            0.55
        )


def generate_decision(metric_name, confidence_score):
    metric_name = str(metric_name).lower()
    confidence_score = to_float(confidence_score)

    if metric_name == "avg_leg_duration_days" and confidence_score >= 0.75:
        return (
            "Investigate carrier transit delay and monitor route performance",
            "Transit time anomaly detected with high confidence indicating possible carrier or port delay.",
            "HIGH"
        )

    elif metric_name == "breach_rate" and confidence_score >= 0.7:
        return (
            "Escalate SLA reliability issue and review carrier operational stability",
            "Elevated SLA breach rate suggests potential service reliability degradation.",
            "HIGH"
        )

    else:
        return (
            "Continue monitoring operational metrics for potential emerging issues",
            "Current anomaly confidence is moderate and requires observation before intervention.",
            "MEDIUM"
        )


def insert_root_cause_record(row):
    if record_exists(
        "curated_iceberg.fact_ai_root_cause_v1",
        row["run_date"],
        row["entity_key"],
        row["metric_name"]
    ):
        return {
            "run_date": row["run_date"],
            "entity_key": row["entity_key"],
            "metric_name": row["metric_name"],
            "root_cause": None,
            "confidence_score": None,
            "supporting_metric": None,
            "skipped": True
        }

    root_cause, supporting_metric, confidence_score = generate_root_cause(
        row["metric_name"],
        row["metric_value"],
        row["baseline_value"],
        row["z_score"]
    )

    insert_sql = f"""
    INSERT INTO curated_iceberg.fact_ai_root_cause_v1
    VALUES (
        DATE '{escape_sql_string(row["run_date"])}',
        '{escape_sql_string(row["entity_key"])}',
        '{escape_sql_string(row["metric_name"])}',
        '{escape_sql_string(root_cause)}',
        {confidence_score},
        '{escape_sql_string(supporting_metric)}',
        current_timestamp
    )
    """

    run_query(insert_sql)

    return {
        "run_date": row["run_date"],
        "entity_key": row["entity_key"],
        "metric_name": row["metric_name"],
        "root_cause": root_cause,
        "confidence_score": confidence_score,
        "supporting_metric": supporting_metric,
        "skipped": False
    }


def insert_decision_record(root_cause_row):
    if record_exists(
        "curated_iceberg.fact_ai_decision_explanations_v1",
        root_cause_row["run_date"],
        root_cause_row["entity_key"],
        root_cause_row["metric_name"]
    ):
        return "skipped"

    if root_cause_row.get("skipped") and root_cause_row.get("confidence_score") is None:
        return "skipped"

    recommended_action, decision_reason, action_priority = generate_decision(
        root_cause_row["metric_name"],
        root_cause_row["confidence_score"]
    )

    insert_sql = f"""
    INSERT INTO curated_iceberg.fact_ai_decision_explanations_v1
    VALUES (
        DATE '{escape_sql_string(root_cause_row["run_date"])}',
        '{escape_sql_string(root_cause_row["entity_key"])}',
        '{escape_sql_string(root_cause_row["metric_name"])}',
        '{escape_sql_string(recommended_action)}',
        '{escape_sql_string(decision_reason)}',
        '{escape_sql_string(action_priority)}',
        current_timestamp
    )
    """

    run_query(insert_sql)
    return "inserted"


def lambda_handler(event, context):
    print("GLAP AI Agent Orchestrator started")

    anomaly_sql = """
    SELECT
        run_date,
        entity_key,
        metric_name,
        metric_value,
        baseline_value,
        z_score
    FROM curated_iceberg.fact_ai_anomaly_scores_v1
    ORDER BY abs(z_score) DESC
    LIMIT 10
    """

    qid = run_query(anomaly_sql)
    anomaly_rows = get_query_results(qid)

    print("Anomaly rows fetched:", len(anomaly_rows))

    root_cause_inserted = 0
    root_cause_skipped = 0
    decision_inserted = 0
    decision_skipped = 0

    for row in anomaly_rows:
        root_cause_row = insert_root_cause_record(row)

        if root_cause_row.get("skipped"):
            root_cause_skipped += 1
        else:
            root_cause_inserted += 1

        decision_status = insert_decision_record(root_cause_row)

        if decision_status == "inserted":
            decision_inserted += 1
        else:
            decision_skipped += 1

    print("Root cause rows inserted:", root_cause_inserted)
    print("Root cause rows skipped:", root_cause_skipped)
    print("Decision rows inserted:", decision_inserted)
    print("Decision rows skipped:", decision_skipped)

    return {
        "status": "success",
        "root_cause_inserted": root_cause_inserted,
        "root_cause_skipped": root_cause_skipped,
        "decision_inserted": decision_inserted,
        "decision_skipped": decision_skipped
    }
