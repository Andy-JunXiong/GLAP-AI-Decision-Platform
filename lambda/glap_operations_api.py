"""Authenticated internal Operations API adapter for GLAP staging.

API Gateway's JWT authorizer validates the token. This adapter maps trusted
group claims to explicit permissions, exposes a bounded Action queue, and
forwards mutations with an actor derived from the authenticated identity.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


DATABASE = os.getenv("ATHENA_SOURCE_DATABASE", "simulated_iceberg_m")
WORKGROUP = os.getenv("ATHENA_WORKGROUP", "primary")
OUTPUT = os.getenv("ATHENA_OUTPUT", "")
ACTION_VIEW = os.getenv("LIFECYCLE_ACTION_CURRENT_VIEW", "vw_lifecycle_action_current_staging_v1")
ALERT_TABLE = os.getenv("LIFECYCLE_ALERT_TABLE", "fact_lifecycle_alert_staging_v1")
OUTCOME_TABLE = os.getenv("LIFECYCLE_OUTCOME_TABLE", "fact_lifecycle_outcome_staging_v1")
MUTATION_FUNCTION = os.getenv("ACTION_MUTATION_FUNCTION", "")
PIPELINE_STATUS_S3_URI = os.getenv("PIPELINE_STATUS_S3_URI", "")
PIPELINE_STAGE_ORDER = (
    "generation",
    "raw_to_iceberg",
    "input_validation",
    "decision_pipeline",
    "decision_flywheel",
    "output_validation",
)
PIPELINE_QUALITY_STAGES = {"input_validation", "output_validation"}
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
}
SAFE_STAGE_STATUS = {"blocked", "running", "succeeded", "failed", "not_invoked"}
PIPELINE_RUNBOOK_URL = (
    "https://github.com/Andy-JunXiong/GLAP-AI-Decision-Platform/"
    "blob/main/docs/runbooks/pipeline_reliability.md"
)
ROLE_PERMISSIONS = {
    "viewer": {"risks:read", "actions:read", "outcomes:read", "health:read"},
    "operator": {
        "risks:read", "actions:read", "actions:complete", "outcomes:read", "health:read",
    },
    "approver": {
        "risks:read", "actions:read", "actions:approve", "actions:reject", "outcomes:read",
        "health:read",
    },
    "administrator": {
        "risks:read", "actions:read", "actions:approve", "actions:reject", "actions:complete",
        "outcomes:read", "health:read",
    },
}
OPERATION_PERMISSION = {
    "APPROVE": "actions:approve",
    "REJECT": "actions:reject",
    "COMPLETE": "actions:complete",
}
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
LOGGER = logging.getLogger(__name__)


def _identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError("Unsafe Athena identifier")
    return value


def _response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", "cache-control": "no-store"},
        "body": json.dumps(body, separators=(",", ":"), default=str),
    }


def _safe_aws_error_code(exc: Exception) -> str:
    response = getattr(exc, "response", {})
    if not isinstance(response, dict):
        return "none"
    error = response.get("Error") or {}
    code = str(error.get("Code") or "none")
    return code if re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", code) else "invalid"


def _mutation_failure_response(payload: dict[str, Any], request_id: Any) -> dict[str, Any] | None:
    error_type = str(payload.get("errorType") or "")
    message = str(payload.get("errorMessage") or "")
    if error_type == "ActionConflictError" or message.startswith(
        ("Invalid Action transition:", "request_id is already bound")
    ):
        return _response(409, {"error": "conflict", "request_id": request_id})
    if error_type == "ValueError" and message.startswith("Action was not found"):
        return _response(404, {"error": "not_found", "request_id": request_id})
    if error_type == "ValueError":
        return _response(400, {"error": "invalid_request", "request_id": request_id})
    return None


def _record_failure_metric(client: Any | None = None) -> bool:
    try:
        if client is None:
            import boto3

            client = boto3.client("cloudwatch")
        client.put_metric_data(
            Namespace="GLAP/OperationsApi",
            MetricData=[{"MetricName": "ServiceUnavailable", "Value": 1, "Unit": "Count"}],
        )
        return True
    except Exception as exc:
        LOGGER.warning(
            "operations_failure_metric_failed exception=%s aws_error=%s",
            type(exc).__name__,
            _safe_aws_error_code(exc),
        )
        return False


def _claim_groups(raw_groups: Any) -> list[str]:
    if isinstance(raw_groups, list):
        return [str(group) for group in raw_groups]
    text = str(raw_groups or "").strip()
    if text.startswith("["):
        try:
            decoded = json.loads(text)
            if isinstance(decoded, list):
                return [str(group) for group in decoded]
        except json.JSONDecodeError:
            pass
    return [part.strip("[]\"'") for part in re.split(r"[ ,]+", text) if part.strip("[]\"'")]


def _identity(event: dict[str, Any]) -> tuple[str, str, set[str]]:
    jwt = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {})
    claims = jwt.get("claims") or {}
    subject = str(claims.get("sub") or "").strip()
    actor = str(
        claims.get("name")
        or claims.get("email")
        or claims.get("username")
        or claims.get("cognito:username")
        or ""
    ).strip()
    raw_groups = claims.get("cognito:groups") or claims.get("groups") or ""
    groups = _claim_groups(raw_groups)
    roles = {str(group).lower() for group in groups if str(group).lower() in ROLE_PERMISSIONS}
    if not subject or not actor or not roles:
        raise PermissionError("Authenticated named identity with an Operations role is required")
    permissions = set().union(*(ROLE_PERMISSIONS[role] for role in roles))
    return subject, actor, permissions


def build_action_queue_query(limit: int, status: str | None) -> str:
    where = "WHERE temporal_scope_id = 'OPERATIONAL'"
    if status:
        if status not in {"PROPOSED", "APPROVED", "REJECTED", "COMPLETED"}:
            raise ValueError("Unsupported Action status filter")
        where += f" AND status = '{status}'"
    return f"""SELECT action_id, alert_fingerprint, shipment_id, action_type,
alert_type, alert_severity, status, approval_required, approved_by,
approved_at, completed_at, created_date
FROM {_identifier(DATABASE)}.{_identifier(ACTION_VIEW)}
{where}
ORDER BY created_date DESC, action_id
LIMIT {limit}"""


def build_risk_hotspots_query(limit: int, status: str | None, as_of_date: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of_date):
        raise ValueError("Invalid operational cutoff date")
    status_filter = ""
    if status:
        if status not in {"OPEN", "RESOLVED"}:
            raise ValueError("Unsupported Risk status filter")
        status_filter = f" AND status = '{status}'"
    return f"""WITH ranked_alerts AS (
    SELECT alert_fingerprint, shipment_id, alert_type, alert_grain,
           alert_dimension, severity, status, first_detected_date,
           last_detected_date, resolved_date, metric_name, metric_value,
           threshold_value, as_of_date,
           row_number() OVER (
               PARTITION BY alert_fingerprint
               ORDER BY try_cast(dt AS date) DESC, updated_at DESC
           ) AS row_rank
    FROM {_identifier(DATABASE)}.{_identifier(ALERT_TABLE)}
    WHERE temporal_scope_id = 'OPERATIONAL'
      AND execution_mode = 'OPERATIONAL'
      AND time_basis = 'ACTUAL_CALENDAR'
      AND as_of_date <= DATE '{as_of_date}'
      AND try_cast(dt AS date) <= DATE '{as_of_date}'
)
SELECT alert_fingerprint, shipment_id, alert_type, alert_grain,
       alert_dimension, severity, status, first_detected_date,
       last_detected_date, resolved_date, metric_name, metric_value,
       threshold_value, as_of_date
FROM ranked_alerts
WHERE row_rank = 1{status_filter}
ORDER BY CASE severity WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2
         WHEN 'MEDIUM' THEN 3 ELSE 4 END,
         last_detected_date DESC, alert_fingerprint
LIMIT {limit}"""


def build_outcome_review_query(limit: int, status: str | None, as_of_date: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of_date):
        raise ValueError("Invalid operational cutoff date")
    valid_statuses = {"PENDING", "SUCCESSFUL", "PARTIALLY_SUCCESSFUL", "FAILED", "INCONCLUSIVE"}
    status_filter = ""
    if status:
        if status not in valid_statuses:
            raise ValueError("Unsupported Outcome status filter")
        status_filter = f" AND outcome_status = '{status}'"
    return f"""WITH ranked_outcomes AS (
    SELECT outcome_id, action_id, alert_fingerprint, shipment_id,
           observation_due_date, status AS outcome_status, observed_date,
           effect_pct, outcome_version, as_of_date,
           row_number() OVER (
               PARTITION BY outcome_id
               ORDER BY try_cast(dt AS date) DESC, as_of_date DESC
           ) AS row_rank
    FROM {_identifier(DATABASE)}.{_identifier(OUTCOME_TABLE)}
    WHERE temporal_scope_id = 'OPERATIONAL'
      AND execution_mode = 'OPERATIONAL'
      AND time_basis = 'ACTUAL_CALENDAR'
      AND as_of_date <= DATE '{as_of_date}'
      AND try_cast(dt AS date) <= DATE '{as_of_date}'
      AND (
          (status = 'PENDING' AND observed_date IS NULL)
          OR (status IN ('SUCCESSFUL', 'PARTIALLY_SUCCESSFUL', 'FAILED', 'INCONCLUSIVE')
              AND observed_date <= DATE '{as_of_date}')
      )
), current_outcomes AS (
    SELECT * FROM ranked_outcomes WHERE row_rank = 1
)
SELECT o.outcome_id, o.action_id, o.alert_fingerprint, o.shipment_id,
       o.observation_due_date, o.outcome_status, o.observed_date,
       o.effect_pct, o.outcome_version, o.as_of_date,
       CASE WHEN o.outcome_status = 'PENDING' THEN 'NOT_OBSERVED'
            ELSE 'OBSERVED_ACTUAL_CALENDAR' END AS evidence_status,
       a.action_type, a.alert_type, a.alert_severity, a.status AS action_status
FROM current_outcomes o
LEFT JOIN {_identifier(DATABASE)}.{_identifier(ACTION_VIEW)} a
  ON o.action_id = a.action_id AND a.temporal_scope_id = 'OPERATIONAL'
WHERE 1 = 1{status_filter}
ORDER BY CASE o.outcome_status WHEN 'PENDING' THEN 1 ELSE 2 END,
         o.observation_due_date, o.outcome_id
LIMIT {limit}"""


def _parse_rows(response: dict[str, Any]) -> list[dict[str, str | None]]:
    result = response.get("ResultSet", {})
    rows = result.get("Rows", [])
    columns = result.get("ResultSetMetadata", {}).get("ColumnInfo", [])
    headers = [str(column.get("Name")) for column in columns]
    parsed = []
    for row in rows[1:]:
        values = [cell.get("VarCharValue") for cell in row.get("Data", [])]
        values.extend([None] * (len(headers) - len(values)))
        parsed.append(dict(zip(headers, values)))
    return parsed


def _query_rows(client: Any, query: str) -> list[dict[str, str | None]]:
    query_id = client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={"Database": DATABASE},
        ResultConfiguration={"OutputLocation": OUTPUT},
        WorkGroup=WORKGROUP,
    )["QueryExecutionId"]
    deadline = time.monotonic() + 30
    while True:
        state = client.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            return _parse_rows(client.get_query_results(QueryExecutionId=query_id, MaxResults=101))
        if state in {"FAILED", "CANCELLED"}:
            raise RuntimeError("Operations query failed")
        if time.monotonic() >= deadline:
            client.stop_query_execution(QueryExecutionId=query_id)
            raise TimeoutError("Operations query timed out")
        time.sleep(0.25)


def _sydney_date() -> str:
    return datetime.now(ZoneInfo("Australia/Sydney")).date().isoformat()


def _safe_timestamp(value: Any) -> str | None:
    text = str(value or "")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.isoformat().replace("+00:00", "Z")


def _safe_failure(value: Any) -> str | None:
    failure = str(value or "") or None
    if failure and failure not in SAFE_FAILURE_CATEGORIES:
        return "unexpected_failure"
    return failure


def sanitize_pipeline_health(run: dict[str, Any], sydney_date: str) -> dict[str, Any]:
    """Return the internal stage-level view without infrastructure identifiers."""

    cutoff = date.fromisoformat(sydney_date)
    try:
        logical_date = date.fromisoformat(str(run.get("logical_run_date") or ""))
    except ValueError:
        logical_date = None

    execution_mode = str(run.get("execution_mode") or "OPERATIONAL").upper()
    time_basis = str(run.get("time_basis") or "ACTUAL_CALENDAR").upper()
    operational = (
        execution_mode == "OPERATIONAL"
        and time_basis == "ACTUAL_CALENDAR"
        and not run.get("scenario_id")
    )

    safe_stages = []
    for index, expected_name in enumerate(PIPELINE_STAGE_ORDER):
        raw_stages = run.get("stages")
        raw = raw_stages[index] if isinstance(raw_stages, list) and index < len(raw_stages) else {}
        raw = raw if isinstance(raw, dict) and raw.get("name") == expected_name else {}
        stage_status = str(raw.get("status") or "blocked").lower()
        if stage_status not in SAFE_STAGE_STATUS:
            stage_status = "blocked"
        checks = []
        for check in raw.get("quality_checks") or []:
            if not isinstance(check, dict):
                continue
            name = str(check.get("name") or "")
            status = str(check.get("status") or "").lower()
            if name in PIPELINE_QUALITY_CHECKS and status in {"passed", "failed"}:
                checks.append({"name": name, "status": status})
        safe_stages.append({
            "name": expected_name,
            "status": stage_status,
            "started_at": _safe_timestamp(raw.get("started_at")),
            "completed_at": _safe_timestamp(raw.get("completed_at")),
            "duration_ms": int(raw["duration_ms"])
            if isinstance(raw.get("duration_ms"), (int, float)) and raw["duration_ms"] >= 0
            else None,
            "failure_category": _safe_failure(raw.get("failure_category")),
            "quality_checks": checks,
        })

    contract_complete = all(
        stage["name"] == expected and stage["status"] == "succeeded"
        for stage, expected in zip(safe_stages, PIPELINE_STAGE_ORDER)
    )
    quality_complete = all(
        {check["name"] for check in stage["quality_checks"]} == PIPELINE_QUALITY_CHECKS
        and all(check["status"] == "passed" for check in stage["quality_checks"])
        for stage in safe_stages if stage["name"] in PIPELINE_QUALITY_STAGES
    )
    raw_status = str(run.get("status") or "unknown").lower()
    future_invalid = logical_date is not None and logical_date > cutoff
    verified_success = (
        operational and not future_invalid and raw_status in {"success", "succeeded"}
        and contract_complete and quality_complete
    )
    if not operational or future_invalid or logical_date is None:
        status = "unverified"
        freshness = "future_invalid" if future_invalid else "unverified"
    elif raw_status == "failed":
        status, freshness = "failed", "current" if logical_date == cutoff else "stale"
    elif raw_status == "running":
        status, freshness = "running", "current" if logical_date == cutoff else "stale"
    elif verified_success and logical_date == cutoff:
        status, freshness = "current", "current"
    elif verified_success:
        status, freshness = "stale", "stale"
    else:
        status, freshness = "unverified", "unverified"

    return {
        "schema_version": "operations-api.v1",
        "status": status,
        "freshness_status": freshness,
        "as_of_date": sydney_date,
        "logical_run_date": logical_date.isoformat() if logical_date and not future_invalid else None,
        "started_at": _safe_timestamp(run.get("started_at")),
        "completed_at": _safe_timestamp(run.get("completed_at")),
        "failed_stage": run.get("failed_stage")
        if run.get("failed_stage") in PIPELINE_STAGE_ORDER else None,
        "failure_category": _safe_failure(run.get("failure_category")),
        "stages": safe_stages,
        "stage_count": len(safe_stages),
        "stages_succeeded": sum(stage["status"] == "succeeded" for stage in safe_stages),
        "quality_checks_succeeded": sum(
            check["status"] == "passed" for stage in safe_stages for check in stage["quality_checks"]
        ),
        "quality_checks_total": len(PIPELINE_QUALITY_CHECKS) * len(PIPELINE_QUALITY_STAGES),
        "runbook_url": PIPELINE_RUNBOOK_URL,
    }


def _read_pipeline_health(client: Any, uri: str, sydney_date: str) -> dict[str, Any]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.lstrip("/"):
        raise RuntimeError("Pipeline status is not configured")
    response = client.get_object(Bucket=parsed.netloc, Key=parsed.path.lstrip("/"))
    raw = json.loads(response["Body"].read())
    if not isinstance(raw, dict):
        raise RuntimeError("Pipeline status is invalid")
    return sanitize_pipeline_health(raw, sydney_date)


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    request_id = event.get("requestContext", {}).get("requestId")
    try:
        subject, actor, permissions = _identity(event)
        method = str(event.get("requestContext", {}).get("http", {}).get("method") or "")
        path = str(event.get("rawPath") or "")
        if method == "GET" and path == "/v1/pipeline-health":
            if "health:read" not in permissions:
                raise PermissionError("Role cannot read Pipeline Health")
            import boto3
            return _response(
                200,
                _read_pipeline_health(boto3.client("s3"), PIPELINE_STATUS_S3_URI, _sydney_date()),
            )

        if method == "GET" and path == "/v1/risks":
            if "risks:read" not in permissions:
                raise PermissionError("Role cannot read Risks")
            import boto3
            params = event.get("queryStringParameters") or {}
            limit = min(max(int(params.get("limit", 50)), 1), 100)
            rows = _query_rows(
                boto3.client("athena"),
                build_risk_hotspots_query(limit, params.get("status"), _sydney_date()),
            )
            return _response(200, {"schema_version": "operations-api.v1", "items": rows, "next_token": None})

        if method == "GET" and path == "/v1/outcomes":
            if "outcomes:read" not in permissions:
                raise PermissionError("Role cannot read Outcomes")
            import boto3
            params = event.get("queryStringParameters") or {}
            limit = min(max(int(params.get("limit", 50)), 1), 100)
            rows = _query_rows(
                boto3.client("athena"),
                build_outcome_review_query(limit, params.get("status"), _sydney_date()),
            )
            return _response(200, {"schema_version": "operations-api.v1", "items": rows, "next_token": None})

        if method == "GET" and path == "/v1/actions":
            if "actions:read" not in permissions:
                raise PermissionError("Role cannot read Actions")
            import boto3
            params = event.get("queryStringParameters") or {}
            limit = min(max(int(params.get("limit", 50)), 1), 100)
            rows = _query_rows(boto3.client("athena"), build_action_queue_query(limit, params.get("status")))
            return _response(200, {"schema_version": "operations-api.v1", "items": rows, "next_token": None})

        match = re.fullmatch(r"/v1/actions/([^/]+)/events", path)
        if method == "POST" and match:
            action_id = match.group(1)
            if not SAFE_ID.fullmatch(action_id):
                raise ValueError("Invalid Action identifier")
            body = json.loads(event.get("body") or "{}")
            operation = str(body.get("operation") or "").upper()
            required = OPERATION_PERMISSION.get(operation)
            if not required or required not in permissions:
                raise PermissionError("Role cannot perform this Action operation")
            import boto3
            mutation_event = {
                "action_id": action_id,
                "operation": operation,
                "request_id": str(body.get("request_id") or ""),
                "reason": str(body.get("reason") or ""),
                "actor": actor,
                "actor_subject": subject,
                "logical_run_date": str(body.get("logical_run_date") or ""),
                "execution_mode": "OPERATIONAL",
                "time_basis": "ACTUAL_CALENDAR",
            }
            result = boto3.client("lambda").invoke(
                FunctionName=MUTATION_FUNCTION,
                InvocationType="RequestResponse",
                Payload=json.dumps(mutation_event).encode("utf-8"),
            )
            payload = json.loads(result["Payload"].read())
            if result.get("FunctionError"):
                mapped = _mutation_failure_response(payload, request_id)
                if mapped:
                    return mapped
                raise RuntimeError("Action mutation was rejected")
            return _response(200, {"schema_version": "operations-api.v1", "action": payload})
        return _response(404, {"error": "not_found", "request_id": request_id})
    except PermissionError as exc:
        return _response(403, {"error": "forbidden", "message": str(exc), "request_id": request_id})
    except (ValueError, json.JSONDecodeError) as exc:
        return _response(400, {"error": "invalid_request", "message": str(exc), "request_id": request_id})
    except Exception as exc:
        _record_failure_metric()
        LOGGER.error(
            "operations_api_failure exception=%s aws_error=%s request_id_present=%s",
            type(exc).__name__,
            _safe_aws_error_code(exc),
            bool(request_id),
        )
        return _response(503, {"error": "service_unavailable", "request_id": request_id})
