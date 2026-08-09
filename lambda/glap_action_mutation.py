"""Private, idempotent Action mutation handler for GLAP staging.

The proposed Action row is immutable.  Every EDIT, APPROVE, REJECT, or COMPLETE
operation appends one audit event; the current state is derived by an Athena
view.  This function has no public API integration or schedule.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import os
import re
import time
from typing import Any

from glap_temporal_boundary import resolve_temporal_context, temporal_scope_id


UTC = timezone.utc
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
SAFE_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._@+-]{1,127}$")
DATABASE = os.getenv("ATHENA_SOURCE_DATABASE", "simulated_iceberg_m")
WORKGROUP = os.getenv("ATHENA_WORKGROUP", "primary")
OUTPUT = os.getenv("ATHENA_OUTPUT", "")
ACTION_CURRENT_VIEW = os.getenv(
    "LIFECYCLE_ACTION_CURRENT_VIEW", "vw_lifecycle_action_current_staging_v1"
)
AUDIT_TABLE = os.getenv(
    "LIFECYCLE_ACTION_AUDIT_TABLE", "fact_lifecycle_action_audit_staging_v1"
)
TRANSITIONS = {
    ("PROPOSED", "EDIT"): "EDITED",
    ("PROPOSED", "APPROVE"): "APPROVED",
    ("PROPOSED", "REJECT"): "REJECTED",
    ("EDITED", "APPROVE"): "APPROVED",
    ("EDITED", "REJECT"): "REJECTED",
    ("APPROVED", "COMPLETE"): "COMPLETED",
}


class ActionConflictError(ValueError):
    """A competing request already consumed the Action's prior state."""


def _identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError("Unsafe Athena identifier")
    return value


def validate_configuration() -> None:
    for value in (DATABASE, ACTION_CURRENT_VIEW, AUDIT_TABLE):
        _identifier(value)
    if not OUTPUT.startswith("s3://"):
        raise ValueError("ATHENA_OUTPUT must be a private s3:// prefix")


def _literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, datetime):
        value = value.astimezone(UTC).replace(tzinfo=None)
        return f"TIMESTAMP '{value.isoformat(sep=' ', timespec='seconds')}'"
    if isinstance(value, date):
        return f"DATE '{value.isoformat()}'"
    return "'" + str(value).replace("'", "''") + "'"


def build_current_action_query(action_id: str, scope_id: str) -> str:
    return f"""SELECT action_id, status, action_owner, action_due_date,
approved_by, approved_at, completed_at
FROM {_identifier(DATABASE)}.{_identifier(ACTION_CURRENT_VIEW)}
WHERE action_id = {_literal(action_id)} AND temporal_scope_id = {_literal(scope_id)}"""


def build_idempotency_query(request_id: str, scope_id: str) -> str:
    return f"""SELECT event_id, action_id, event_type, previous_status, new_status,
actor, reason, occurred_at, action_owner, action_due_date
FROM {_identifier(DATABASE)}.{_identifier(AUDIT_TABLE)}
WHERE request_id = {_literal(request_id)} AND temporal_scope_id = {_literal(scope_id)}"""


def build_audit_merge(row: dict[str, Any]) -> str:
    columns = (
        "event_id", "request_id", "action_id", "event_type", "previous_status",
        "new_status", "actor", "reason", "occurred_at", "approved_by",
        "approved_at", "completed_at", "action_owner", "action_due_date",
        "created_date", "temporal_scope_id",
        "execution_mode", "time_basis", "as_of_date", "execution_scenario_id",
    )
    values = ", ".join(_literal(row.get(column)) for column in columns)
    names = ", ".join(columns)
    source_values = ", ".join(f"source.{column}" for column in columns)
    return f"""MERGE INTO {_identifier(DATABASE)}.{_identifier(AUDIT_TABLE)} AS target
USING (VALUES ({values})) AS source ({names})
ON target.temporal_scope_id = source.temporal_scope_id
AND (
  target.request_id = source.request_id
  OR (
    target.action_id = source.action_id
    AND target.previous_status = source.previous_status
  )
)
WHEN NOT MATCHED THEN INSERT ({names}) VALUES ({source_values})"""


def plan_mutation(
    event: dict[str, Any], current_action: dict[str, Any], now: datetime
) -> dict[str, Any]:
    operation = str(event.get("operation") or "").upper()
    action_id = str(event.get("action_id") or "")
    request_id = str(event.get("request_id") or "")
    actor = str(event.get("actor") or "").strip()
    reason = str(event.get("reason") or "").strip()
    if operation not in {"EDIT", "APPROVE", "REJECT", "COMPLETE"}:
        raise ValueError("operation must be EDIT, APPROVE, REJECT, or COMPLETE")
    if not SAFE_ID.fullmatch(action_id) or not SAFE_ID.fullmatch(request_id):
        raise ValueError("action_id and request_id must be safe stable identifiers")
    if not SAFE_ACTOR.fullmatch(actor) or actor.lower() in {"system", "automation", "model"}:
        raise ValueError("A named human actor is required")
    if len(reason) < 3 or len(reason) > 500:
        raise ValueError("A concise mutation reason is required")
    previous = str(current_action.get("status") or "")
    try:
        new_status = TRANSITIONS[(previous, operation)]
    except KeyError as exc:
        raise ValueError(f"Invalid Action transition: {previous} -> {operation}") from exc
    approved_by = current_action.get("approved_by")
    approved_at = current_action.get("approved_at")
    completed_at = current_action.get("completed_at")
    action_owner = current_action.get("action_owner")
    action_due_date = current_action.get("action_due_date")
    if isinstance(action_due_date, str) and action_due_date:
        action_due_date = date.fromisoformat(action_due_date)
    if operation == "EDIT":
        action_owner = str(event.get("action_owner") or "").strip()
        if (
            not SAFE_ACTOR.fullmatch(action_owner)
            or action_owner.lower() in {"system", "automation", "model"}
        ):
            raise ValueError("A named human Action owner is required")
        try:
            action_due_date = date.fromisoformat(str(event.get("action_due_date") or ""))
            logical_run_date = date.fromisoformat(str(event.get("logical_run_date") or ""))
        except ValueError as exc:
            raise ValueError("action_due_date and logical_run_date must be ISO dates") from exc
        if action_due_date < logical_run_date:
            raise ValueError("action_due_date cannot precede the operational date")
    elif operation == "APPROVE":
        approved_by, approved_at = actor, now
    elif operation == "COMPLETE":
        completed_at = now
    return {
        "event_id": hashlib.sha256(
            f"ACTION_AUDIT|{request_id}".encode("utf-8")
        ).hexdigest()[:32],
        "request_id": request_id,
        "action_id": action_id,
        "event_type": operation,
        "previous_status": previous,
        "new_status": new_status,
        "actor": actor,
        "reason": reason,
        "occurred_at": now,
        "approved_by": approved_by,
        "approved_at": approved_at,
        "completed_at": completed_at,
        "action_owner": action_owner,
        "action_due_date": action_due_date,
        "created_date": now.date(),
    }


def _parse_rows(response: dict[str, Any]) -> list[dict[str, str | None]]:
    result = response.get("ResultSet", {})
    rows = result.get("Rows", [])
    columns = result.get("ResultSetMetadata", {}).get("ColumnInfo", [])
    headers = [str(column.get("Name")) for column in columns]
    if not rows or not headers:
        return []
    parsed = []
    for row in rows[1:]:
        values = [cell.get("VarCharValue") for cell in row.get("Data", [])]
        values.extend([None] * (len(headers) - len(values)))
        parsed.append(dict(zip(headers, values)))
    return parsed


def _run_query(client: Any, query: str) -> list[dict[str, str | None]]:
    query_id = client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={"Database": DATABASE},
        ResultConfiguration={"OutputLocation": OUTPUT},
        WorkGroup=WORKGROUP,
    )["QueryExecutionId"]
    deadline = time.monotonic() + 120
    while True:
        execution = client.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]
        state = execution["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in {"FAILED", "CANCELLED"}:
            raise RuntimeError(f"Athena Action mutation query {state.lower()}")
        if time.monotonic() >= deadline:
            client.stop_query_execution(QueryExecutionId=query_id)
            raise TimeoutError("Athena Action mutation query timed out")
        time.sleep(1)
    return _parse_rows(client.get_query_results(QueryExecutionId=query_id, MaxResults=10))


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    validate_configuration()
    logical_date = str(event.get("logical_run_date") or "")
    temporal = resolve_temporal_context(logical_date, event)
    scope_id = temporal_scope_id(temporal)
    action_id = str(event.get("action_id") or "")
    request_id = str(event.get("request_id") or "")
    if not SAFE_ID.fullmatch(action_id) or not SAFE_ID.fullmatch(request_id):
        raise ValueError("action_id and request_id must be safe stable identifiers")
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("boto3 is required for Athena mutation") from exc
    client = boto3.client("athena", region_name=os.getenv("AWS_REGION", "us-east-1"))
    replay = _run_query(client, build_idempotency_query(request_id, scope_id))
    if replay:
        row = replay[0]
        if row.get("action_id") != action_id:
            raise ValueError("request_id is already bound to another Action")
        return {
            "status": "success", "idempotent_replay": True,
            "action_id": action_id, "event_id": row.get("event_id"),
            "action_status": row.get("new_status"),
            "action_owner": row.get("action_owner"),
            "action_due_date": row.get("action_due_date"), **temporal,
        }
    actions = _run_query(client, build_current_action_query(action_id, scope_id))
    if len(actions) != 1:
        raise ValueError("Action was not found in the requested temporal scope")
    current = dict(actions[0])
    for field in ("approved_at", "completed_at"):
        if current.get(field):
            current[field] = datetime.fromisoformat(str(current[field])).replace(tzinfo=UTC)
    if current.get("action_due_date"):
        current["action_due_date"] = date.fromisoformat(str(current["action_due_date"]))
    mutation = plan_mutation(event, current, datetime.now(UTC))
    mutation.update({
        "temporal_scope_id": scope_id,
        "execution_mode": temporal["execution_mode"],
        "time_basis": temporal["time_basis"],
        "as_of_date": date.fromisoformat(str(temporal["as_of_date"])),
        "execution_scenario_id": temporal["scenario_id"],
    })
    if not event.get("dry_run", False):
        _run_query(client, build_audit_merge(mutation))
        confirmed = _run_query(client, build_idempotency_query(request_id, scope_id))
        if not confirmed:
            raise ActionConflictError(
                "A competing request already changed the Action from its prior state"
            )
    return {
        "status": "success", "idempotent_replay": False,
        "action_id": action_id, "event_id": mutation["event_id"],
        "previous_status": mutation["previous_status"],
        "action_status": mutation["new_status"],
        "action_owner": mutation["action_owner"],
        "action_due_date": mutation["action_due_date"],
        "dry_run": bool(event.get("dry_run", False)), **temporal,
    }
