"""Governed Athena persistence adapter for the GLAP lifecycle staging engine."""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
import os
import re
import time
from typing import Any, Iterable

import glap_stateful_lifecycle_generator as engine
import glap_governed_closed_loop as closed_loop
from glap_temporal_boundary import resolve_temporal_context, temporal_scope_id


IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DATABASE = os.getenv("ATHENA_SOURCE_DATABASE", "simulated_iceberg_m")
WORKGROUP = os.getenv("ATHENA_WORKGROUP", "primary")
OUTPUT = os.getenv("ATHENA_OUTPUT", "")
SNAPSHOT_TABLE = os.getenv("SHIPMENT_TABLE", "fact_shipment_lifecycle_staging_v1")
EVENT_TABLE = os.getenv("SHIPMENT_EVENT_TABLE", "fact_shipment_lifecycle_event_staging_v1")
COST_TABLE = os.getenv("SHIPMENT_COST_TABLE", "fact_shipment_cost_staging_v1")
METRICS_TABLE = os.getenv("SHIPMENT_METRICS_TABLE", "fact_shipment_lifecycle_metrics_staging_v1")
SIGNAL_TABLE = os.getenv("SHIPMENT_SIGNAL_TABLE", "fact_shipment_signal_candidate_staging_v1")
ALERT_TABLE = os.getenv("LIFECYCLE_ALERT_TABLE", "fact_lifecycle_alert_staging_v1")
ACTION_TABLE = os.getenv("LIFECYCLE_ACTION_TABLE", "fact_lifecycle_action_staging_v1")
ACTION_CURRENT_VIEW = os.getenv(
    "LIFECYCLE_ACTION_CURRENT_VIEW", "vw_lifecycle_action_current_staging_v1"
)
OUTCOME_TABLE = os.getenv("LIFECYCLE_OUTCOME_TABLE", "fact_lifecycle_outcome_staging_v1")
POLICY_PROPOSAL_TABLE = os.getenv(
    "POLICY_PROPOSAL_TABLE", "fact_policy_proposal_staging_v1"
)
ROUTE_TABLE = os.getenv("ROUTE_SERVICE_TABLE", "dim_route_service_v1")
TARGET_TABLE = os.getenv("LIFECYCLE_TARGET_TABLE", "dim_lifecycle_target_v1")
RATE_TABLE = os.getenv("RATE_CARD_TABLE", "dim_rate_card_v1")
FX_TABLE = os.getenv("FX_RATE_TABLE", "dim_fx_rate_v1")

TEMPORAL_COLUMNS = (
    "temporal_scope_id", "execution_mode", "time_basis", "as_of_date",
    "execution_scenario_id",
)

SNAPSHOT_COLUMNS = (
    "shipment_id", "dt", "booking_at", "gate_in_target_at", "gate_in_at", "etd", "atd",
    "eta", "ata", "discharge_target_at", "discharged_at", "delivery_target_at",
    "delivered_at", "lifecycle_stage", "lifecycle_status", "terminal_state", "origin_port", "destination_port",
    "carrier", "route_service_id", "route_config_version", "rate_card_version",
    "rate_locked_at", "service_level", "equipment_type", "container_count",
    "journey_exception_type", "journey_exception_hours", "expected_total_cost",
    "accrued_total_cost", "actual_total_cost", "cost_currency", "simulation_seed",
    "created_at", "updated_at", "transport_mode", "provider_type",
    "operating_carrier", "origin_location_type", "destination_location_type",
    "origin_handover_target_at", "origin_handover_at",
    "destination_release_target_at", "destination_release_at", "piece_count",
    "gross_weight_kg", "volume_cbm", "chargeable_weight_kg", *TEMPORAL_COLUMNS,
)
EVENT_COLUMNS = (
    "event_id", "shipment_id", "event_type", "event_time", "observed_at", "processed_at",
    "location", "logical_run_date", "scenario_id", "simulation_seed",
    "transport_mode", "segment_type", "leg_seq", "location_type", *TEMPORAL_COLUMNS,
)
COST_COLUMNS = (
    "shipment_id", "dt", "charge_code", "cost_stage", "calculation_basis", "quantity",
    "unit_rate", "amount", "currency", "rate_card_id", "rate_card_version", "cost_status",
    "created_at", *TEMPORAL_COLUMNS,
)
METRICS_COLUMNS = (
    "shipment_id", "dt", "lifecycle_stage", "lifecycle_status", "gate_in_performance",
    "gate_in_delay_hours", "departure_performance", "departure_delay_hours",
    "arrival_performance", "arrival_delay_hours", "discharge_performance",
    "discharge_delay_hours", "delivery_performance", "delivery_delay_hours",
    "planned_p2p_hours", "actual_p2p_hours", "sla_breach_flag", "sla_breach_stages",
    "computed_at", "origin_performance", "origin_delay_hours",
    "destination_release_performance", "destination_release_delay_hours", *TEMPORAL_COLUMNS,
)
SIGNAL_COLUMNS = (
    "signal_fingerprint", "shipment_id", "dt", "signal_type", "signal_grain",
    "signal_dimension", "metric_name", "metric_value", "threshold_value", "severity",
    "candidate_status", "simulation_provenance", "computed_at", *TEMPORAL_COLUMNS,
)
ALERT_COLUMNS = (
    "alert_fingerprint", "shipment_id", "dt", "alert_type", "alert_grain",
    "alert_dimension", "severity", "status", "first_detected_date",
    "last_detected_date", "resolved_date", "metric_name", "metric_value",
    "threshold_value", "provenance", "updated_at", *TEMPORAL_COLUMNS,
)
ACTION_COLUMNS = (
    "action_id", "alert_fingerprint", "shipment_id", "action_type", "alert_type",
    "alert_severity", "policy_version", "status", "approval_required", "approved_by",
    "approved_at", "completed_at", "decision_brief_version", "selected_alternative",
    "selection_rationale", "provenance", "created_date", *TEMPORAL_COLUMNS,
)
OUTCOME_COLUMNS = (
    "outcome_id", "action_id", "alert_fingerprint", "shipment_id", "dt",
    "observation_due_date", "status", "observed_date", "effect_pct",
    "outcome_version", "provenance", *TEMPORAL_COLUMNS,
)
POLICY_PROPOSAL_COLUMNS = (
    "proposal_id", "source_policy_version", "status", "observed_outcome_count",
    "success_rate_pct", "proposed_change", "simulation_config_change",
    "effective_date", "approved_by", "approved_policy_version",
    "rollback_policy_version", "provenance", "created_date", *TEMPORAL_COLUMNS,
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
        (ALERT_TABLE, "alert table"), (ACTION_TABLE, "action table"),
        (ACTION_CURRENT_VIEW, "action current view"),
        (OUTCOME_TABLE, "outcome table"),
        (POLICY_PROPOSAL_TABLE, "policy proposal table"),
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
        "targets": f"""SELECT stage_code, target_days, transport_mode, target_hours FROM {database}.{_identifier(TARGET_TABLE, 'target table')}
WHERE status = 'ACTIVE' AND effective_from <= DATE '{day}'
  AND (effective_to IS NULL OR effective_to >= DATE '{day}')""",
        "routes": f"""SELECT route_service_id, origin_port, destination_port, carrier, service_code,
service_level, p2p_target_days, p2p_target_hours, transport_mode, provider_type,
operating_carrier, origin_location_type, destination_location_type, equipment_type,
effective_from, effective_to, config_version
FROM {database}.{_identifier(ROUTE_TABLE, 'route table')}
WHERE status = 'ACTIVE' AND effective_from <= DATE '{day}'
  AND (effective_to IS NULL OR effective_to >= DATE '{day}')""",
        "rates": f"""SELECT rate_card_id, origin_port, destination_port, carrier, service_code,
equipment_type, charge_code, calculation_basis, amount, percentage_rate, currency,
effective_from, effective_to, status, config_version, transport_mode
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


def build_active_snapshot_query(logical_date: date, scope_id: str = "OPERATIONAL") -> str:
    day = logical_date.isoformat()
    columns = ", ".join(SNAPSHOT_COLUMNS)
    database = _identifier(DATABASE, "database")
    snapshot_table = _identifier(SNAPSHOT_TABLE, "snapshot table")
    scope = _sql_literal(scope_id)
    return f"""SELECT {columns}
FROM {database}.{snapshot_table} AS current_snapshot
WHERE try_cast(current_snapshot.dt AS date) = (
    SELECT max(try_cast(prior_snapshot.dt AS date))
    FROM {database}.{snapshot_table} AS prior_snapshot
    WHERE try_cast(prior_snapshot.dt AS date) < DATE '{day}'
      AND prior_snapshot.temporal_scope_id = {scope}
  )
  AND current_snapshot.temporal_scope_id = {scope}
  AND lifecycle_status = 'OPEN' AND terminal_state = false"""


def build_closed_loop_state_queries(logical_date: date, scope_id: str) -> dict[str, str]:
    """Read only the private state required to advance the governed loop."""

    day = logical_date.isoformat()
    database = _identifier(DATABASE, "database")
    scope = _sql_literal(scope_id)
    alert_table = _identifier(ALERT_TABLE, "alert table")
    return {
        "previous_alerts": f"""SELECT {', '.join(ALERT_COLUMNS)}
FROM {database}.{alert_table} AS current_alert
WHERE try_cast(current_alert.dt AS date) = (
    SELECT max(try_cast(prior_alert.dt AS date))
    FROM {database}.{alert_table} AS prior_alert
    WHERE try_cast(prior_alert.dt AS date) < DATE '{day}'
      AND prior_alert.temporal_scope_id = {scope}
  )
  AND current_alert.temporal_scope_id = {scope}""",
        "actions": f"""SELECT {', '.join(ACTION_COLUMNS)}
FROM {database}.{_identifier(ACTION_CURRENT_VIEW, 'action current view')}
WHERE temporal_scope_id = {scope}""",
        "outcomes": f"""SELECT {', '.join(OUTCOME_COLUMNS)}
FROM {database}.{_identifier(OUTCOME_TABLE, 'outcome table')}
WHERE temporal_scope_id = {scope}""",
        "proposals": f"""SELECT proposal_id
FROM {database}.{_identifier(POLICY_PROPOSAL_TABLE, 'policy proposal table')}
WHERE temporal_scope_id = {scope}""",
    }


def _coerce_closed_loop_row(row: dict[str, str | None]) -> dict[str, Any]:
    result: dict[str, Any] = dict(row)
    for field in ("approved_at", "completed_at", "updated_at"):
        if row.get(field):
            result[field] = datetime.fromisoformat(str(row[field])).replace(tzinfo=timezone.utc)
    for field in (
        "first_detected_date", "last_detected_date", "resolved_date", "created_date",
        "observation_due_date", "observed_date", "effective_date", "as_of_date",
    ):
        if row.get(field):
            result[field] = date.fromisoformat(str(row[field]))
    for field in ("metric_value", "threshold_value", "effect_pct", "success_rate_pct"):
        if row.get(field) is not None:
            result[field] = float(str(row[field]))
    if row.get("observed_outcome_count") is not None:
        result["observed_outcome_count"] = int(str(row["observed_outcome_count"]))
    for field in ("approval_required", "simulation_config_change"):
        if row.get(field) is not None:
            result[field] = str(row[field]).lower() == "true"
    return result


def build_closed_loop_rows(
    logical_date: date,
    signals: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
    previous_alerts: list[dict[str, Any]],
    existing_actions: list[dict[str, Any]],
    existing_outcomes: list[dict[str, Any]],
    existing_proposal_ids: set[str],
    policy_version: str = "decision-policy-v1",
    minimum_observed: int = 20,
) -> dict[str, list[dict[str, Any]]]:
    """Advance alerts, actions, outcomes and review-only policy proposals."""

    alerts = closed_loop.reconcile_alerts(signals, previous_alerts, logical_date)
    for row in alerts:
        row["dt"] = logical_date.isoformat()
        for field in ("first_detected_date", "last_detected_date", "resolved_date"):
            if row.get(field):
                row[field] = date.fromisoformat(str(row[field]))

    alert_by_fingerprint = {row["alert_fingerprint"]: row for row in alerts}
    known_action_ids = {str(row["action_id"]) for row in existing_actions}
    actions = []
    for row in closed_loop.propose_actions(alerts, policy_version):
        if row["action_id"] in known_action_ids:
            continue
        alert = alert_by_fingerprint[row["alert_fingerprint"]]
        row.update({
            "alert_type": alert["alert_type"],
            "alert_severity": alert["severity"],
            "created_date": logical_date,
        })
        actions.append(row)

    snapshot_by_shipment = {row["shipment_id"]: row for row in snapshots}
    prior_outcome_keys = {
        (str(row.get("outcome_id")), str(row.get("dt"))) for row in existing_outcomes
    }
    outcomes = []
    for action in existing_actions:
        if action.get("status") != "COMPLETED" or not action.get("completed_at"):
            continue
        alert = alert_by_fingerprint.get(str(action.get("alert_fingerprint"))) or {
            "alert_fingerprint": action["alert_fingerprint"],
            "alert_type": action.get("alert_type") or "SLA_BREACH",
            "severity": action.get("alert_severity") or "MEDIUM",
        }
        shipment = snapshot_by_shipment.get(str(action.get("shipment_id")), {})
        outcome = closed_loop.observe_outcome(
            action,
            alert,
            logical_date,
            context={
                "shipment_stage": shipment.get("lifecycle_stage"),
                "carrier": shipment.get("carrier"),
                "execution_delay_hours": 0,
                "active_disruption": bool(shipment.get("journey_exception_type")),
            },
        )
        outcome["dt"] = logical_date.isoformat()
        for field in ("observation_due_date", "observed_date"):
            if outcome.get(field):
                outcome[field] = date.fromisoformat(str(outcome[field]))
        key = (outcome["outcome_id"], outcome["dt"])
        if key not in prior_outcome_keys:
            outcomes.append(outcome)

    closed_history = [
        row for row in existing_outcomes
        if row.get("status") in closed_loop.OUTCOME_STATES
    ] + [row for row in outcomes if row.get("status") in closed_loop.OUTCOME_STATES]
    proposal = closed_loop.build_policy_proposal(
        closed_history, policy_version, logical_date, minimum_observed
    )
    proposals = []
    if proposal and proposal["proposal_id"] not in existing_proposal_ids:
        proposal["created_date"] = logical_date
        proposals.append(proposal)
    return {"alerts": alerts, "actions": actions, "outcomes": outcomes, "proposals": proposals}


def apply_temporal_provenance(
    rows: Iterable[dict[str, Any]], context: dict[str, str | None]
) -> None:
    """Permanently stamp every written row with its temporal identity."""

    scope_id = temporal_scope_id(context)
    for row in rows:
        row.update({
            "temporal_scope_id": scope_id,
            "execution_mode": context["execution_mode"],
            "time_basis": context["time_basis"],
            "as_of_date": date.fromisoformat(str(context["as_of_date"])),
            "execution_scenario_id": context["scenario_id"],
        })


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


def build_merge_sql(
    table: str,
    columns: tuple[str, ...],
    key_columns: tuple[str, ...],
    rows: Iterable[dict[str, Any]],
    update_matched: bool = False,
) -> list[str]:
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
        update_columns = [column for column in columns if column not in key_columns]
        matched_clause = ""
        if update_matched and update_columns:
            assignments = ", ".join(
                f"{column} = source.{column}" for column in update_columns
            )
            matched_clause = f"\nWHEN MATCHED THEN UPDATE SET {assignments}"
        statements.append(f"""MERGE INTO {_identifier(DATABASE, 'database')}.{table} AS target
USING (VALUES
{values}
) AS source ({source_columns})
ON {join}{matched_clause}
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
        "rate_locked_at", "created_at", "updated_at", "origin_handover_target_at",
        "origin_handover_at", "destination_release_target_at", "destination_release_at",
    ):
        result[field] = (
            datetime.fromisoformat(str(row[field])).replace(tzinfo=timezone.utc)
            if row.get(field) else None
        )
    result["terminal_state"] = str(row.get("terminal_state")).lower() == "true"
    for field in ("container_count", "piece_count", "journey_exception_hours"):
        result[field] = int(row[field]) if row.get(field) else 0
    for field in (
        "expected_total_cost", "accrued_total_cost", "actual_total_cost",
        "gross_weight_kg", "volume_cbm", "chargeable_weight_kg",
    ):
        result[field] = float(row[field]) if row.get(field) else None
    result["transport_mode"] = str(row.get("transport_mode") or "OCEAN")
    result["provider_type"] = str(row.get("provider_type") or (
        "OCEAN_CARRIER" if row.get("carrier") == "MAERSK" else "LOGISTICS_PROVIDER"
    ))
    result["operating_carrier"] = str(row.get("operating_carrier") or row.get("carrier") or "")
    result["origin_location_type"] = str(row.get("origin_location_type") or "PORT")
    result["destination_location_type"] = str(row.get("destination_location_type") or "PORT")
    result["origin_handover_target_at"] = result["origin_handover_target_at"] or result["gate_in_target_at"]
    result["origin_handover_at"] = result["origin_handover_at"] or result["gate_in_at"]
    result["destination_release_target_at"] = (
        result["destination_release_target_at"] or result["discharge_target_at"]
    )
    result["destination_release_at"] = result["destination_release_at"] or result["discharged_at"]
    if result["gross_weight_kg"] is None:
        result["gross_weight_kg"] = float(result["container_count"] * 24000)
    if result["volume_cbm"] is None:
        result["volume_cbm"] = float(result["container_count"] * 67.7)
    if result["chargeable_weight_kg"] is None:
        result["chargeable_weight_kg"] = result["gross_weight_kg"]
    if not result["piece_count"]:
        result["piece_count"] = result["container_count"] * 100
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
    temporal_context = resolve_temporal_context(event["logical_run_date"], event)
    scope_id = temporal_scope_id(temporal_context)
    client = boto3.client("athena", region_name=os.getenv("AWS_REGION", "us-east-1"))
    config_queries = build_configuration_queries(logical_date)
    target_rows = _run_query(client, config_queries["targets"])
    legacy_to_generic = {
        "BOOKING_TO_GATE_IN": "BOOKING_TO_ORIGIN_HANDOVER",
        "GATE_IN_TO_ETD": "ORIGIN_HANDOVER_TO_DEPARTURE",
        "ATA_TO_DISCHARGED": "ARRIVAL_TO_DESTINATION_RELEASE",
        "DISCHARGED_TO_DELIVERED": "DESTINATION_RELEASE_TO_DELIVERY",
    }
    targets: dict[str, int] = {}
    for row in target_rows:
        stage = str(row["stage_code"])
        mode = str(row.get("transport_mode") or "OCEAN")
        hours = int(str(row.get("target_hours") or int(str(row["target_days"])) * 24))
        targets[f"{mode}:{legacy_to_generic.get(stage, stage)}"] = hours
    routes = _run_query(client, config_queries["routes"])
    for row in routes:
        row["p2p_target_days"] = int(str(row["p2p_target_days"]))
        row["p2p_target_hours"] = int(str(row.get("p2p_target_hours") or row["p2p_target_days"] * 24))
    rates = _run_query(client, config_queries["rates"])
    fx_rows = _run_query(client, config_queries["fx"])
    fx_rates = {
        (str(row["base_currency"]), str(row["quote_currency"])): float(str(row["fx_rate"]))
        for row in fx_rows
    }
    active = [
        _coerce_snapshot(row)
        for row in _run_query(client, build_active_snapshot_query(logical_date, scope_id))
    ]
    closed_loop_queries = build_closed_loop_state_queries(logical_date, scope_id)
    previous_alerts = [
        _coerce_closed_loop_row(row)
        for row in _run_query(client, closed_loop_queries["previous_alerts"])
    ]
    existing_actions = [
        _coerce_closed_loop_row(row)
        for row in _run_query(client, closed_loop_queries["actions"])
    ]
    existing_outcomes = [
        _coerce_closed_loop_row(row)
        for row in _run_query(client, closed_loop_queries["outcomes"])
    ]
    existing_proposal_ids = {
        str(row["proposal_id"])
        for row in _run_query(client, closed_loop_queries["proposals"])
    }
    if not active and event.get("seed_population", False):
        active = engine.seed_population(
            logical_date, routes, targets, int(event.get("population_size", 450)),
            event.get("seed_version", "lifecycle-2026.09-multimodal-v1"), rates, fx_rates,
        )
    result = engine.run_day(
        active, logical_date, routes, targets,
        event.get("seed_version", "lifecycle-2026.09-multimodal-v1"), event.get("new_count"), rates, fx_rates,
    )
    snapshots = result.pop("snapshots")
    events = result.pop("events")
    metrics = result.pop("metrics")
    signals = result.pop("signals")
    closed_loop_rows = build_closed_loop_rows(
        logical_date,
        signals,
        snapshots,
        previous_alerts,
        existing_actions,
        existing_outcomes,
        existing_proposal_ids,
        event.get("policy_version", "decision-policy-v1"),
        int(event.get("minimum_policy_outcomes", 20)),
    )
    alerts = closed_loop_rows["alerts"]
    actions = closed_loop_rows["actions"]
    outcomes = closed_loop_rows["outcomes"]
    proposals = closed_loop_rows["proposals"]
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
    for rows in (
        snapshots, events, cost_rows, metrics, signals,
        alerts, actions, outcomes, proposals,
    ):
        apply_temporal_provenance(rows, temporal_context)
    update_matched = event.get("retry_failed_run") is True
    statements = (
        build_merge_sql(
            SNAPSHOT_TABLE, SNAPSHOT_COLUMNS,
            ("temporal_scope_id", "shipment_id", "dt"), snapshots, update_matched
        )
        + build_merge_sql(
            EVENT_TABLE, EVENT_COLUMNS, ("temporal_scope_id", "event_id"),
            events, update_matched
        )
        + build_merge_sql(
            COST_TABLE,
            COST_COLUMNS,
            ("temporal_scope_id", "shipment_id", "dt", "charge_code"),
            cost_rows,
            update_matched,
        )
        + build_merge_sql(
            METRICS_TABLE, METRICS_COLUMNS,
            ("temporal_scope_id", "shipment_id", "dt"), metrics, update_matched
        )
        + build_merge_sql(
            SIGNAL_TABLE,
            SIGNAL_COLUMNS,
            ("temporal_scope_id", "signal_fingerprint", "dt"),
            signals,
            update_matched,
        )
        + build_merge_sql(
            ALERT_TABLE,
            ALERT_COLUMNS,
            ("temporal_scope_id", "alert_fingerprint", "dt"),
            alerts,
            update_matched,
        )
        + build_merge_sql(
            ACTION_TABLE,
            ACTION_COLUMNS,
            ("temporal_scope_id", "action_id"),
            actions,
            False,
        )
        + build_merge_sql(
            OUTCOME_TABLE,
            OUTCOME_COLUMNS,
            ("temporal_scope_id", "outcome_id", "dt"),
            outcomes,
            update_matched,
        )
        + build_merge_sql(
            POLICY_PROPOSAL_TABLE,
            POLICY_PROPOSAL_COLUMNS,
            ("temporal_scope_id", "proposal_id"),
            proposals,
            False,
        )
    )
    if not event.get("dry_run", False):
        for statement in statements:
            _run_query(client, statement)
    return {
        **result,
        **temporal_context,
        "cost_rows_created": len(cost_rows),
        "metric_rows_created": len(metrics),
        "signal_rows_created": len(signals),
        "alert_rows_created": len(alerts),
        "action_rows_created": len(actions),
        "outcome_rows_created": len(outcomes),
        "policy_proposal_rows_created": len(proposals),
        "write_statements": len(statements),
        "dry_run": bool(event.get("dry_run", False)),
    }
