"""Export a public-safe GLAP OPS aggregate from Athena.

The exporter deliberately publishes counts and dates only. It never exports
shipment identifiers, entity keys, carrier names, query result locations,
account identifiers, or ARNs.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
from typing import Any


DEFAULT_DATABASE = "curated_iceberg"
DEFAULT_WORKGROUP = "primary"
TERMINAL_FAILURE_STATES = {"FAILED", "CANCELLED"}
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_identifier(value: str, label: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"Invalid {label}: {value!r}")
    return value


def build_query(database: str) -> str:
    database = validate_identifier(database, "Athena database")
    return f"""
WITH latest_shipment AS (
    SELECT max(CAST(event_time AS date)) AS snapshot_date
    FROM {database}.fact_shipment_events_extended_iceberg
),
shipment_counts AS (
    SELECT
        count(DISTINCT shipment_id) AS shipments_generated,
        count(DISTINCT CASE
            WHEN upper(status) IN ('AT_RISK', 'BREACHED', 'DELAYED', 'EXCEPTION')
            THEN shipment_id END) AS shipments_at_risk
    FROM {database}.fact_shipment_events_extended_iceberg
    CROSS JOIN latest_shipment
    WHERE CAST(event_time AS date) = latest_shipment.snapshot_date
),
latest_run AS (
    SELECT max(run_date) AS run_date
    FROM {database}.fact_ai_anomaly_scores_v1
),
alert_counts AS (
    SELECT count(*) AS alerts_generated
    FROM {database}.fact_ai_anomaly_scores_v1
    CROSS JOIN latest_run
    WHERE fact_ai_anomaly_scores_v1.run_date = latest_run.run_date
      AND anomaly_flag = 1
),
root_cause_counts AS (
    SELECT count(*) AS root_causes_generated
    FROM {database}.fact_ai_root_cause_v1
    CROSS JOIN latest_run
    WHERE fact_ai_root_cause_v1.run_date = latest_run.run_date
),
decision_counts AS (
    SELECT count(*) AS decisions_generated
    FROM {database}.fact_ai_decision_explanations_v1
    CROSS JOIN latest_run
    WHERE fact_ai_decision_explanations_v1.run_date = latest_run.run_date
)
SELECT
    CAST(latest_shipment.snapshot_date AS varchar) AS latest_shipment_date,
    CAST(latest_run.run_date AS varchar) AS latest_run_date,
    shipments_generated,
    shipments_at_risk,
    alerts_generated,
    root_causes_generated,
    decisions_generated
FROM latest_shipment
CROSS JOIN latest_run
CROSS JOIN shipment_counts
CROSS JOIN alert_counts
CROSS JOIN root_cause_counts
CROSS JOIN decision_counts
""".strip()


def _cell_value(cell: dict[str, str]) -> str | None:
    return cell.get("VarCharValue")


def parse_athena_result(response: dict[str, Any]) -> dict[str, str | None]:
    rows = response.get("ResultSet", {}).get("Rows", [])
    if len(rows) < 2:
        raise ValueError("Athena OPS query returned no data row")
    headers = [_cell_value(cell) for cell in rows[0].get("Data", [])]
    values = [_cell_value(cell) for cell in rows[1].get("Data", [])]
    if not headers or any(header is None for header in headers):
        raise ValueError("Athena OPS query returned invalid headers")
    if len(values) > len(headers):
        raise ValueError("Athena OPS query returned more values than headers")
    values.extend([None] * (len(headers) - len(values)))
    return dict(zip(headers, values))


def _optional_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def build_snapshot(row: dict[str, str | None], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    source_dates = [value for key, value in row.items() if key.endswith("_date") and value]
    if not source_dates:
        raise ValueError("Athena OPS query did not return a source date")
    as_of_date = max(source_dates)
    source_updated_at = datetime.fromisoformat(f"{as_of_date}T00:00:00+00:00")
    age_hours = max(0, int((now - source_updated_at).total_seconds() // 3600))

    metrics = {
        "shipments_generated": _optional_int(row.get("shipments_generated")),
        "shipments_at_risk": _optional_int(row.get("shipments_at_risk")),
        "alerts_generated": _optional_int(row.get("alerts_generated")),
        "root_causes_generated": _optional_int(row.get("root_causes_generated")),
        "decisions_generated": _optional_int(row.get("decisions_generated")),
        # These tables are not part of the verified public DDL contract yet.
        "actions_generated": None,
        "outcomes_generated": None,
    }

    return {
        "schema_version": "1.0",
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "source_updated_at": source_updated_at.isoformat().replace("+00:00", "Z"),
        "as_of_date": as_of_date,
        "provenance": {
            "source_type": "athena_iceberg_aggregate",
            "connection": "scheduled_github_oidc_export",
            "label": "Scheduled AWS OPS snapshot",
            "is_connected": True,
            "disclosure": "Public-safe aggregate counts; no operational records or identifiers are exported.",
        },
        "freshness": {
            "status": "fresh" if age_hours <= 36 else "stale",
            "age_hours": age_hours,
            "max_age_hours": 36,
        },
        "metrics": metrics,
        "pipeline": {
            "status": "current" if age_hours <= 36 else "stale",
            "query_checks_succeeded": 1,
            "query_checks_total": 1,
        },
    }


def run_query(client: Any, query: str, database: str, output: str, workgroup: str) -> dict[str, Any]:
    execution_id = client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={"Database": database},
        ResultConfiguration={"OutputLocation": output},
        WorkGroup=workgroup,
    )["QueryExecutionId"]

    deadline = time.monotonic() + 120
    while True:
        execution = client.get_query_execution(QueryExecutionId=execution_id)["QueryExecution"]
        state = execution["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in TERMINAL_FAILURE_STATES:
            reason = execution["Status"].get("StateChangeReason", "Unknown Athena error")
            raise RuntimeError(f"Athena OPS query {state.lower()}: {reason}")
        if time.monotonic() >= deadline:
            client.stop_query_execution(QueryExecutionId=execution_id)
            raise TimeoutError("Athena OPS query timed out after 120 seconds")
        time.sleep(1)

    return client.get_query_results(QueryExecutionId=execution_id, MaxResults=2)


def export_snapshot(output_path: Path) -> dict[str, Any]:
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - exercised in AWS workflow
        raise RuntimeError("boto3 is required for an AWS OPS export") from exc

    database = validate_identifier(os.getenv("ATHENA_DATABASE") or DEFAULT_DATABASE, "Athena database")
    workgroup = os.getenv("ATHENA_WORKGROUP") or DEFAULT_WORKGROUP
    output = os.environ.get("ATHENA_OUTPUT")
    if not output:
        raise ValueError("ATHENA_OUTPUT is required")

    client = boto3.client("athena", region_name=os.getenv("AWS_REGION", "us-east-1"))
    response = run_query(client, build_query(database), database, output, workgroup)
    snapshot = build_snapshot(parse_athena_result(response))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("offline/data/ops-snapshot.json"),
        help="Path for the public-safe snapshot JSON",
    )
    args = parser.parse_args()
    snapshot = export_snapshot(args.output)
    print(
        f"Wrote {args.output} from {snapshot['provenance']['label']} "
        f"as of {snapshot['as_of_date']} ({snapshot['freshness']['status']})"
    )


if __name__ == "__main__":
    main()
