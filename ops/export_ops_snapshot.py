"""Export public-safe GLAP operational analytics from Athena.

The exporter publishes aggregate counts, stage freshness, daily totals, and a
transparent seven-day volume baseline. It never exports shipment or customer
identifiers, entity keys, query locations, account identifiers, or ARNs.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_DATABASE = "curated_iceberg"
DEFAULT_SOURCE_DATABASE = "simulated_iceberg_m"
DEFAULT_WORKGROUP = "primary"
HISTORY_DAYS = 28
FORECAST_HORIZON_DAYS = 7
MAX_STAGE_LAG_DAYS = 1
MIN_ENGINEERING_DELIVERED_SHIPMENTS = 200
TERMINAL_FAILURE_STATES = {"FAILED", "CANCELLED"}
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SAFE_PUBLIC_STAGE = re.compile(r"^[a-z][a-z0-9_]{1,47}$")
SAFE_ANALYTIC_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _./&()'\-]{0,79}$")
PIPELINE_RUN_SUCCESS = {"success", "succeeded"}
PIPELINE_QUALITY_CHECKS = {
    "missing_dates",
    "empty_inputs",
    "duplicate_business_keys",
    "abnormal_volume_change",
    "stale_stage_outputs",
}
PIPELINE_STAGE_ORDER = (
    "generation",
    "raw_to_iceberg",
    "input_validation",
    "decision_pipeline",
    "decision_flywheel",
    "output_validation",
)
PIPELINE_QUALITY_STAGES = ("input_validation", "output_validation")
PIPELINE_QUALITY_CHECK_TOTAL = len(PIPELINE_QUALITY_CHECKS) * len(
    PIPELINE_QUALITY_STAGES
)
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
    "fact_ai_alerts_v3",
    "fact_ai_insights_v3",
    "fact_ai_decisions_v3",
    "fact_ai_actions_v2",
    "fact_ai_outcomes_v2",
    "fact_ai_learning_v1",
)

CURRENT_SOURCE_TABLES = (
    "fact_shipment_v2",
    "fact_shipment_lifecycle_staging_v1",
    "fact_shipment_lifecycle_metrics_staging_v1",
    "fact_shipment_signal_candidate_staging_v1",
)
CURRENT_ANALYTICS_VIEWS = (
    "vw_multimodal_shipment_daily_context_v1",
    "vw_multimodal_operational_baseline_v1",
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


def validate_logical_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("logical date must use YYYY-MM-DD") from exc


def resolve_analysis_date(
    pipeline_run: dict[str, Any] | None,
    now: datetime | None = None,
) -> date:
    """Use the governed run date, never a future event timestamp, as the anchor."""

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    try:
        current_sydney_date = now.astimezone(ZoneInfo("Australia/Sydney")).date()
    except ZoneInfoNotFoundError:
        # Minimal Windows Python installations may omit the IANA tz database.
        # The governed pipeline date remains authoritative; UTC is only the
        # conservative fallback when no run contract is available.
        current_sydney_date = now.astimezone(timezone.utc).date()
    if pipeline_run:
        try:
            logical_date = validate_logical_date(str(pipeline_run.get("logical_run_date") or ""))
        except ValueError:
            logical_date = None
        if logical_date and logical_date <= current_sydney_date:
            return logical_date
    return current_sydney_date


def build_query(
    database: str,
    logical_run_date: str | date,
    source_database: str = DEFAULT_SOURCE_DATABASE,
) -> str:
    """Build the current-flywheel KPI query.

    Counts are taken at each stage's own latest logical run date. The returned
    stage dates allow the publisher and UI to expose partial pipeline lag.
    """

    database = validate_identifier(database, "Athena database")
    source_database = validate_identifier(source_database, "Athena source database")
    logical_date = validate_logical_date(logical_run_date).isoformat()
    return f"""
WITH params AS (
    SELECT DATE '{logical_date}' AS logical_run_date
),
latest_shipment AS (
    SELECT max(try_cast(dt AS date)) AS run_date
    FROM {source_database}.fact_shipment_v2
    CROSS JOIN params
    WHERE try_cast(dt AS date) <= params.logical_run_date
),
latest_alert AS (
    SELECT max(run_date) AS run_date FROM {database}.fact_ai_alerts_v3 CROSS JOIN params
    WHERE run_date <= params.logical_run_date
),
latest_insight AS (
    SELECT max(run_date) AS run_date FROM {database}.fact_ai_insights_v3 CROSS JOIN params
    WHERE run_date <= params.logical_run_date
),
latest_decision AS (
    SELECT max(run_date) AS run_date FROM {database}.fact_ai_decisions_v3 CROSS JOIN params
    WHERE run_date <= params.logical_run_date
),
latest_action AS (
    SELECT max(run_date) AS run_date FROM {database}.fact_ai_actions_v2 CROSS JOIN params
    WHERE run_date <= params.logical_run_date
),
latest_outcome AS (
    SELECT max(run_date) AS run_date FROM {database}.fact_ai_outcomes_v2 CROSS JOIN params
    WHERE run_date <= params.logical_run_date
),
latest_learning AS (
    SELECT max(run_date) AS run_date FROM {database}.fact_ai_learning_v1 CROSS JOIN params
    WHERE run_date <= params.logical_run_date
),
shipment_counts AS (
    SELECT
        count(DISTINCT shipment_id) AS shipments_generated
    FROM {source_database}.fact_shipment_v2
    CROSS JOIN latest_shipment
    WHERE try_cast(dt AS date) = latest_shipment.run_date
),
risk_keys AS (
    SELECT DISTINCT route_id, carrier, ship_mode
    FROM {database}.fact_ai_alerts_v3
    CROSS JOIN latest_alert
    WHERE fact_ai_alerts_v3.run_date = latest_alert.run_date
),
shipment_risk_counts AS (
    SELECT count(DISTINCT shipments.shipment_id) AS shipments_at_risk
    FROM {source_database}.fact_shipment_v2 AS shipments
    JOIN risk_keys
      ON lower(trim(shipments.route_id)) = lower(trim(risk_keys.route_id))
     AND lower(trim(shipments.carrier)) = lower(trim(risk_keys.carrier))
     AND lower(trim(shipments.ship_mode)) = lower(trim(risk_keys.ship_mode))
    CROSS JOIN latest_shipment
    WHERE try_cast(shipments.dt AS date) = latest_shipment.run_date
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
            ('COMPLETED', 'EXECUTED', 'CLOSED', 'DONE') THEN 1 ELSE 0 END) AS actions_open,
        100.0 * sum(CASE WHEN upper(coalesce(status, '')) IN
            ('COMPLETED', 'EXECUTED', 'CLOSED', 'DONE') THEN 1 ELSE 0 END)
            / nullif(count(*), 0) AS action_completion_rate_pct
    FROM {database}.fact_ai_actions_v2 CROSS JOIN latest_action
    WHERE fact_ai_actions_v2.run_date = latest_action.run_date
),
outcome_counts AS (
    SELECT
        count(*) AS outcomes_generated,
        100.0 * avg(improvement_pct) AS avg_outcome_improvement_pct,
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
    CAST(params.logical_run_date AS varchar) AS analysis_date,
    shipments_generated,
    shipments_at_risk,
    alerts_generated,
    root_causes_generated,
    decisions_generated,
    actions_generated,
    actions_completed,
    actions_open,
    action_completion_rate_pct,
    outcomes_generated,
    learning_records_generated,
    avg_outcome_improvement_pct,
    avg_effectiveness_score,
    outcome_success_rate_pct
FROM latest_shipment
CROSS JOIN params
CROSS JOIN latest_alert
CROSS JOIN latest_insight
CROSS JOIN latest_decision
CROSS JOIN latest_action
CROSS JOIN latest_outcome
CROSS JOIN latest_learning
CROSS JOIN shipment_counts
CROSS JOIN shipment_risk_counts
CROSS JOIN alert_counts
CROSS JOIN insight_counts
CROSS JOIN decision_counts
CROSS JOIN action_counts
CROSS JOIN outcome_counts
CROSS JOIN learning_counts
""".strip()


def build_forecast_query(
    database: str,
    logical_run_date: str | date,
    history_days: int = HISTORY_DAYS,
    horizon_days: int = FORECAST_HORIZON_DAYS,
    source_database: str = DEFAULT_SOURCE_DATABASE,
) -> str:
    """Build the AWS Athena OLS baseline and its public-safe history."""

    database = validate_identifier(database, "Athena database")
    source_database = validate_identifier(source_database, "Athena source database")
    if not 7 <= history_days <= 90:
        raise ValueError("history_days must be between 7 and 90")
    if not 1 <= horizon_days <= 30:
        raise ValueError("horizon_days must be between 1 and 30")
    logical_date = validate_logical_date(logical_run_date).isoformat()
    return f"""
WITH params AS (
    SELECT DATE '{logical_date}' AS analysis_date
),
calendar AS (
    SELECT
        CAST(day AS date) AS day,
        row_number() OVER (ORDER BY day) - 1 AS x
    FROM params
    CROSS JOIN UNNEST(
        sequence(date_add('day', -{history_days - 1}, analysis_date), analysis_date, INTERVAL '1' DAY)
    ) AS dates(day)
),
observed AS (
    SELECT
        try_cast(dt AS date) AS day,
        count(DISTINCT shipment_id) AS shipments
    FROM {source_database}.fact_shipment_v2
    CROSS JOIN params
    WHERE try_cast(dt AS date)
        BETWEEN date_add('day', -{history_days - 1}, analysis_date) AND analysis_date
    GROUP BY try_cast(dt AS date)
),
risk_keys AS (
    SELECT DISTINCT run_date AS day, route_id, carrier, ship_mode
    FROM {database}.fact_ai_alerts_v3
    CROSS JOIN params
    WHERE run_date
        BETWEEN date_add('day', -{history_days - 1}, analysis_date) AND analysis_date
),
risk_observed AS (
    SELECT
        try_cast(shipments.dt AS date) AS day,
        count(DISTINCT shipments.shipment_id) AS shipments_at_risk
    FROM {source_database}.fact_shipment_v2 AS shipments
    JOIN risk_keys
      ON try_cast(shipments.dt AS date) = risk_keys.day
     AND lower(trim(shipments.route_id)) = lower(trim(risk_keys.route_id))
     AND lower(trim(shipments.carrier)) = lower(trim(risk_keys.carrier))
     AND lower(trim(shipments.ship_mode)) = lower(trim(risk_keys.ship_mode))
    CROSS JOIN params
    WHERE try_cast(shipments.dt AS date)
        BETWEEN date_add('day', -{history_days - 1}, analysis_date) AND analysis_date
    GROUP BY try_cast(shipments.dt AS date)
),
series AS (
    SELECT
        calendar.day,
        calendar.x,
        coalesce(observed.shipments, 0) AS shipments,
        coalesce(risk_observed.shipments_at_risk, 0) AS shipments_at_risk,
        CASE WHEN observed.day IS NULL THEN 0 ELSE 1 END AS observed_flag
    FROM calendar
    LEFT JOIN observed ON calendar.day = observed.day
    LEFT JOIN risk_observed ON calendar.day = risk_observed.day
),
terms AS (
    SELECT
        count(*) AS n,
        sum(CAST(x AS double)) AS sum_x,
        sum(CAST(shipments AS double)) AS sum_y,
        sum(CAST(x AS double) * CAST(shipments AS double)) AS sum_xy,
        sum(CAST(x AS double) * CAST(x AS double)) AS sum_xx
    FROM series
),
model AS (
    SELECT
        (n * sum_xy - sum_x * sum_y) / nullif(n * sum_xx - sum_x * sum_x, 0) AS slope,
        (sum_y - ((n * sum_xy - sum_x * sum_y)
            / nullif(n * sum_xx - sum_x * sum_x, 0)) * sum_x) / n AS intercept,
        n
    FROM terms
),
residual AS (
    SELECT
        sqrt(sum(power(CAST(series.shipments AS double)
            - (model.intercept + model.slope * series.x), 2)) / greatest(1, model.n - 2))
            AS residual_sigma
    FROM series
    CROSS JOIN model
    GROUP BY model.n
),
summary AS (
    SELECT
        sum(observed_flag) AS observed_days,
        round(100.0 * sum(observed_flag) / count(*), 1) AS data_completeness_pct,
        CAST(sum(CASE WHEN day = params.analysis_date THEN shipments ELSE 0 END) AS bigint)
            AS latest_daily_shipments,
        round(avg(CAST(shipments AS double)), 1) AS average_daily_shipments,
        round(100.0 * sum(CASE WHEN day = params.analysis_date THEN shipments_at_risk ELSE 0 END)
            / nullif(sum(CASE WHEN day = params.analysis_date THEN shipments ELSE 0 END), 0), 1)
            AS latest_risk_rate_pct,
        round(100.0 * model.slope / nullif(avg(CAST(shipments AS double)), 0), 2)
            AS daily_volume_trend_pct
    FROM series
    CROSS JOIN params
    CROSS JOIN model
    GROUP BY params.analysis_date, model.slope
),
forecast_points AS (
    SELECT
        date_add('day', horizon, params.analysis_date) AS metric_date,
        greatest(0, CAST(round(model.intercept + model.slope * ({history_days - 1} + horizon)) AS bigint))
            AS predicted_shipments,
        greatest(1, CAST(round(1.96 * residual.residual_sigma) AS bigint)) AS interval_size
    FROM params
    CROSS JOIN model
    CROSS JOIN residual
    CROSS JOIN UNNEST(sequence(1, {horizon_days})) AS future(horizon)
),
forecast AS (
    SELECT
        metric_date,
        predicted_shipments,
        greatest(0, predicted_shipments - interval_size) AS lower_bound,
        predicted_shipments + interval_size AS upper_bound,
        CAST(round(predicted_shipments * coalesce(summary.latest_risk_rate_pct, 0) / 100.0) AS bigint)
            AS predicted_at_risk,
        sum(predicted_shipments) OVER () AS predicted_shipments_total
    FROM forecast_points
    CROSS JOIN summary
)
SELECT
    'history' AS row_type,
    CAST(CAST(series.day AS date) AS varchar) AS metric_date,
    CAST(series.shipments AS bigint) AS shipments_generated,
    CAST(series.shipments_at_risk AS bigint) AS shipments_at_risk,
    CAST(NULL AS bigint) AS predicted_shipments,
    CAST(NULL AS bigint) AS lower_bound,
    CAST(NULL AS bigint) AS upper_bound,
    CAST(NULL AS bigint) AS predicted_at_risk,
    CAST(summary.observed_days AS bigint) AS observed_days,
    summary.data_completeness_pct,
    summary.latest_daily_shipments,
    summary.average_daily_shipments,
    summary.latest_risk_rate_pct,
    summary.daily_volume_trend_pct,
    CAST(NULL AS bigint) AS predicted_shipments_total
FROM series
CROSS JOIN summary
UNION ALL
SELECT
    'forecast',
    CAST(forecast.metric_date AS varchar),
    CAST(NULL AS bigint),
    CAST(NULL AS bigint),
    forecast.predicted_shipments,
    forecast.lower_bound,
    forecast.upper_bound,
    forecast.predicted_at_risk,
    CAST(summary.observed_days AS bigint),
    summary.data_completeness_pct,
    summary.latest_daily_shipments,
    summary.average_daily_shipments,
    summary.latest_risk_rate_pct,
    summary.daily_volume_trend_pct,
    forecast.predicted_shipments_total
FROM forecast
CROSS JOIN summary
ORDER BY metric_date
""".strip()


def build_existing_analytics_query(database: str, logical_run_date: str | date) -> str:
    """Aggregate governed result tables at one governed run date."""

    database = validate_identifier(database, "Athena database")
    logical_date = validate_logical_date(logical_run_date).isoformat()
    return f"""
WITH params AS (
    SELECT DATE '{logical_date}' AS logical_run_date
),
distributions AS (
    SELECT 'alerts' AS dimension, coalesce(alert_type, 'UNKNOWN') AS label,
        count(*) AS metric_count
    FROM {database}.fact_ai_alerts_v3
    CROSS JOIN params
    WHERE run_date = params.logical_run_date
    GROUP BY alert_type
    UNION ALL
    SELECT 'actions', coalesce(action_type, 'UNKNOWN'), count(*)
    FROM {database}.fact_ai_actions_v2
    CROSS JOIN params
    WHERE run_date = params.logical_run_date
    GROUP BY action_type
    UNION ALL
    SELECT 'root_causes', coalesce(root_cause_type, 'UNKNOWN'), count(*)
    FROM {database}.fact_ai_insights_v3
    CROSS JOIN params
    WHERE run_date = params.logical_run_date
    GROUP BY root_cause_type
),
ranked AS (
    SELECT dimension, label, metric_count,
        row_number() OVER (PARTITION BY dimension ORDER BY metric_count DESC, label) AS rank
    FROM distributions
),
summary AS (
    SELECT 'summary' AS dimension, 'risk_hotspots_tracked' AS label, count(*) AS metric_count
    FROM (
        SELECT DISTINCT route_id, carrier, alert_type
        FROM {database}.fact_ai_alerts_v3
        CROSS JOIN params
        WHERE run_date = params.logical_run_date
    )
)
SELECT dimension, label, metric_count
FROM ranked
WHERE rank <= 6
UNION ALL
SELECT dimension, label, metric_count
FROM summary
ORDER BY dimension, metric_count DESC, label
""".strip()


def build_operational_baseline_query(
    source_database: str,
    logical_run_date: str | date,
) -> str:
    """Read public-safe aggregate baseline dimensions without entity rows."""

    source_database = validate_identifier(source_database, "Athena source database")
    logical_date = validate_logical_date(logical_run_date).isoformat()
    return f"""
WITH latest_baseline AS (
    SELECT max(baseline_as_of_date) AS baseline_as_of_date
    FROM {source_database}.vw_multimodal_operational_baseline_v1
    WHERE baseline_as_of_date <= DATE '{logical_date}'
)
SELECT
    CAST(baseline.baseline_as_of_date AS varchar) AS baseline_as_of_date,
    CAST(baseline.source_start_date AS varchar) AS source_start_date,
    CAST(baseline.source_max_metric_date AS varchar) AS source_max_metric_date,
    baseline.dimension_type,
    baseline.dimension_value,
    baseline.shipment_count,
    baseline.new_booking_count,
    baseline.delivered_count,
    baseline.on_time_delivery_count,
    baseline.late_delivery_count,
    baseline.on_time_delivery_rate_pct,
    baseline.avg_delivery_delay_hours,
    baseline.sla_breach_shipment_count,
    baseline.sla_breach_shipment_rate_pct,
    baseline.expected_cost_total,
    baseline.current_cost_total,
    baseline.cost_variance_pct,
    baseline.signal_candidate_count,
    baseline.high_severity_signal_count,
    baseline.real_world_evidence,
    baseline.data_provenance,
    baseline.evidence_class,
    baseline.decision_use
FROM {source_database}.vw_multimodal_operational_baseline_v1 baseline
JOIN latest_baseline latest
  ON baseline.baseline_as_of_date = latest.baseline_as_of_date
WHERE baseline.dimension_type IN ('ALL', 'TRANSPORT_MODE', 'PROVIDER', 'MARKET_LANE')
ORDER BY
    baseline.baseline_as_of_date DESC,
    CASE baseline.dimension_type
        WHEN 'ALL' THEN 0
        WHEN 'TRANSPORT_MODE' THEN 1
        WHEN 'PROVIDER' THEN 2
        ELSE 3
    END,
    baseline.shipment_count DESC,
    baseline.dimension_value
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


def _safe_pipeline_load_error(exc: Exception) -> str:
    """Return a public-safe diagnostic code without paths or exception text."""

    response = getattr(exc, "response", None)
    error = response.get("Error", {}) if isinstance(response, dict) else {}
    code = str(error.get("Code") or "")
    return {
        "AccessDenied": "access_denied",
        "NoSuchBucket": "bucket_unavailable",
        "NoSuchKey": "object_unavailable",
        "InvalidObjectState": "object_unavailable",
    }.get(
        code,
        "invalid_json"
        if isinstance(exc, json.JSONDecodeError)
        else "unexpected_error",
    )


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
                "expected_stage_count": len(PIPELINE_STAGE_ORDER),
                "stage_count": 0,
                "stages_succeeded": 0,
                "quality_checks_succeeded": 0,
                "quality_checks_total": PIPELINE_QUALITY_CHECK_TOTAL,
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
    execution_mode = str(pipeline_run.get("execution_mode") or "OPERATIONAL").upper()
    time_basis = str(pipeline_run.get("time_basis") or "ACTUAL_CALENDAR").upper()
    operational_time = (
        execution_mode == "OPERATIONAL"
        and time_basis == "ACTUAL_CALENDAR"
        and not pipeline_run.get("scenario_id")
    )
    failure_category = str(pipeline_run.get("failure_category") or "") or None
    if failure_category not in SAFE_FAILURE_CATEGORIES:
        failure_category = "unexpected_failure" if failure_category else None
    logical_date_current = logical_date == newest_date
    stage_contract_complete = (
        tuple(stage["name"] for stage in stages) == PIPELINE_STAGE_ORDER
    )
    all_stages_succeeded = stage_contract_complete and all(
        stage["status"] == "succeeded" for stage in stages
    )
    quality_stages = {
        stage["name"]: stage["quality_checks"]
        for stage in stages
        if stage["name"] in PIPELINE_QUALITY_STAGES
    }
    quality_contract_complete = all(
        {check["name"] for check in quality_stages.get(stage_name, [])}
        == PIPELINE_QUALITY_CHECKS
        and all(
            check["status"] == "passed"
            for check in quality_stages.get(stage_name, [])
        )
        for stage_name in PIPELINE_QUALITY_STAGES
    )
    quality_checks_succeeded = sum(
        1
        for stage in stages
        for check in stage["quality_checks"]
        if check["status"] == "passed"
    )
    verified = (
        run_status in PIPELINE_RUN_SUCCESS
        and operational_time
        and logical_date_current
        and all_stages_succeeded
        and quality_contract_complete
    )
    if not operational_time:
        public_status = "unverified"
    elif verified:
        public_status = "current"
    elif run_status == "failed":
        public_status = "failed"
    elif run_status == "running":
        public_status = "running"
    else:
        public_status = "unverified"

    duration_ms = None
    try:
        started = datetime.fromisoformat(
            (_safe_timestamp(pipeline_run.get("started_at")) or "").replace("Z", "+00:00")
        )
        completed = datetime.fromisoformat(
            (_safe_timestamp(pipeline_run.get("completed_at")) or "").replace("Z", "+00:00")
        )
        duration_ms = max(0, int((completed - started).total_seconds() * 1000))
    except (TypeError, ValueError):
        pass

    return (
        {
            "status": public_status,
            "verification_mode": (
                "pipeline_run" if operational_time else "future_simulation_excluded"
            ),
            "execution_mode": execution_mode,
            "time_basis": time_basis,
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
            "expected_stage_count": len(PIPELINE_STAGE_ORDER),
            "stage_count": len(stages),
            "stages_succeeded": sum(
                1 for stage in stages if stage["status"] == "succeeded"
            ),
            "quality_checks_succeeded": quality_checks_succeeded,
            "quality_checks_total": PIPELINE_QUALITY_CHECK_TOTAL,
            "runbook_url": PIPELINE_RUNBOOK_URL,
        },
        verified,
    )


def parse_forecast_rows(
    rows: list[dict[str, str | None]],
    history_days: int = HISTORY_DAYS,
    horizon_days: int = FORECAST_HORIZON_DAYS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate and package values already calculated by Athena."""

    history_rows = [row for row in rows if row.get("row_type") == "history"]
    forecast_rows = [row for row in rows if row.get("row_type") == "forecast"]
    summary = (forecast_rows or history_rows or [{}])[0]
    observed_days = _optional_int(summary.get("observed_days")) or 0
    analytics = {
        "window_days": history_days,
        "observed_days": observed_days,
        "data_completeness_pct": _optional_float(summary.get("data_completeness_pct"), 1) or 0.0,
        "latest_daily_shipments": _optional_int(summary.get("latest_daily_shipments")),
        "average_daily_shipments": _optional_float(summary.get("average_daily_shipments"), 1),
        "latest_risk_rate_pct": _optional_float(summary.get("latest_risk_rate_pct"), 1),
        "daily_volume_trend_pct": _optional_float(summary.get("daily_volume_trend_pct"), 2),
        "calculation_engine": "aws_athena_engine_v3",
        "date_anchor": "logical_run_date_dt",
    }
    points = [
        {
            "date": row.get("metric_date"),
            "predicted_shipments": _optional_int(row.get("predicted_shipments")),
            "lower_bound": _optional_int(row.get("lower_bound")),
            "upper_bound": _optional_int(row.get("upper_bound")),
            "predicted_at_risk": _optional_int(row.get("predicted_at_risk")),
        }
        for row in forecast_rows
        if _date(row.get("metric_date")) is not None
    ]
    history = [
        {
            "date": row.get("metric_date"),
            "shipments": _optional_int(row.get("shipments_generated")) or 0,
            "shipments_at_risk": _optional_int(row.get("shipments_at_risk")) or 0,
        }
        for row in history_rows[-14:]
        if _date(row.get("metric_date")) is not None
    ]
    forecast = {
        "status": "ready" if observed_days >= 7 and len(points) == horizon_days else "insufficient_data",
        "method": "ordinary_least_squares_28d",
        "method_label": "28-day Athena OLS baseline",
        "calculation_engine": "aws_athena_engine_v3",
        "horizon_days": horizon_days,
        "predicted_shipments_7d": _optional_int(summary.get("predicted_shipments_total")),
        "points": points,
        "history": history,
        "disclosure": "AWS Athena statistical baseline, not a committed operational target or autonomous decision.",
    }
    return analytics, forecast


def parse_existing_analytics(rows: list[dict[str, str | None]]) -> dict[str, Any]:
    """Package aggregate-only results from the already-deployed v_ai views."""

    result: dict[str, Any] = {
        "source": "existing_athena_result_tables",
        "risk_hotspots_tracked": 0,
        "distributions": {"alerts": [], "actions": [], "root_causes": []},
    }
    for row in rows:
        dimension = str(row.get("dimension") or "")
        label = str(row.get("label") or "")
        metric_count = _optional_int(row.get("metric_count")) or 0
        if dimension == "summary" and label == "risk_hotspots_tracked":
            result[label] = metric_count
        elif dimension in result["distributions"] and SAFE_ANALYTIC_LABEL.fullmatch(label):
            result["distributions"][dimension].append({"label": label, "count": metric_count})
    return result


def parse_operational_baseline(
    row: dict[str, str | None],
    logical_run_date: str | date,
) -> dict[str, Any]:
    """Validate and publish the aggregate-only stateful operational baseline."""

    cutoff = validate_logical_date(logical_run_date)
    baseline_date = _date(row.get("baseline_as_of_date"))
    source_start_date = _date(row.get("source_start_date"))
    source_max_date = _date(row.get("source_max_metric_date"))
    if not baseline_date or not source_start_date or not source_max_date:
        raise ValueError("Operational baseline did not return its governed date window")
    if (
        baseline_date > cutoff
        or source_max_date > baseline_date
        or source_start_date > source_max_date
    ):
        raise ValueError("Operational baseline exceeds the governed analysis date")

    if (
        str(row.get("real_world_evidence") or "").lower() != "false"
        or row.get("data_provenance") != "SIMULATED_MULTIMODAL_V1"
        or row.get("evidence_class") != "SYNTHETIC_OPERATIONAL_CALENDAR_BASELINE"
        or row.get("decision_use") != "ENGINEERING_EVALUATION_ONLY"
    ):
        raise ValueError("Operational baseline evidence classification is unsafe")

    shipment_count = _optional_int(row.get("shipment_count"))
    delivered_count = _optional_int(row.get("delivered_count"))
    if (
        shipment_count is None
        or shipment_count <= 0
        or delivered_count is None
        or delivered_count < 0
        or delivered_count > shipment_count
    ):
        raise ValueError("Operational baseline shipment counts are invalid")

    on_time_rate = _optional_float(row.get("on_time_delivery_rate_pct"), 2)
    raw_cost_variance = _optional_float(row.get("cost_variance_pct"), 2)
    outcome_rate_observable = delivered_count > 0 and on_time_rate is not None
    realized_cost_observable = delivered_count > 0 and raw_cost_variance is not None
    engineering_ready = (
        delivered_count >= MIN_ENGINEERING_DELIVERED_SHIPMENTS
        and outcome_rate_observable
        and realized_cost_observable
    )
    reasons: list[str] = []
    if delivered_count < MIN_ENGINEERING_DELIVERED_SHIPMENTS:
        reasons.append("INSUFFICIENT_DELIVERED_SHIPMENTS")
    if not outcome_rate_observable:
        reasons.append("OUTCOME_RATE_UNAVAILABLE")
    if not realized_cost_observable:
        reasons.append("REALIZED_COST_UNAVAILABLE")

    return {
        "status": "available",
        "as_of_date": baseline_date.isoformat(),
        "source_start_date": source_start_date.isoformat(),
        "source_max_metric_date": source_max_date.isoformat(),
        "metrics": {
            "shipment_count": shipment_count,
            "new_booking_count": _optional_int(row.get("new_booking_count")),
            "delivered_count": delivered_count,
            "on_time_delivery_count": _optional_int(row.get("on_time_delivery_count")),
            "late_delivery_count": _optional_int(row.get("late_delivery_count")),
            "on_time_delivery_rate_pct": on_time_rate if outcome_rate_observable else None,
            "avg_delivery_delay_hours": (
                _optional_float(row.get("avg_delivery_delay_hours"), 2)
                if outcome_rate_observable
                else None
            ),
            "sla_breach_shipment_count": _optional_int(
                row.get("sla_breach_shipment_count")
            ),
            "sla_breach_shipment_rate_pct": _optional_float(
                row.get("sla_breach_shipment_rate_pct"), 2
            ),
            "expected_cost_total": _optional_float(row.get("expected_cost_total"), 2),
            "current_cost_total": _optional_float(row.get("current_cost_total"), 2),
            "cost_variance_pct": raw_cost_variance if realized_cost_observable else None,
            "signal_candidate_count": _optional_int(row.get("signal_candidate_count")),
            "high_severity_signal_count": _optional_int(
                row.get("high_severity_signal_count")
            ),
        },
        "maturity": {
            "status": "ENGINEERING_READY" if engineering_ready else "NOT_READY",
            "minimum_delivered_shipments": MIN_ENGINEERING_DELIVERED_SHIPMENTS,
            "delivered_shipments": delivered_count,
            "delivery_coverage_pct": round(100.0 * delivered_count / shipment_count, 2),
            "outcome_metrics_observable": outcome_rate_observable,
            "realized_cost_observable": realized_cost_observable,
            "real_world_status": "BLOCKED",
            "reasons": reasons,
        },
        "evidence": {
            "real_world_evidence": False,
            "data_provenance": "SIMULATED_MULTIMODAL_V1",
            "evidence_class": "SYNTHETIC_OPERATIONAL_CALENDAR_BASELINE",
            "decision_use": "ENGINEERING_EVALUATION_ONLY",
        },
    }


def parse_operational_baseline_rows(
    rows: list[dict[str, str | None]],
    logical_run_date: str | date,
) -> dict[str, Any]:
    """Publish an ALL baseline plus allowlisted aggregate breakdowns."""

    if not rows:
        raise ValueError("Operational baseline returned no aggregate rows")
    all_rows = [
        row
        for row in rows
        if row.get("dimension_type") == "ALL" and row.get("dimension_value") == "ALL"
    ]
    if len(all_rows) != 1:
        raise ValueError("Operational baseline must contain exactly one ALL row")

    baseline = parse_operational_baseline(all_rows[0], logical_run_date)
    total_shipments = baseline["metrics"]["shipment_count"]
    breakdowns: dict[str, list[dict[str, Any]]] = {
        "transport_modes": [],
        "providers": [],
        "market_lanes": [],
    }
    output_keys = {
        "TRANSPORT_MODE": "transport_modes",
        "PROVIDER": "providers",
        "MARKET_LANE": "market_lanes",
    }
    seen: set[tuple[str, str]] = set()
    for row in rows:
        dimension_type = row.get("dimension_type")
        dimension_value = row.get("dimension_value")
        if dimension_type == "ALL":
            continue
        if dimension_type not in output_keys or not isinstance(dimension_value, str):
            raise ValueError("Operational baseline returned an unsafe dimension")
        if (
            len(dimension_value) > 64
            or not re.fullmatch(r"[A-Z0-9][A-Z0-9 _./-]*", dimension_value)
        ):
            raise ValueError("Operational baseline returned an unsafe dimension value")
        key = (dimension_type, dimension_value)
        if key in seen:
            raise ValueError("Operational baseline returned a duplicate dimension")
        seen.add(key)

        parsed = parse_operational_baseline(row, logical_run_date)
        metrics = parsed["metrics"]
        if metrics["shipment_count"] > total_shipments:
            raise ValueError("Operational baseline breakdown exceeds the ALL population")
        breakdowns[output_keys[dimension_type]].append(
            {
                "name": dimension_value,
                "shipment_count": metrics["shipment_count"],
                "new_booking_count": metrics["new_booking_count"],
                "delivered_count": metrics["delivered_count"],
                "sla_breach_shipment_count": metrics["sla_breach_shipment_count"],
                "sla_breach_shipment_rate_pct": metrics["sla_breach_shipment_rate_pct"],
                "signal_candidate_count": metrics["signal_candidate_count"],
                "high_severity_signal_count": metrics["high_severity_signal_count"],
                "expected_cost_total": metrics["expected_cost_total"],
                "current_cost_total": metrics["current_cost_total"],
                "cost_variance_pct": metrics["cost_variance_pct"],
            }
        )

    for values in breakdowns.values():
        values.sort(key=lambda item: (-item["shipment_count"], item["name"]))
    delivered = baseline["metrics"]["delivered_count"]
    baseline["breakdowns"] = breakdowns
    baseline["outcome_labels"] = {
        "observed": delivered,
        "pending": total_shipments - delivered,
        "total": total_shipments,
    }
    baseline["population_profile"] = {
        "transport_mode_count": len(breakdowns["transport_modes"]),
        "provider_count": len(breakdowns["providers"]),
        "market_lane_count": len(breakdowns["market_lanes"]),
        "multimodal_status": (
            "MULTIMODAL_OBSERVED"
            if len(breakdowns["transport_modes"]) > 1
            else "SINGLE_MODE_OBSERVED"
        ),
    }
    return baseline


def build_snapshot(
    row: dict[str, str | None],
    forecast_rows: list[dict[str, str | None]] | None = None,
    existing_analytics_rows: list[dict[str, str | None]] | None = None,
    operational_baseline_row: (
        dict[str, str | None] | list[dict[str, str | None]] | None
    ) = None,
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
    analytics, forecast = parse_forecast_rows(forecast_rows or [])
    analytics.update(
        {
            "action_completion_rate_pct": _optional_float(row.get("action_completion_rate_pct"), 1),
            "outcome_success_rate_pct": _optional_float(row.get("outcome_success_rate_pct"), 1),
            "avg_outcome_improvement_pct": _optional_float(row.get("avg_outcome_improvement_pct"), 1),
            "avg_effectiveness_score": _optional_float(row.get("avg_effectiveness_score"), 2),
            "max_stage_lag_days": max_stage_lag,
            "existing_assets": parse_existing_analytics(existing_analytics_rows or []),
        }
    )
    baseline_rows = (
        operational_baseline_row
        if isinstance(operational_baseline_row, list)
        else [operational_baseline_row] if operational_baseline_row else []
    )
    if baseline_rows and "dimension_type" not in baseline_rows[0]:
        baseline_rows = [
            {**baseline_rows[0], "dimension_type": "ALL", "dimension_value": "ALL"}
        ]
    operational_baseline = (
        parse_operational_baseline_rows(baseline_rows, newest_date)
        if baseline_rows
        else {
            "status": "unavailable",
            "as_of_date": None,
            "metrics": {},
            "breakdowns": {
                "transport_modes": [],
                "providers": [],
                "market_lanes": [],
            },
            "outcome_labels": {"observed": 0, "pending": 0, "total": 0},
            "population_profile": {
                "transport_mode_count": 0,
                "provider_count": 0,
                "market_lane_count": 0,
                "multimodal_status": "UNAVAILABLE",
            },
            "maturity": {
                "status": "NOT_READY",
                "minimum_delivered_shipments": MIN_ENGINEERING_DELIVERED_SHIPMENTS,
                "delivered_shipments": 0,
                "delivery_coverage_pct": 0.0,
                "outcome_metrics_observable": False,
                "realized_cost_observable": False,
                "real_world_status": "BLOCKED",
                "reasons": ["OPERATIONAL_BASELINE_UNAVAILABLE"],
            },
            "evidence": {
                "real_world_evidence": False,
                "data_provenance": "SIMULATED_MULTIMODAL_V1",
                "evidence_class": "SYNTHETIC_OPERATIONAL_CALENDAR_BASELINE",
                "decision_use": "ENGINEERING_EVALUATION_ONLY",
            },
        }
    )
    baseline_available = operational_baseline["status"] == "available"
    pipeline_current = pipeline_current and baseline_available
    fresh = age_hours <= 36 and pipeline_current

    return {
        "schema_version": "1.7",
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "source_updated_at": source_updated_at.isoformat().replace("+00:00", "Z"),
        "as_of_date": newest_date.isoformat(),
        "provenance": {
            "source_type": "athena_iceberg_aggregate",
            "connection": "aws_athena_existing_assets_via_github_oidc",
            "label": "AWS Athena existing-asset analytics",
            "is_connected": True,
            "disclosure": "Public-safe aggregate analytics; no operational records or identifiers are exported.",
            "outcome_evidence": "simulated",
        },
        "freshness": {
            "status": "fresh" if fresh else "stale",
            "age_hours": age_hours,
            "max_age_hours": 36,
        },
        "stage_freshness": stage_freshness,
        "metrics": metrics,
        "analytics": analytics,
        "operational_baseline": operational_baseline,
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
            "query_checks_succeeded": 4 if operational_baseline_row else 3,
            "query_checks_total": 4,
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
    source_database = validate_identifier(
        os.getenv("ATHENA_SOURCE_DATABASE") or DEFAULT_SOURCE_DATABASE,
        "Athena source database",
    )
    workgroup = os.getenv("ATHENA_WORKGROUP") or DEFAULT_WORKGROUP
    output = os.environ.get("ATHENA_OUTPUT")
    if not output:
        raise ValueError("ATHENA_OUTPUT is required")

    region = os.getenv("AWS_REGION", "us-east-1")
    pipeline_status_uri = os.getenv("PIPELINE_STATUS_S3_URI")
    pipeline_status_required = os.getenv("PIPELINE_STATUS_REQUIRED", "false").lower() == "true"
    pipeline_run = None
    if pipeline_status_uri:
        try:
            pipeline_run = load_pipeline_run(
                boto3.client("s3", region_name=region), pipeline_status_uri
            )
        except Exception as exc:
            if not pipeline_status_required:
                raise
            # Required verification fails closed while still allowing Pages to
            # publish an explicit stale/unverified state.
            print(
                "Pipeline status object unavailable "
                f"({_safe_pipeline_load_error(exc)}); publishing unverified."
            )
            pipeline_run = None
    analysis_date = resolve_analysis_date(pipeline_run)
    client = boto3.client("athena", region_name=region)
    metric_response = run_query(
        client, build_query(database, analysis_date, source_database), database, output, workgroup
    )
    forecast_response = run_query(
        client,
        build_forecast_query(database, analysis_date, source_database=source_database),
        database,
        output,
        workgroup,
    )
    existing_analytics_response = run_query(
        client,
        build_existing_analytics_query(database, analysis_date),
        database,
        output,
        workgroup,
    )
    operational_baseline_response = run_query(
        client,
        build_operational_baseline_query(source_database, analysis_date),
        source_database,
        output,
        workgroup,
    )
    snapshot = build_snapshot(
        parse_athena_result(metric_response),
        parse_athena_rows(forecast_response),
        parse_athena_rows(existing_analytics_response),
        parse_athena_rows(operational_baseline_response),
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
