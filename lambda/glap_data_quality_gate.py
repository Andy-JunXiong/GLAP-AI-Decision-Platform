"""Athena-backed, fail-closed data-quality gate for the GLAP daily pipeline."""

from __future__ import annotations

from datetime import date
import os
import re
import time
from typing import Any

import boto3

from glap_quality_contracts import (
    LIFECYCLE_CHECK_NAMES,
    MULTIMODAL_ANALYTICS_CHECK_NAMES,
    PIPELINE_CHECK_NAMES,
    render_lifecycle_validation_queries,
    render_multimodal_analytics_validation_query,
)


IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TERMINAL_FAILURE_STATES = {"FAILED", "CANCELLED"}
QUALITY_CHECK_NAMES = tuple(sorted(PIPELINE_CHECK_NAMES))

INPUT_CONTRACTS = {
    "pipeline_v1": {
        "shipment_table": "fact_shipment_v2",
        "tables": (
            ("fact_shipment_v2", "try_cast(dt AS date)", "ROW(shipment_id, dt)"),
            (
                "fact_shipment_event_v2",
                "try_cast(dt AS date)",
                "ROW(shipment_id, leg_seq, event_type, event_ts, dt)",
            ),
            (
                "fact_shipment_leg_metrics_core_v2",
                "run_date",
                "ROW(shipment_id, leg_seq, dt)",
            ),
            ("fact_shipment_cost_v2", "try_cast(dt AS date)", "ROW(shipment_id, dt)"),
            (
                "fact_shipment_risk_v2",
                "coalesce(risk_dt, try_cast(dt AS date))",
                "ROW(shipment_id, dt)",
            ),
            (
                "shipment_product_allocation_v2",
                "try_cast(dt AS date)",
                "ROW(shipment_id, product_id, dt)",
            ),
        ),
    },
    "lifecycle_compat_v2": {
        "shipment_table": "vw_lifecycle_shipment_v2_compat",
        "tables": (
            (
                "vw_lifecycle_shipment_v2_compat",
                "try_cast(dt AS date)",
                "ROW(shipment_id, dt)",
            ),
            (
                "vw_lifecycle_shipment_event_v2_compat",
                "try_cast(dt AS date)",
                "ROW(shipment_id, leg_seq, event_type, event_ts, dt)",
            ),
            (
                "vw_lifecycle_leg_metrics_v2_compat",
                "run_date",
                "ROW(shipment_id, leg_seq, dt)",
            ),
            (
                "vw_lifecycle_cost_v2_compat",
                "try_cast(dt AS date)",
                "ROW(shipment_id, dt)",
            ),
            (
                "vw_lifecycle_risk_v2_compat",
                "coalesce(risk_dt, try_cast(dt AS date))",
                "ROW(shipment_id, dt)",
            ),
            (
                "vw_lifecycle_product_allocation_v2_compat",
                "try_cast(dt AS date)",
                "ROW(shipment_id, product_id, dt)",
            ),
        ),
    },
}

ATHENA_DATABASE = os.getenv("ATHENA_DATABASE", "curated_iceberg")
ATHENA_SOURCE_DATABASE = os.getenv("ATHENA_SOURCE_DATABASE", "simulated_iceberg_m")
ATHENA_OUTPUT = os.getenv("ATHENA_OUTPUT")
ATHENA_WORKGROUP = os.getenv("ATHENA_WORKGROUP", "primary")
ATHENA_REGION = os.getenv("ATHENA_REGION", "us-east-1")

athena = boto3.client("athena", region_name=ATHENA_REGION)


def validate_identifier(value: str, label: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"Invalid {label}: {value!r}")
    return value


def validate_run_date(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("logical_run_date is required")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("logical_run_date must use YYYY-MM-DD")
    return value


def _stat_sql(
    database: str,
    table: str,
    date_expression: str,
    key_expression: str,
    logical_run_date: str,
) -> str:
    return f"""
SELECT
    '{table}' AS stage_name,
    count_if({date_expression} = DATE '{logical_run_date}') AS row_count,
    count_if({date_expression} = DATE '{logical_run_date}')
      - count(DISTINCT IF(
            {date_expression} = DATE '{logical_run_date}',
            {key_expression}
        )) AS duplicate_count,
    max({date_expression}) AS latest_date
FROM {database}.{table}
""".strip()


def _quality_projection(logical_run_date: str, volume_sql: str) -> str:
    return f"""
SELECT
    CAST(count(*) AS varchar) AS required_tables,
    CAST(sum(CASE WHEN row_count > 0 THEN 1 ELSE 0 END) AS varchar) AS populated_tables,
    CAST(sum(CASE WHEN latest_date = DATE '{logical_run_date}' THEN 1 ELSE 0 END) AS varchar)
        AS current_tables,
    CAST(sum(row_count) AS varchar) AS total_rows,
    CAST(sum(duplicate_count) AS varchar) AS duplicate_business_keys,
    CAST(volumes.observed_volume AS varchar) AS observed_volume,
    CAST(volumes.previous_volume AS varchar) AS previous_volume
FROM table_stats
CROSS JOIN ({volume_sql}) AS volumes
GROUP BY volumes.observed_volume, volumes.previous_volume
""".strip()


def build_input_quality_query(
    logical_run_date: str,
    source_database: str = ATHENA_SOURCE_DATABASE,
    quality_contract: str = "pipeline_v1",
) -> str:
    logical_run_date = validate_run_date(logical_run_date)
    source_database = validate_identifier(source_database, "Athena source database")
    try:
        contract = INPUT_CONTRACTS[quality_contract]
    except KeyError as exc:
        raise ValueError("Unsupported input quality contract") from exc
    stats = [
        _stat_sql(source_database, table, date_expression, key_expression, logical_run_date)
        for table, date_expression, key_expression in contract["tables"]
    ]
    shipment_table = contract["shipment_table"]
    volume_sql = f"""
SELECT
    count(DISTINCT IF(try_cast(dt AS date) = DATE '{logical_run_date}', shipment_id))
        AS observed_volume,
    count(DISTINCT IF(
        try_cast(dt AS date) = date_add('day', -1, DATE '{logical_run_date}'), shipment_id
    )) AS previous_volume
FROM {source_database}.{shipment_table}
""".strip()
    return (
        "WITH table_stats AS (\n"
        + "\nUNION ALL\n".join(stats)
        + "\n)\n"
        + _quality_projection(logical_run_date, volume_sql)
    )


def build_output_quality_query(
    logical_run_date: str,
    database: str = ATHENA_DATABASE,
    source_database: str = ATHENA_SOURCE_DATABASE,
) -> str:
    logical_run_date = validate_run_date(logical_run_date)
    database = validate_identifier(database, "Athena database")
    source_database = validate_identifier(source_database, "Athena source database")
    stats = [
        _stat_sql(
            database,
            "fact_ai_alerts_v3",
            "run_date",
            "ROW(alert_id, run_date)",
            logical_run_date,
        ),
        _stat_sql(
            database,
            "fact_ai_insights_v3",
            "run_date",
            "ROW(insight_id, run_date)",
            logical_run_date,
        ),
        _stat_sql(
            database,
            "fact_ai_decisions_v3",
            "run_date",
            "ROW(decision_id, run_date)",
            logical_run_date,
        ),
        _stat_sql(
            database,
            "fact_ai_actions_v2",
            "run_date",
            "ROW(action_id, run_date)",
            logical_run_date,
        ),
        _stat_sql(
            database,
            "fact_ai_outcomes_v2",
            "run_date",
            "ROW(outcome_id, run_date)",
            logical_run_date,
        ),
        _stat_sql(
            database,
            "fact_ai_learning_v1",
            "run_date",
            "ROW(action_type, metric_name, run_date)",
            logical_run_date,
        ),
    ]
    volume_sql = f"""
SELECT
    count(DISTINCT IF(
        try_cast(dt AS date) = DATE '{logical_run_date}', shipment_id
    )) AS observed_volume,
    count(DISTINCT IF(
        try_cast(dt AS date) = date_add('day', -1, DATE '{logical_run_date}'), shipment_id
    )) AS previous_volume
FROM {source_database}.fact_shipment_v2
""".strip()
    return (
        "WITH table_stats AS (\n"
        + "\nUNION ALL\n".join(stats)
        + "\n)\n"
        + _quality_projection(logical_run_date, volume_sql)
    )


def _int_value(row: dict[str, Any], name: str) -> int:
    try:
        return int(row[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Athena quality result missing integer field: {name}") from exc


def evaluate_quality_metrics(
    row: dict[str, Any],
    max_volume_change_pct: float,
) -> tuple[dict[str, str], dict[str, Any]]:
    if not 0 <= max_volume_change_pct <= 1000:
        raise ValueError("MAX_VOLUME_CHANGE_PCT must be between 0 and 1000")
    required_tables = _int_value(row, "required_tables")
    populated_tables = _int_value(row, "populated_tables")
    current_tables = _int_value(row, "current_tables")
    total_rows = _int_value(row, "total_rows")
    duplicates = _int_value(row, "duplicate_business_keys")
    observed_volume = _int_value(row, "observed_volume")
    previous_volume = _int_value(row, "previous_volume")
    volume_change_pct = (
        100.0 * abs(observed_volume - previous_volume) / previous_volume
        if previous_volume > 0
        else None
    )

    passed = {
        "missing_dates": populated_tables == required_tables and required_tables > 0,
        "empty_inputs": total_rows > 0 and observed_volume > 0,
        "duplicate_business_keys": duplicates == 0,
        "abnormal_volume_change": (
            volume_change_pct is not None and volume_change_pct <= max_volume_change_pct
        ),
        "stale_stage_outputs": current_tables == required_tables and required_tables > 0,
    }
    checks = {name: "passed" if passed[name] else "failed" for name in QUALITY_CHECK_NAMES}
    metrics = {
        "required_tables": required_tables,
        "populated_tables": populated_tables,
        "current_tables": current_tables,
        "total_rows": total_rows,
        "duplicate_business_keys": duplicates,
        "observed_volume": observed_volume,
        "previous_volume": previous_volume,
        "volume_change_pct": round(volume_change_pct, 2) if volume_change_pct is not None else None,
        "max_volume_change_pct": max_volume_change_pct,
    }
    return checks, metrics


def parse_athena_result(response: dict[str, Any]) -> dict[str, str | None]:
    rows = response.get("ResultSet", {}).get("Rows", [])
    if len(rows) != 2:
        raise ValueError("Athena quality query must return exactly one data row")
    headers = [cell.get("VarCharValue") for cell in rows[0].get("Data", [])]
    values = [cell.get("VarCharValue") for cell in rows[1].get("Data", [])]
    if not headers or any(header is None for header in headers):
        raise ValueError("Athena quality query returned invalid headers")
    values.extend([None] * (len(headers) - len(values)))
    return dict(zip(headers, values))


def execute_query(query: str, database: str, max_results: int) -> dict[str, Any]:
    if not ATHENA_OUTPUT:
        raise ValueError("ATHENA_OUTPUT is required")
    execution_id = athena.start_query_execution(
        QueryString=query,
        QueryExecutionContext={"Database": database},
        ResultConfiguration={"OutputLocation": ATHENA_OUTPUT},
        WorkGroup=ATHENA_WORKGROUP,
    )["QueryExecutionId"]
    deadline = time.monotonic() + 180
    while True:
        execution = athena.get_query_execution(QueryExecutionId=execution_id)["QueryExecution"]
        state = execution["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in TERMINAL_FAILURE_STATES:
            raise RuntimeError(f"Athena quality query {state.lower()}")
        if time.monotonic() >= deadline:
            athena.stop_query_execution(QueryExecutionId=execution_id)
            raise TimeoutError("Athena quality query timed out after 180 seconds")
        time.sleep(1)
    return athena.get_query_results(QueryExecutionId=execution_id, MaxResults=max_results)


def run_query(query: str, database: str) -> dict[str, str | None]:
    return parse_athena_result(execute_query(query, database, 10))


def parse_validation_result(response: dict[str, Any]) -> dict[str, int]:
    rows = response.get("ResultSet", {}).get("Rows", [])
    if len(rows) < 2:
        raise ValueError("Lifecycle validation query returned no checks")
    headers = [cell.get("VarCharValue") for cell in rows[0].get("Data", [])]
    if headers[:2] != ["check_name", "failure_count"]:
        raise ValueError("Lifecycle validation query returned an invalid contract")
    parsed: dict[str, int] = {}
    for row in rows[1:]:
        values = [cell.get("VarCharValue") for cell in row.get("Data", [])]
        if len(values) < 2 or not values[0] or values[0] in parsed:
            raise ValueError("Lifecycle validation query returned duplicate or missing checks")
        try:
            parsed[values[0]] = int(values[1])
        except (TypeError, ValueError) as exc:
            raise ValueError("Lifecycle validation failure_count must be an integer") from exc
    return parsed


def run_lifecycle_validation(logical_run_date: str, source_database: str) -> dict[str, int]:
    failures: dict[str, int] = {}
    for query in render_lifecycle_validation_queries(logical_run_date, source_database):
        for name, count in parse_validation_result(
            execute_query(query, source_database, 100)
        ).items():
            if name in failures:
                raise ValueError("Lifecycle validation returned a duplicate check")
            failures[name] = count
    if set(failures) != set(LIFECYCLE_CHECK_NAMES):
        raise ValueError("Lifecycle validation returned an incomplete quality contract")
    return failures


def run_multimodal_analytics_validation(
    logical_run_date: str, source_database: str
) -> dict[str, int]:
    failures = parse_validation_result(
        execute_query(
            render_multimodal_analytics_validation_query(
                logical_run_date, source_database
            ),
            source_database,
            100,
        )
    )
    if set(failures) != set(MULTIMODAL_ANALYTICS_CHECK_NAMES):
        raise ValueError("Multimodal analytics validation returned an incomplete quality contract")
    return failures


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    event = event if isinstance(event, dict) else {}
    logical_run_date = validate_run_date(
        event.get("logical_run_date") or event.get("run_date")
    )
    pipeline_stage = event.get("pipeline_stage")
    quality_contract = event.get("quality_contract") or "pipeline_v1"
    database = validate_identifier(ATHENA_DATABASE, "Athena database")
    source_database = validate_identifier(
        ATHENA_SOURCE_DATABASE, "Athena source database"
    )
    if pipeline_stage == "lifecycle_validation":
        if quality_contract != "lifecycle_v1":
            raise ValueError("lifecycle_validation requires lifecycle_v1")
        failure_counts = run_lifecycle_validation(logical_run_date, source_database)
        checks = {
            name: "passed" if failure_counts[name] == 0 else "failed"
            for name in sorted(LIFECYCLE_CHECK_NAMES)
        }
        return {
            "status": "success",
            "logical_run_date": logical_run_date,
            "pipeline_stage": pipeline_stage,
            "quality_contract": quality_contract,
            "quality_checks": checks,
            "failed_checks": [name for name, status in checks.items() if status == "failed"],
            "metrics": {
                "check_count": len(checks),
                "failure_count": sum(failure_counts.values()),
            },
        }
    if pipeline_stage == "analytics_validation":
        if quality_contract != "multimodal_analytics_v1":
            raise ValueError(
                "analytics_validation requires multimodal_analytics_v1"
            )
        failure_counts = run_multimodal_analytics_validation(
            logical_run_date, source_database
        )
        checks = {
            name: "passed" if failure_counts[name] == 0 else "failed"
            for name in sorted(MULTIMODAL_ANALYTICS_CHECK_NAMES)
        }
        return {
            "status": "success",
            "logical_run_date": logical_run_date,
            "pipeline_stage": pipeline_stage,
            "quality_contract": quality_contract,
            "quality_checks": checks,
            "failed_checks": [name for name, status in checks.items() if status == "failed"],
            "metrics": {
                "check_count": len(checks),
                "failure_count": sum(failure_counts.values()),
            },
        }
    if pipeline_stage == "input_validation":
        query = build_input_quality_query(
            logical_run_date, source_database, quality_contract
        )
        query_database = source_database
    elif pipeline_stage == "output_validation":
        if quality_contract != "pipeline_v1":
            raise ValueError("output_validation requires pipeline_v1")
        query = build_output_quality_query(logical_run_date, database, source_database)
        query_database = database
    else:
        raise ValueError(
            "pipeline_stage must be lifecycle_validation, analytics_validation, "
            "input_validation or output_validation"
        )

    checks, metrics = evaluate_quality_metrics(
        run_query(query, query_database),
        float(os.getenv("MAX_VOLUME_CHANGE_PCT", "50")),
    )
    return {
        "status": "success",
        "logical_run_date": logical_run_date,
        "pipeline_stage": pipeline_stage,
        "quality_contract": quality_contract,
        "quality_checks": checks,
        "failed_checks": [name for name, status in checks.items() if status == "failed"],
        "metrics": metrics,
    }
