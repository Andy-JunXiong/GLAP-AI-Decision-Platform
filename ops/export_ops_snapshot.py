"""Export public-safe GLAP operational analytics from Athena.

The exporter publishes aggregate counts, stage freshness, daily totals, and a
transparent seven-day volume baseline. It never exports shipment identifiers,
entity keys, routes, carriers, query locations, account identifiers, or ARNs.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import time
from typing import Any


DEFAULT_DATABASE = "curated_iceberg"
DEFAULT_WORKGROUP = "primary"
HISTORY_DAYS = 28
FORECAST_HORIZON_DAYS = 7
MAX_STAGE_LAG_DAYS = 1
TERMINAL_FAILURE_STATES = {"FAILED", "CANCELLED"}
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SAFE_PUBLIC_STAGE = re.compile(r"^[a-z][a-z0-9_]{1,47}$")
PIPELINE_RUN_SUCCESS = {"success", "succeeded"}
PIPELINE_QUALITY_CHECKS = {
    "missing_dates",
    "empty_inputs",
    "duplicate_business_keys",
    "abnormal_volume_change",
    "stale_stage_outputs",
}
SAFE_FAILURE_CATEGORIES = {
    "dependency_failure",
    "invalid_response",
    "quality_contract_invalid",
    "quality_gate_failed",
    "unexpected_failure",
    "status_unavailable",
}
PIPELINE_RUNBOOK_URL = (
    "https://github.com/Andy-JunXiong/GLAP-AI-Decision-Platform/"
    "blob/main/docs/runbooks/pipeline_reliability.md"
)

CURRENT_CONTRACT_TABLES = (
    "fact_shipment_events_extended_iceberg",
    "fact_ai_alerts_v3",
    "fact_ai_insights_v3",
    "fact_ai_decisions_v3",
    "fact_ai_actions_v2",
    "fact_ai_outcomes_v2",
    "fact_ai_learning_v1",
)

STAGE_DATE_COLUMNS = {
    "shipments": "latest_shipment_date",
    "alerts": "latest_alert_date",
    "root_causes": "latest_insight_date",
    "decisions": "latest_decision_date",
    "actions": "latest_action_date",
    "outcomes": "latest_outcome_date",
    "learning": "latest_learning_date",
}


def validate_identifier(value: str, label: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"Invalid {label}: {value!r}")
    return value


def build_query(database: str) -> str:
    """Build the current-flywheel KPI query.

    Counts are taken at each stage's own latest logical run date. The returned
    stage dates allow the publisher and UI to expose partial pipeline lag.
    """

    database = validate_identifier(database, "Athena database")
    return f"""
WITH latest_shipment AS (
    SELECT max(CAST(event_time AS date)) AS run_date
    FROM {database}.fact_shipment_events_extended_iceberg
),
latest_alert AS (
    SELECT max(run_date) AS run_date FROM {database}.fact_ai_alerts_v3
),
latest_insight AS (
    SELECT max(run_date) AS run_date FROM {database}.fact_ai_insights_v3
),
latest_decision AS (
    SELECT max(run_date) AS run_date FROM {database}.fact_ai_decisions_v3
),
latest_action AS (
    SELECT max(run_date) AS run_date FROM {database}.fact_ai_actions_v2
),
latest_outcome AS (
    SELECT max(run_date) AS run_date FROM {database}.fact_ai_outcomes_v2
),
latest_learning AS (
    SELECT max(run_date) AS run_date FROM {database}.fact_ai_learning_v1
),
shipment_counts AS (
    SELECT
        count(DISTINCT shipment_id) AS shipments_generated,
        count(DISTINCT CASE
            WHEN upper(status) IN ('AT_RISK', 'BREACHED', 'DELAYED', 'EXCEPTION')
            THEN shipment_id END) AS shipments_at_risk
    FROM {database}.fact_shipment_events_extended_iceberg
    CROSS JOIN latest_shipment
    WHERE CAST(event_time AS date) = latest_shipment.run_date
),
alert_counts AS (
    SELECT count(*) AS alerts_generated
    FROM {database}.fact_ai_alerts_v3 CROSS JOIN latest_alert
    WHERE fact_ai_alerts_v3.run_date = latest_alert.run_date
),
insight_counts AS (
    SELECT count(*) AS root_causes_generated
    FROM {database}.fact_ai_insights_v3 CROSS JOIN latest_insight
    WHERE fact_ai_insights_v3.run_date = latest_insight.run_date
),
decision_counts AS (
    SELECT count(*) AS decisions_generated
    FROM {database}.fact_ai_decisions_v3 CROSS JOIN latest_decision
    WHERE fact_ai_decisions_v3.run_date = latest_decision.run_date
),
action_counts AS (
    SELECT
        count(*) AS actions_generated,
        sum(CASE WHEN upper(coalesce(status, '')) IN
            ('COMPLETED', 'EXECUTED', 'CLOSED', 'DONE') THEN 1 ELSE 0 END) AS actions_completed,
        sum(CASE WHEN upper(coalesce(status, '')) NOT IN
            ('COMPLETED', 'EXECUTED', 'CLOSED', 'DONE') THEN 1 ELSE 0 END) AS actions_open
    FROM {database}.fact_ai_actions_v2 CROSS JOIN latest_action
    WHERE fact_ai_actions_v2.run_date = latest_action.run_date
),
outcome_counts AS (
    SELECT
        count(*) AS outcomes_generated,
        avg(improvement_pct) AS avg_outcome_improvement_pct,
        avg(effectiveness_score) AS avg_effectiveness_score,
        100.0 * sum(CASE WHEN improvement_pct > 0 THEN 1 ELSE 0 END)
            / nullif(count(*), 0) AS outcome_success_rate_pct
    FROM {database}.fact_ai_outcomes_v2 CROSS JOIN latest_outcome
    WHERE fact_ai_outcomes_v2.run_date = latest_outcome.run_date
),
learning_counts AS (
    SELECT count(*) AS learning_records_generated
    FROM {database}.fact_ai_learning_v1 CROSS JOIN latest_learning
    WHERE fact_ai_learning_v1.run_date = latest_learning.run_date
)
SELECT
    CAST(latest_shipment.run_date AS varchar) AS latest_shipment_date,
    CAST(latest_alert.run_date AS varchar) AS latest_alert_date,
    CAST(latest_insight.run_date AS varchar) AS latest_insight_date,
    CAST(latest_decision.run_date AS varchar) AS latest_decision_date,
    CAST(latest_action.run_date AS varchar) AS latest_action_date,
    CAST(latest_outcome.run_date AS varchar) AS latest_outcome_date,
    CAST(latest_learning.run_date AS varchar) AS latest_learning_date,
    shipments_generated,
    shipments_at_risk,
    alerts_generated,
    root_causes_generated,
    decisions_generated,
    actions_generated,
    actions_completed,
    actions_open,
    outcomes_generated,
    learning_records_generated,
    avg_outcome_improvement_pct,
    avg_effectiveness_score,
    outcome_success_rate_pct
FROM latest_shipment
CROSS JOIN latest_alert
CROSS JOIN latest_insight
CROSS JOIN latest_decision
CROSS JOIN latest_action
CROSS JOIN latest_outcome
CROSS JOIN latest_learning
CROSS JOIN shipment_counts
CROSS JOIN alert_counts
CROSS JOIN insight_counts
CROSS JOIN decision_counts
CROSS JOIN action_counts
CROSS JOIN outcome_counts
CROSS JOIN learning_counts
""".strip()


def build_history_query(database: str, history_days: int = HISTORY_DAYS) -> str:
    """Build a public-safe daily shipment history query for forecasting."""

    database = validate_identifier(database, "Athena database")
    if not 7 <= history_days <= 90:
        raise ValueError("history_days must be between 7 and 90")
    return f"""
WITH latest AS (
    SELECT max(CAST(event_time AS date)) AS latest_date
    FROM {database}.fact_shipment_events_extended_iceberg
)
SELECT
    CAST(CAST(event_time AS date) AS varchar) AS metric_date,
    count(DISTINCT shipment_id) AS shipments_generated,
    count(DISTINCT CASE
        WHEN upper(status) IN ('AT_RISK', 'BREACHED', 'DELAYED', 'EXCEPTION')
        THEN shipment_id END) AS shipments_at_risk
FROM {database}.fact_shipment_events_extended_iceberg
CROSS JOIN latest
WHERE CAST(event_time AS date)
    BETWEEN date_add('day', -{history_days - 1}, latest.latest_date) AND latest.latest_date
GROUP BY CAST(event_time AS date)
ORDER BY CAST(event_time AS date)
""".strip()


def _cell_value(cell: dict[str, str]) -> str | None:
    return cell.get("VarCharValue")


def parse_athena_rows(response: dict[str, Any]) -> list[dict[str, str | None]]:
    rows = response.get("ResultSet", {}).get("Rows", [])
    if len(rows) < 2:
        raise ValueError("Athena OPS query returned no data rows")
    headers = [_cell_value(cell) for cell in rows[0].get("Data", [])]
    if not headers or any(header is None for header in headers):
        raise ValueError("Athena OPS query returned invalid headers")

    parsed: list[dict[str, str | None]] = []
    for result_row in rows[1:]:
        values = [_cell_value(cell) for cell in result_row.get("Data", [])]
        if len(values) > len(headers):
            raise ValueError("Athena OPS query returned more values than headers")
        values.extend([None] * (len(headers) - len(values)))
        parsed.append(dict(zip(headers, values)))
    return parsed


def parse_athena_result(response: dict[str, Any]) -> dict[str, str | None]:
    """Return the first data row for single-row aggregate queries."""

    return parse_athena_rows(response)[0]


def _optional_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _optional_float(value: str | None, digits: int = 2) -> float | None:
    if value in (None, ""):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return round(number, digits)


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _safe_timestamp(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_pipeline_health(
    pipeline_run: dict[str, Any] | None,
    newest_date: date,
    required: bool,
) -> tuple[dict[str, Any], bool]:
    """Return a sanitized pipeline view and whether it proves current success."""

    if not pipeline_run:
        status = "unverified" if required else "date_inferred"
        return (
            {
                "status": status,
                "verification_mode": "pipeline_run" if required else "stage_dates_only",
                "logical_run_date": None,
                "started_at": None,
                "completed_at": None,
                "duration_ms": None,
                "failed_stage": None,
                "failure_category": "status_unavailable" if required else None,
                "stages": [],
                "runbook_url": PIPELINE_RUNBOOK_URL,
            },
            not required,
        )

    try:
        logical_date = _date(str(pipeline_run.get("logical_run_date") or ""))
    except ValueError:
        logical_date = None
    raw_stages = pipeline_run.get("stages")
    if not isinstance(raw_stages, list):
        raw_stages = []
    stages = []
    quality_gate_verified = False
    for raw_stage in raw_stages:
        if not isinstance(raw_stage, dict):
            continue
        checks = raw_stage.get("quality_checks")
        safe_checks = []
        if isinstance(checks, list):
            for check in checks:
                if not isinstance(check, dict):
                    continue
                name = str(check.get("name") or "")
                check_status = str(check.get("status") or "").lower()
                if name in PIPELINE_QUALITY_CHECKS and check_status in {"passed", "failed"}:
                    safe_checks.append({"name": name, "status": check_status})
            if (
                {check["name"] for check in safe_checks} == PIPELINE_QUALITY_CHECKS
                and all(check["status"] == "passed" for check in safe_checks)
            ):
                quality_gate_verified = True
        failure_category = str(raw_stage.get("failure_category") or "") or None
        if failure_category not in SAFE_FAILURE_CATEGORIES:
            failure_category = "unexpected_failure" if failure_category else None
        stage_name = str(raw_stage.get("name") or "")
        if not SAFE_PUBLIC_STAGE.fullmatch(stage_name):
            stage_name = "unknown"
        stages.append(
            {
                "name": stage_name,
                "started_at": _safe_timestamp(raw_stage.get("started_at")),
                "completed_at": _safe_timestamp(raw_stage.get("completed_at")),
                "duration_ms": int(raw_stage["duration_ms"])
                if isinstance(raw_stage.get("duration_ms"), (int, float))
                and raw_stage["duration_ms"] >= 0
                else None,
                "status": str(raw_stage.get("status") or "unknown").lower(),
                "failure_category": failure_category,
                "quality_checks": safe_checks,
            }
        )

    run_status = str(pipeline_run.get("status") or "unknown").lower()
    failure_category = str(pipeline_run.get("failure_category") or "") or None
    if failure_category not in SAFE_FAILURE_CATEGORIES:
        failure_category = "unexpected_failure" if failure_category else None
    logical_date_current = logical_date == newest_date
    all_stages_succeeded = bool(stages) and all(stage["status"] == "succeeded" for stage in stages)
    verified = (
        run_status in PIPELINE_RUN_SUCCESS
        and logical_date_current
        and all_stages_succeeded
        and quality_gate_verified
    )
    if verified:
        public_status = "current"
    elif run_status == "failed":
        public_status = "failed"
    elif run_status == "running":
        public_status = "running"
    else:
        public_status = "unverified"

    duration_ms = None
    try:
        started = datetime.fromisoformat(_safe_timestamp(pipeline_run.get("started_at")) or "")
        completed = datetime.fromisoformat(_safe_timestamp(pipeline_run.get("completed_at")) or "")
        duration_ms = max(0, int((completed - started).total_seconds() * 1000))
    except (TypeError, ValueError):
        pass

    return (
        {
            "status": public_status,
            "verification_mode": "pipeline_run",
            "logical_run_date": logical_date.isoformat() if logical_date else None,
            "started_at": _safe_timestamp(pipeline_run.get("started_at")),
            "completed_at": _safe_timestamp(pipeline_run.get("completed_at")),
            "duration_ms": duration_ms,
            "failed_stage": (
                str(pipeline_run.get("failed_stage"))
                if SAFE_PUBLIC_STAGE.fullmatch(str(pipeline_run.get("failed_stage") or ""))
                else None
            ),
            "failure_category": failure_category,
            "stages": stages,
            "runbook_url": PIPELINE_RUNBOOK_URL,
        },
        verified,
    )


def build_volume_forecast(
    history_rows: list[dict[str, str | None]],
    history_days: int = HISTORY_DAYS,
    horizon_days: int = FORECAST_HORIZON_DAYS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a deterministic OLS daily-volume baseline and public analytics."""

    if not history_rows:
        return (
            {
                "window_days": history_days,
                "observed_days": 0,
                "data_completeness_pct": 0.0,
                "latest_daily_shipments": None,
                "latest_risk_rate_pct": None,
            },
            {
                "status": "insufficient_data",
                "method": "ordinary_least_squares_28d",
                "horizon_days": horizon_days,
                "points": [],
                "history": [],
            },
        )

    observed: dict[date, tuple[int, int]] = {}
    for row in history_rows:
        metric_date = _date(row.get("metric_date"))
        if metric_date is None:
            continue
        observed[metric_date] = (
            _optional_int(row.get("shipments_generated")) or 0,
            _optional_int(row.get("shipments_at_risk")) or 0,
        )
    if not observed:
        return build_volume_forecast([], history_days, horizon_days)

    anchor = max(observed)
    start = anchor - timedelta(days=history_days - 1)
    dates = [start + timedelta(days=index) for index in range(history_days)]
    volumes = [float(observed.get(day, (0, 0))[0]) for day in dates]
    risks = [observed.get(day, (0, 0))[1] for day in dates]
    x_values = list(range(history_days))
    x_mean = sum(x_values) / history_days
    y_mean = sum(volumes) / history_days
    denominator = sum((x - x_mean) ** 2 for x in x_values)
    slope = (
        sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, volumes)) / denominator
        if denominator
        else 0.0
    )
    intercept = y_mean - slope * x_mean
    residuals = [y - (intercept + slope * x) for x, y in zip(x_values, volumes)]
    residual_sigma = math.sqrt(sum(value * value for value in residuals) / max(1, history_days - 2))
    latest_volume = int(volumes[-1])
    latest_risk = risks[-1]
    latest_risk_rate = 100.0 * latest_risk / latest_volume if latest_volume else 0.0

    points = []
    for horizon in range(1, horizon_days + 1):
        predicted = max(0, int(round(intercept + slope * (history_days - 1 + horizon))))
        interval = max(1, int(round(1.96 * residual_sigma)))
        points.append(
            {
                "date": (anchor + timedelta(days=horizon)).isoformat(),
                "predicted_shipments": predicted,
                "lower_bound": max(0, predicted - interval),
                "upper_bound": predicted + interval,
                "predicted_at_risk": int(round(predicted * latest_risk_rate / 100.0)),
            }
        )

    observed_days = sum(1 for day in dates if day in observed)
    analytics = {
        "window_days": history_days,
        "observed_days": observed_days,
        "data_completeness_pct": round(100.0 * observed_days / history_days, 1),
        "latest_daily_shipments": latest_volume,
        "average_daily_shipments": round(y_mean, 1),
        "latest_risk_rate_pct": round(latest_risk_rate, 1),
        "daily_volume_trend_pct": round(100.0 * slope / y_mean, 2) if y_mean else 0.0,
    }
    forecast = {
        "status": "ready" if observed_days >= 7 else "insufficient_data",
        "method": "ordinary_least_squares_28d",
        "method_label": "28-day linear trend baseline",
        "horizon_days": horizon_days,
        "predicted_shipments_7d": sum(point["predicted_shipments"] for point in points),
        "points": points,
        "history": [
            {
                "date": day.isoformat(),
                "shipments": int(volume),
                "shipments_at_risk": risk,
            }
            for day, volume, risk in zip(dates[-14:], volumes[-14:], risks[-14:])
        ],
        "disclosure": "Statistical baseline, not a committed operational target or autonomous decision.",
    }
    return analytics, forecast


def build_snapshot(
    row: dict[str, str | None],
    history_rows: list[dict[str, str | None]] | None = None,
    now: datetime | None = None,
    pipeline_run: dict[str, Any] | None = None,
    pipeline_status_required: bool = False,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    stage_dates = {stage: _date(row.get(column)) for stage, column in STAGE_DATE_COLUMNS.items()}
    available_dates = [value for value in stage_dates.values() if value is not None]
    if not available_dates:
        raise ValueError("Athena OPS query did not return a source date")
    newest_date = max(available_dates)
    source_updated_at = datetime.combine(newest_date, datetime.min.time(), tzinfo=timezone.utc)
    age_hours = max(0, int((now - source_updated_at).total_seconds() // 3600))

    stage_freshness: dict[str, Any] = {}
    for stage, stage_date in stage_dates.items():
        lag_days = (newest_date - stage_date).days if stage_date else None
        stage_freshness[stage] = {
            "as_of_date": stage_date.isoformat() if stage_date else None,
            "lag_days": lag_days,
            "status": "current" if lag_days is not None and lag_days <= MAX_STAGE_LAG_DAYS else "stale",
        }
    max_stage_lag = max(
        (stage["lag_days"] for stage in stage_freshness.values() if stage["lag_days"] is not None),
        default=999,
    )
    stage_dates_current = all(stage["status"] == "current" for stage in stage_freshness.values())
    pipeline_health, run_verified = _safe_pipeline_health(
        pipeline_run, newest_date, pipeline_status_required
    )
    pipeline_current = stage_dates_current and run_verified
    fresh = age_hours <= 36 and pipeline_current

    metrics = {
        "shipments_generated": _optional_int(row.get("shipments_generated")),
        "shipments_at_risk": _optional_int(row.get("shipments_at_risk")),
        "alerts_generated": _optional_int(row.get("alerts_generated")),
        "root_causes_generated": _optional_int(row.get("root_causes_generated")),
        "decisions_generated": _optional_int(row.get("decisions_generated")),
        "actions_generated": _optional_int(row.get("actions_generated")),
        "actions_completed": _optional_int(row.get("actions_completed")),
        "actions_open": _optional_int(row.get("actions_open")),
        "outcomes_generated": _optional_int(row.get("outcomes_generated")),
        "learning_records_generated": _optional_int(row.get("learning_records_generated")),
    }
    analytics, forecast = build_volume_forecast(history_rows or [])
    analytics.update(
        {
            "action_completion_rate_pct": round(
                100.0 * (metrics["actions_completed"] or 0) / metrics["actions_generated"], 1
            )
            if metrics["actions_generated"]
            else None,
            "outcome_success_rate_pct": _optional_float(row.get("outcome_success_rate_pct"), 1),
            "avg_outcome_improvement_pct": _optional_float(row.get("avg_outcome_improvement_pct"), 1),
            "avg_effectiveness_score": _optional_float(row.get("avg_effectiveness_score"), 2),
            "max_stage_lag_days": max_stage_lag,
        }
    )

    return {
        "schema_version": "1.2",
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "source_updated_at": source_updated_at.isoformat().replace("+00:00", "Z"),
        "as_of_date": newest_date.isoformat(),
        "provenance": {
            "source_type": "athena_iceberg_aggregate",
            "connection": "scheduled_github_oidc_export",
            "label": "Scheduled AWS OPS analytics",
            "is_connected": True,
            "disclosure": "Public-safe aggregate analytics; no operational records or identifiers are exported.",
        },
        "freshness": {
            "status": "fresh" if fresh else "stale",
            "age_hours": age_hours,
            "max_age_hours": 36,
        },
        "stage_freshness": stage_freshness,
        "metrics": metrics,
        "analytics": analytics,
        "forecast": forecast,
        "pipeline": {
            **pipeline_health,
            "status": (
                "current"
                if pipeline_current
                else (
                    pipeline_health["status"]
                    if pipeline_health["status"] in {"failed", "running", "unverified"}
                    else "partial_or_stale"
                )
            ),
            "max_stage_lag_days": max_stage_lag,
            "query_checks_succeeded": 2,
            "query_checks_total": 2,
        },
    }


def load_pipeline_run(client: Any, status_uri: str) -> dict[str, Any]:
    parsed = urlparse(status_uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.lstrip("/"):
        raise ValueError("PIPELINE_STATUS_S3_URI must be a complete s3:// URI")
    response = client.get_object(Bucket=parsed.netloc, Key=parsed.path.lstrip("/"))
    value = json.loads(response["Body"].read())
    if not isinstance(value, dict):
        raise ValueError("Pipeline status object must contain a JSON object")
    return value


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

    return client.get_query_results(QueryExecutionId=execution_id, MaxResults=1000)


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

    region = os.getenv("AWS_REGION", "us-east-1")
    client = boto3.client("athena", region_name=region)
    metric_response = run_query(client, build_query(database), database, output, workgroup)
    history_response = run_query(client, build_history_query(database), database, output, workgroup)
    pipeline_status_uri = os.getenv("PIPELINE_STATUS_S3_URI")
    pipeline_status_required = os.getenv("PIPELINE_STATUS_REQUIRED", "false").lower() == "true"
    pipeline_run = None
    if pipeline_status_uri:
        try:
            pipeline_run = load_pipeline_run(
                boto3.client("s3", region_name=region), pipeline_status_uri
            )
        except Exception:
            if not pipeline_status_required:
                raise
            # Required verification fails closed while still allowing Pages to
            # publish an explicit stale/unverified state.
            pipeline_run = None
    snapshot = build_snapshot(
        parse_athena_result(metric_response),
        parse_athena_rows(history_response),
        pipeline_run=pipeline_run,
        pipeline_status_required=pipeline_status_required,
    )
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
