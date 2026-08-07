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
from typing import Any


DATABASE = os.getenv("ATHENA_SOURCE_DATABASE", "simulated_iceberg_m")
WORKGROUP = os.getenv("ATHENA_WORKGROUP", "primary")
OUTPUT = os.getenv("ATHENA_OUTPUT", "")
ACTION_VIEW = os.getenv("LIFECYCLE_ACTION_CURRENT_VIEW", "vw_lifecycle_action_current_staging_v1")
MUTATION_FUNCTION = os.getenv("ACTION_MUTATION_FUNCTION", "")
ROLE_PERMISSIONS = {
    "viewer": {"actions:read"},
    "operator": {"actions:read", "actions:complete"},
    "approver": {"actions:read", "actions:approve", "actions:reject"},
    "administrator": {"actions:read", "actions:approve", "actions:reject", "actions:complete"},
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


def _query_actions(client: Any, query: str) -> list[dict[str, str | None]]:
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
            raise RuntimeError("Action queue query failed")
        if time.monotonic() >= deadline:
            client.stop_query_execution(QueryExecutionId=query_id)
            raise TimeoutError("Action queue query timed out")
        time.sleep(0.25)


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    request_id = event.get("requestContext", {}).get("requestId")
    try:
        subject, actor, permissions = _identity(event)
        method = str(event.get("requestContext", {}).get("http", {}).get("method") or "")
        path = str(event.get("rawPath") or "")
        if method == "GET" and path == "/v1/actions":
            if "actions:read" not in permissions:
                raise PermissionError("Role cannot read Actions")
            import boto3
            params = event.get("queryStringParameters") or {}
            limit = min(max(int(params.get("limit", 50)), 1), 100)
            rows = _query_actions(boto3.client("athena"), build_action_queue_query(limit, params.get("status")))
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
