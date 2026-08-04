"""Governed Athena persistence adapter for the GLAP lifecycle staging engine."""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
import os
import re
import time
from typing import Any, Iterable

import glap_stateful_lifecycle_generator as engine


IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DATABASE = os.getenv("ATHENA_SOURCE_DATABASE", "simulated_iceberg_m")
WORKGROUP = os.getenv("ATHENA_WORKGROUP", "primary")
OUTPUT = os.getenv("ATHENA_OUTPUT", "")
SNAPSHOT_TABLE = os.getenv("SHIPMENT_TABLE", "fact_shipment_lifecycle_staging_v1")
EVENT_TABLE = os.getenv("SHIPMENT_EVENT_TABLE", "fact_shipment_lifecycle_event_staging_v1")
COST_TABLE = os.getenv("SHIPMENT_COST_TABLE", "fact_shipment_cost_staging_v1")
METRICS_TABLE = os.getenv("SHIPMENT_METRICS_TABLE", "fact_shipment_lifecycle_metrics_staging_v1")
SIGNAL_TABLE = os.getenv("SHIPMENT_SIGNAL_TABLE", "fact_shipment_signal_candidate_staging_v1")
ROUTE_TABLE = os.getenv("ROUTE_SERVICE_TABLE", "dim_route_service_v1")
TARGET_TABLE = os.getenv("LIFECYCLE_TARGET_TABLE", "dim_lifecycle_target_v1")
RATE_TABLE = os.getenv("RATE_CARD_TABLE", "dim_rate_card_v1")
FX_TABLE = os.getenv("FX_RATE_TABLE", "dim_fx_rate_v1")

SNAPSHOT_COLUMNS = (
    "shipment_id", "dt", "booking_at", "gate_in_target_at", "gate_in_at", "etd", "atd",
    "eta", "ata", "discharge_target_at", "discharged_at", "delivery_target_at",
    "delivered_at", "lifecycle_stage", "lifecycle_status", "terminal_state", "origin_port", "destination_port",
    "carrier", "route_service_id", "route_config_version", "rate_card_version",
    "rate_locked_at", "service_level", "equipment_type", "container_count",
    "journey_exception_type", "journey_exception_hours", "expected_total_cost",
    "accrued_total_cost", "actual_total_cost", "cost_currency", "simulation_seed",
    "created_at", "updated_at",
)
EVENT_COLUMNS = (
    "event_id", "shipment_id", "event_type", "event_time", "observed_at", "processed_at",
    "location", "logical_run_date", "scenario_id", "simulation_seed",
)
COST_COLUMNS = (
    "shipment_id", "dt", "charge_code", "cost_stage", "calculation_basis", "quantity",
    "unit_rate", "amount", "currency", "rate_card_id", "rate_card_version", "cost_status",
    "created_at",
)
METRICS_COLUMNS = (
    "shipment_id", "dt", "lifecycle_stage", "lifecycle_status", "gate_in_performance",
    "gate_in_delay_hours", "departure_performance", "departure_delay_hours",
    "arrival_performance", "arrival_delay_hours", "discharge_performance",
    "discharge_delay_hours", "delivery_performance", "delivery_delay_hours",
    "planned_p2p_hours", "actual_p2p_hours", "sla_breach_flag", "sla_breach_stages",
    "computed_at",
)
SIGNAL_COLUMNS = (
    "signal_fingerprint", "shipment_id", "dt", "signal_type", "signal_grain",
    "signal_dimension", "metric_name", "metric_value", "threshold_value", "severity",
    "candidate_status", "simulation_provenance", "computed_at",
)


def _identifier(value: str, label: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"Invalid {label}: {value!r}")
    return value


def validate_configuration() -> None:
    for value, label in (
        (DATABASE, "database"), (SNAPSHOT_TABLE, "snapshot table"), (EVENT_TABLE, "event table"),
        (COST_TABLE, "cost table"), (METRICS_TABLE, "metrics table"),
        (SIGNAL_TABLE, "signal table"),
        (ROUTE_TABLE, "route table"), (TARGET_TABLE, "target table"),
        (RATE_TABLE, "rate table"), (FX_TABLE, "FX table"),
    ):
        _identifier(value, label)
    if not OUTPUT.startswith("s3://"):
        raise ValueError("ATHENA_OUTPUT is required and must be an s3:// URI")


def build_configuration_queries(logical_date: date) -> dict[str, str]:
    day = logical_date.isoformat()
    database = _identifier(DATABASE, "database")
    return {
        "targets": f"""SELECT stage_code, target_days FROM {database}.{_identifier(TARGET_TABLE, 'target table')}
WHERE status = 'ACTIVE' AND effective_from <= DATE '{day}'
  AND (effective_to IS NULL OR effective_to >= DATE '{day}')""",
        "routes": f"""SELECT route_service_id, origin_port, destination_port, carrier, service_code,
service_level, p2p_target_days, effective_from, effective_to, config_version
FROM {database}.{_identifier(ROUTE_TABLE, 'route table')}
WHERE status = 'ACTIVE' AND effective_from <= DATE '{day}'
  AND (effective_to IS NULL OR effective_to >= DATE '{day}')""",
        "rates": f"""SELECT rate_card_id, origin_port, destination_port, carrier, service_code,
equipment_type, charge_code, calculation_basis, amount, percentage_rate, currency,
effective_from, effective_to, status, config_version
FROM {database}.{_identifier(RATE_TABLE, 'rate table')}
WHERE status = 'ACTIVE' AND effective_from <= DATE '{day}'
  AND (effective_to IS NULL OR effective_to >= DATE '{day}')""",
        "fx": f"""SELECT base_currency, quote_currency, fx_rate
FROM {database}.{_identifier(FX_TABLE, 'FX table')}
WHERE effective_date = (
  SELECT max(effective_date) FROM {database}.{_identifier(FX_TABLE, 'FX table')}
  WHERE effective_date <= DATE '{day}'
)""",
    }


def build_active_snapshot_query(logical_date: date) -> str:
    previous = (logical_date.fromordinal(logical_date.toordinal() - 1)).isoformat()
    columns = ", ".join(SNAPSHOT_COLUMNS)
    return f"""SELECT {columns}
FROM {_identifier(DATABASE, 'database')}.{_identifier(SNAPSHOT_TABLE, 'snapshot table')}
WHERE try_cast(dt AS date) = DATE '{previous}'
  AND lifecycle_status = 'OPEN' AND terminal_state = false"""


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        utc = value.astimezone(timezone.utc).replace(tzinfo=None)
        return f"TIMESTAMP '{utc.isoformat(sep=' ', timespec='seconds')}'"
    if isinstance(value, date):
        return f"DATE '{value.isoformat()}'"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def build_merge_sql(table: str, columns: tuple[str, ...], key_columns: tuple[str, ...],
                    rows: Iterable[dict[str, Any]]) -> list[str]:
    """Build retry-safe Iceberg MERGE statements in bounded batches."""

    table = _identifier(table, "target table")
    row_list = list(rows)
    statements = []
    for start in range(0, len(row_list), 100):
        batch = row_list[start:start + 100]
        values = ",\n".join(
            "(" + ", ".join(_sql_literal(row.get(column)) for column in columns) + ")"
            for row in batch
        )
        source_columns = ", ".join(columns)
        join = " AND ".join(f"target.{key} = source.{key}" for key in key_columns)
        insert_values = ", ".join(f"source.{column}" for column in columns)
        statements.append(f"""MERGE INTO {_identifier(DATABASE, 'database')}.{table} AS target
USING (VALUES
{values}
) AS source ({source_columns})
ON {join}
WHEN NOT MATCHED THEN INSERT ({source_columns}) VALUES ({insert_values})""")
    return statements


def parse_rows(response: dict[str, Any]) -> list[dict[str, str | None]]:
    rows = response.get("ResultSet", {}).get("Rows", [])
    if not rows:
        return []
    column_info = response.get("ResultSet", {}).get("ResultSetMetadata", {}).get("ColumnInfo", [])
    headers = [column.get("Name") for column in column_info]
    if not headers:
        headers = [cell.get("VarCharValue") for cell in rows[0].get("Data", [])]
    if not headers or any(header is None for header in headers):
        raise ValueError("Athena response has invalid headers")
    first_values = [cell.get("VarCharValue") for cell in rows[0].get("Data", [])]
    data_rows = rows[1:] if first_values == headers else rows
    parsed = []
    for row in data_rows:
        values = [cell.get("VarCharValue") for cell in row.get("Data", [])]
        values.extend([None] * (len(headers) - len(values)))
        parsed.append(dict(zip(headers, values)))
    return parsed


def _coerce_snapshot(row: dict[str, str | None]) -> dict[str, Any]:
    result: dict[str, Any] = dict(row)
    for field in (
        "booking_at", "gate_in_target_at", "gate_in_at", "etd", "atd", "eta", "ata",
        "discharge_target_at", "discharged_at", "delivery_target_at", "delivered_at",
        "rate_locked_at", "created_at", "updated_at",
    ):
        result[field] = (
            datetime.fromisoformat(str(row[field])).replace(tzinfo=timezone.utc)
            if row.get(field) else None
        )
    result["terminal_state"] = str(row.get("terminal_state")).lower() == "true"
    for field in ("container_count", "journey_exception_hours"):
        result[field] = int(row[field]) if row.get(field) else 0
    for field in ("expected_total_cost", "accrued_total_cost", "actual_total_cost"):
        result[field] = float(row[field]) if row.get(field) else None
    return result


def _run_query(client: Any, query: str) -> list[dict[str, str | None]]:
    execution_id = client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={"Database": DATABASE},
        ResultConfiguration={"OutputLocation": OUTPUT},
        WorkGroup=WORKGROUP,
    )["QueryExecutionId"]
    deadline = time.monotonic() + 180
    while True:
        execution = client.get_query_execution(QueryExecutionId=execution_id)["QueryExecution"]
        state = execution["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in {"FAILED", "CANCELLED"}:
            raise RuntimeError(f"Athena lifecycle query {state.lower()}")
        if time.monotonic() >= deadline:
            client.stop_query_execution(QueryExecutionId=execution_id)
            raise TimeoutError("Athena lifecycle query timed out")
        time.sleep(1)
    response = client.get_query_results(QueryExecutionId=execution_id, MaxResults=1000)
    rows = parse_rows(response)
    while response.get("NextToken"):
        response = client.get_query_results(
            QueryExecutionId=execution_id,
            MaxResults=1000,
            NextToken=response["NextToken"],
        )
        rows.extend(parse_rows(response))
    return rows


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Read governed configuration, advance one day and MERGE staging rows."""

    validate_configuration()
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - AWS runtime supplies boto3
        raise RuntimeError("boto3 is required for Athena persistence") from exc
    logical_date = date.fromisoformat(event["logical_run_date"])
    client = boto3.client("athena", region_name=os.getenv("AWS_REGION", "us-east-1"))
    config_queries = build_configuration_queries(logical_date)
    target_rows = _run_query(client, config_queries["targets"])
    targets = {str(row["stage_code"]): int(str(row["target_days"])) for row in target_rows}
    routes = _run_query(client, config_queries["routes"])
    for row in routes:
        row["p2p_target_days"] = int(str(row["p2p_target_days"]))
    rates = _run_query(client, config_queries["rates"])
    fx_rows = _run_query(client, config_queries["fx"])
    fx_rates = {
        (str(row["base_currency"]), str(row["quote_currency"])): float(str(row["fx_rate"]))
        for row in fx_rows
    }
    active = [_coerce_snapshot(row) for row in _run_query(client, build_active_snapshot_query(logical_date))]
    if not active and event.get("seed_population", False):
        active = engine.seed_population(
            logical_date, routes, targets, int(event.get("population_size", 450)),
            event.get("seed_version", "lifecycle-2026.08-v1"), rates, fx_rates,
        )
    result = engine.run_day(
        active, logical_date, routes, targets,
        event.get("seed_version", "lifecycle-2026.08-v1"), event.get("new_count"), rates, fx_rates,
    )
    snapshots = result.pop("snapshots")
    events = result.pop("events")
    metrics = result.pop("metrics")
    signals = result.pop("signals")
    cost_rows = []
    for snapshot in snapshots:
        for line in snapshot.pop("expected_cost_lines", []):
            cost_rows.append({
                "shipment_id": snapshot["shipment_id"], "dt": snapshot["dt"],
                "charge_code": line["charge_code"], "cost_stage": "BOOKING",
                "calculation_basis": line["calculation_basis"], "quantity": line["quantity"],
                "unit_rate": line["unit_rate"], "amount": line["amount"],
                "currency": line["currency"], "rate_card_id": line["rate_card_id"],
                "rate_card_version": line["rate_card_version"], "cost_status": "EXPECTED",
                "created_at": snapshot["created_at"],
            })
    statements = (
        build_merge_sql(SNAPSHOT_TABLE, SNAPSHOT_COLUMNS, ("shipment_id", "dt"), snapshots)
        + build_merge_sql(EVENT_TABLE, EVENT_COLUMNS, ("event_id",), events)
        + build_merge_sql(COST_TABLE, COST_COLUMNS, ("shipment_id", "dt", "charge_code"), cost_rows)
        + build_merge_sql(METRICS_TABLE, METRICS_COLUMNS, ("shipment_id", "dt"), metrics)
        + build_merge_sql(
            SIGNAL_TABLE, SIGNAL_COLUMNS, ("signal_fingerprint", "dt"), signals
        )
    )
    if not event.get("dry_run", False):
        for statement in statements:
            _run_query(client, statement)
    return {
        **result,
        "cost_rows_created": len(cost_rows),
        "metric_rows_created": len(metrics),
        "signal_rows_created": len(signals),
        "write_statements": len(statements),
        "dry_run": bool(event.get("dry_run", False)),
    }
