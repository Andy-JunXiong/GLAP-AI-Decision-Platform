"""Success-gated controller for the current GLAP daily pipeline.

The controller invokes an environment-configured sequence of Lambda stages and
persists a public-safe run status after every transition. It intentionally does
not know the deployed function names or expose them in the status contract.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
import os
import re
import time
import uuid
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import boto3
from botocore.config import Config

from glap_quality_contracts import QUALITY_CONTRACTS
from glap_temporal_boundary import OPERATIONAL, resolve_temporal_context


SUCCESS_STATES = {"ok", "success", "succeeded"}
SAFE_STAGE_NAME = re.compile(r"^[a-z][a-z0-9_]{1,47}$")

lambda_client = boto3.client(
    "lambda",
    config=Config(
        connect_timeout=5,
        read_timeout=900,
        retries={"max_attempts": 0},
    ),
)
s3_client = boto3.client("s3")


class StageFailure(RuntimeError):
    def __init__(
        self, category: str, quality_checks: list[dict[str, str]] | None = None
    ) -> None:
        super().__init__(category)
        self.category = category
        self.quality_checks = quality_checks or []


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def load_stage_config(raw: str | None = None) -> list[dict[str, Any]]:
    raw = raw if raw is not None else os.environ.get("PIPELINE_STAGES_JSON")
    if not raw:
        raise ValueError("PIPELINE_STAGES_JSON is required")
    try:
        stages = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("PIPELINE_STAGES_JSON must be valid JSON") from exc
    if not isinstance(stages, list) or not 2 <= len(stages) <= 16:
        raise ValueError("PIPELINE_STAGES_JSON must contain 2 to 16 stages")

    names: set[str] = set()
    validated: list[dict[str, Any]] = []
    for stage in stages:
        if not isinstance(stage, dict):
            raise ValueError("Each pipeline stage must be an object")
        name = stage.get("name")
        function_name = stage.get("function_name")
        if not isinstance(name, str) or not SAFE_STAGE_NAME.fullmatch(name):
            raise ValueError("Pipeline stage names must be safe lowercase identifiers")
        if name in names:
            raise ValueError(f"Duplicate pipeline stage name: {name}")
        if not isinstance(function_name, str) or not function_name.strip():
            raise ValueError(f"Pipeline stage {name} requires function_name")
        quality_contract = stage.get("quality_contract")
        quality_gate = stage.get("quality_gate") is True or quality_contract is not None
        if quality_gate and quality_contract is None:
            quality_contract = "pipeline_v1"
        if quality_contract is not None and quality_contract not in QUALITY_CONTRACTS:
            raise ValueError(f"Unsupported quality contract: {quality_contract}")
        names.add(name)
        validated.append(
            {
                "name": name,
                "function_name": function_name,
                "quality_gate": quality_gate,
                "quality_contract": quality_contract,
            }
        )
    return validated


def parse_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.lstrip("/"):
        raise ValueError("PIPELINE_STATUS_S3_URI must be a complete s3:// URI")
    return parsed.netloc, parsed.path.lstrip("/")


def new_run(
    logical_run_date: str,
    stages: list[dict[str, Any]],
    now: datetime,
    temporal_context: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    date.fromisoformat(logical_run_date)
    temporal_context = temporal_context or {
        "execution_mode": OPERATIONAL,
        "time_basis": "ACTUAL_CALENDAR",
        "as_of_date": logical_run_date,
        "scenario_id": None,
    }
    return {
        "schema_version": "1.1",
        "logical_run_date": logical_run_date,
        **temporal_context,
        "started_at": iso_timestamp(now),
        "completed_at": None,
        "status": "running",
        "failed_stage": None,
        "failure_category": None,
        "stages": [
            {
                "name": stage["name"],
                "started_at": None,
                "completed_at": None,
                "duration_ms": None,
                "status": "blocked",
                "failure_category": None,
                "quality_checks": [],
            }
            for stage in stages
        ],
    }


def persist_run(run: dict[str, Any], status_uri: str) -> None:
    bucket, key = parse_s3_uri(status_uri)
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=(json.dumps(run, separators=(",", ":")) + "\n").encode("utf-8"),
        ContentType="application/json",
        ServerSideEncryption="AES256",
    )


def load_existing_run(status_uri: str) -> dict[str, Any] | None:
    bucket, key = parse_s3_uri(status_uri)
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
    except Exception as exc:
        error = getattr(exc, "response", {}).get("Error", {})
        if error.get("Code") in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise
    raw = response["Body"].read()
    try:
        value = json.loads(raw)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Existing pipeline status is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("Existing pipeline status must be a JSON object")
    return value


def temporal_status_uri(
    status_uri: str, temporal_context: dict[str, str | None]
) -> str:
    if temporal_context["execution_mode"] == OPERATIONAL:
        return status_uri
    bucket, key = parse_s3_uri(status_uri)
    prefix = key.rsplit("/", 1)[0] if "/" in key else ""
    scenario_id = str(temporal_context["scenario_id"])
    simulation_key = "/".join(
        part for part in (prefix, "simulations", scenario_id, "latest.json") if part
    )
    return f"s3://{bucket}/{simulation_key}"


def archive_legacy_future_status(
    status_uri: str,
    existing_run: dict[str, Any],
    temporal_context: dict[str, str | None],
) -> bool:
    if temporal_context["execution_mode"] != OPERATIONAL:
        return False
    if "execution_mode" in existing_run:
        return False
    try:
        existing_date = date.fromisoformat(str(existing_run["logical_run_date"]))
        as_of_date = date.fromisoformat(str(temporal_context["as_of_date"]))
    except (KeyError, TypeError, ValueError):
        return False
    if existing_date <= as_of_date:
        return False

    archive_context = {
        "execution_mode": "FUTURE_SIMULATION",
        "time_basis": "FUTURE_SIMULATION",
        "as_of_date": temporal_context["as_of_date"],
        "scenario_id": "legacy-pre-boundary-2026",
    }
    archived_run = {**existing_run, **archive_context}
    persist_run(archived_run, temporal_status_uri(status_uri, archive_context))
    return True


def parse_stage_payload(response: dict[str, Any]) -> dict[str, Any]:
    if response.get("FunctionError"):
        raise StageFailure("dependency_failure")
    payload = response.get("Payload")
    if payload is None:
        raise StageFailure("invalid_response")
    raw = payload.read() if hasattr(payload, "read") else payload
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        body = json.loads(raw)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StageFailure("invalid_response") from exc
    if not isinstance(body, dict):
        raise StageFailure("invalid_response")
    explicit_ok = body.get("ok")
    status_succeeded = str(body.get("status", "")).lower() in SUCCESS_STATES
    if explicit_ok is False or not (status_succeeded or explicit_ok is True):
        raise StageFailure("dependency_failure")
    return body


def validate_quality_checks(
    body: dict[str, Any], required_names: frozenset[str]
) -> list[dict[str, str]]:
    raw_checks = body.get("quality_checks")
    if not isinstance(raw_checks, dict) or set(raw_checks) != set(required_names):
        raise StageFailure("quality_contract_invalid")
    checks = []
    for name in sorted(required_names):
        state = str(raw_checks[name]).lower()
        if state not in {"passed", "failed"}:
            raise StageFailure("quality_contract_invalid")
        checks.append({"name": name, "status": state})
    if any(check["status"] != "passed" for check in checks):
        raise StageFailure("quality_gate_failed", checks)
    return checks


def _validate_generator_receipt(body: dict, stage: dict, event: dict, link: dict) -> dict:
    """Validate private linkage only; never copy this receipt into run status."""
    receipt = body.get("execution_receipt")
    if receipt is None and "execution_receipt" not in body:
        return {"receipt_state": "UNAVAILABLE_LEGACY"}
    try:
        expected = {
            "schema_version", "invocation_id", "function_name", "function_version",
            "controller_link", "controller_link_trusted", "logical_date", "temporal_context",
            "source_bundle_sha256", "settings_sha256", "request_parameters_sha256", "started_at",
            "finished_at", "status", "dry_run", "generated_counts", "planned_write_statements",
            "completed_write_statements", "queries", "complete", "runtime_verified",
            "snapshot_lineage_verified", "real_world_evidence",
        }
        if not isinstance(receipt, dict) or set(receipt) != expected:
            raise ValueError
        request_id_pattern = r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}"
        if (receipt["schema_version"] != "generator-execution-receipt.v1"
                or not re.fullmatch(request_id_pattern, receipt["invocation_id"])
                or receipt["function_name"] != stage["function_name"]
                or not re.fullmatch(r"\$LATEST|[0-9]{1,20}", receipt["function_version"])
                or receipt["controller_link"] != link
                or receipt["logical_date"] != event["logical_run_date"]
                or receipt["temporal_context"] != {key: event[key] for key in (
                    "execution_mode", "time_basis", "as_of_date", "scenario_id")}
                or receipt["status"] != "SUCCEEDED" or receipt["complete"] is not True
                or any(receipt[key] is not False for key in (
                    "dry_run", "controller_link_trusted", "runtime_verified",
                    "snapshot_lineage_verified", "real_world_evidence"))):
            raise ValueError
        for key in ("source_bundle_sha256", "settings_sha256", "request_parameters_sha256"):
            if not re.fullmatch(r"[a-f0-9]{64}", receipt[key]):
                raise ValueError
        counts = receipt["generated_counts"]
        if not isinstance(counts, dict) or set(counts) != {"outcomes", "proposals"}:
            raise ValueError
        values = [*counts.values(), receipt["planned_write_statements"], receipt["completed_write_statements"]]
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError
        if any(type(body.get(key)) is not int or body[key] < 0 for key in (
                "outcome_rows_created", "policy_proposal_rows_created", "write_statements")):
            raise ValueError
        if (counts["outcomes"] != body.get("outcome_rows_created") or
                counts["proposals"] != body.get("policy_proposal_rows_created") or
                body.get("dry_run") is not False or
                receipt["planned_write_statements"] != body.get("write_statements") or
                receipt["completed_write_statements"] != receipt["planned_write_statements"]):
            raise ValueError
        queries = receipt["queries"]
        if not isinstance(queries, list) or not 9 <= len(queries) <= 256:
            raise ValueError
        seen, reads, writes = set(), set(), 0
        start = datetime.fromisoformat(receipt["started_at"])
        finish = datetime.fromisoformat(receipt["finished_at"])
        stage_start = datetime.fromisoformat(link["stage_started_at"])
        if start.utcoffset() is None or finish.utcoffset() is None or not stage_start <= start <= finish:
            raise ValueError
        previous_finish = start
        expected_reads = {"READ_TARGETS", "READ_ROUTES", "READ_RATES", "READ_FX", "READ_ACTIVE",
                          "READ_ALERTS", "READ_ACTIONS", "READ_OUTCOMES", "READ_PROPOSALS"}
        for index, query in enumerate(queries, 1):
            if not isinstance(query, dict) or set(query) != {
                "sequence", "purpose", "query_id", "statement_sha256", "started_at", "finished_at",
                "status", "athena_state", "result_reused"}:
                raise ValueError
            if (type(query["sequence"]) is not int or query["sequence"] != index or
                    not re.fullmatch(request_id_pattern, query["query_id"]) or query["query_id"] in seen
                    or query["status"] != "SUCCEEDED" or query["athena_state"] != "SUCCEEDED"
                    or not re.fullmatch(r"[a-f0-9]{64}", query["statement_sha256"])
                    or (query["result_reused"] is not None and type(query["result_reused"]) is not bool)):
                raise ValueError
            seen.add(query["query_id"])
            query_start = datetime.fromisoformat(query["started_at"])
            query_finish = datetime.fromisoformat(query["finished_at"])
            if (query_start.utcoffset() is None or query_finish.utcoffset() is None
                    or not previous_finish <= query_start <= query_finish <= finish):
                raise ValueError
            previous_finish = query_finish
            purpose = query["purpose"]
            if purpose in expected_reads and purpose not in reads and not writes:
                reads.add(purpose)
            elif purpose == "WRITE_MERGE" and reads == expected_reads:
                writes += 1
            else:
                raise ValueError
        if reads != expected_reads or writes != receipt["completed_write_statements"]:
            raise ValueError
        return {"receipt_state": "PRESENT_LOCALLY_VALIDATED", "invocation_id": receipt["invocation_id"],
                "query_count": len(queries), "generated_outcomes": counts["outcomes"],
                "generated_proposals": counts["proposals"]}
    except (ValueError, TypeError, KeyError, OverflowError):
        raise StageFailure("invalid_response") from None


def invoke_stage(stage: dict[str, Any], event: dict[str, Any], *,
                 run_started_at: str | None = None, stage_started_at: str | None = None) -> list[dict[str, str]]:
    invocation_event = dict(event)
    link = None
    if stage["name"] == "stateful_lifecycle_generation":
        timestamp = iso_timestamp(utc_now())
        link = {"link_id": uuid.uuid4().hex, "run_started_at": run_started_at or timestamp,
                "stage_started_at": stage_started_at or timestamp}
        invocation_event["execution_link"] = link
        print(json.dumps({"schema_version": "generator-controller-link.v1", **link,
                          "state": "REQUESTED", "logical_date": event["logical_run_date"],
                          "runtime_verified": False}, sort_keys=True), flush=True)
    quality_contract = stage.get("quality_contract") or (
        "pipeline_v1" if stage.get("quality_gate") is True else None
    )
    if quality_contract:
        invocation_event["quality_contract"] = quality_contract
    response = lambda_client.invoke(
        FunctionName=stage["function_name"],
        InvocationType="RequestResponse",
        Payload=json.dumps(invocation_event).encode("utf-8"),
    )
    body = parse_stage_payload(response)
    if link is not None:
        summary = _validate_generator_receipt(body, stage, invocation_event, link)
        print(json.dumps({"schema_version": "generator-controller-link.v1", **link,
                          "state": "RETURNED", "logical_date": event["logical_run_date"],
                          "runtime_verified": False, **summary}, sort_keys=True), flush=True)
    return (
        validate_quality_checks(body, QUALITY_CONTRACTS[quality_contract])
        if stage["quality_gate"]
        else []
    )


def execute_pipeline(
    stages: list[dict[str, Any]],
    logical_run_date: str,
    status_uri: str,
    dry_run: bool = False,
    retry_failed_run: bool = False,
    temporal_context: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    temporal_context = temporal_context or {
        "execution_mode": OPERATIONAL,
        "time_basis": "ACTUAL_CALENDAR",
        "as_of_date": logical_run_date,
        "scenario_id": None,
    }
    run = new_run(logical_run_date, stages, utc_now(), temporal_context)
    if dry_run:
        completed_at = utc_now()
        run.update(
            {
                "completed_at": iso_timestamp(completed_at),
                "status": "succeeded",
                "dry_run": True,
            }
        )
        for stage_run in run["stages"]:
            stage_run["status"] = "not_invoked"
        return run

    existing_run = load_existing_run(status_uri)
    if existing_run and archive_legacy_future_status(
        status_uri, existing_run, temporal_context
    ):
        existing_run = None
    if retry_failed_run and not existing_run:
        raise ValueError("Recovery requires an existing failed run for the same date")
    if existing_run:
        existing_date = validate_run_date(existing_run.get("logical_run_date"))
        requested_date = date.fromisoformat(logical_run_date)
        if existing_date > requested_date:
            raise ValueError(
                "Refusing to overwrite a newer pipeline run "
                f"(existing_date={existing_date.isoformat()}, "
                f"requested_date={requested_date.isoformat()})"
            )
        if retry_failed_run and existing_date != requested_date:
            raise ValueError("Recovery requires an existing failed run for the same date")
        if existing_date == requested_date:
            existing_mode = str(existing_run.get("execution_mode") or OPERATIONAL)
            existing_scenario = existing_run.get("scenario_id")
            if (
                existing_mode != temporal_context["execution_mode"]
                or existing_scenario != temporal_context["scenario_id"]
            ):
                raise ValueError("Refusing to reuse a run from a different temporal context")
            if retry_failed_run:
                failed_stage = existing_run.get("failed_stage")
                failure_category = existing_run.get("failure_category")
                retryable_dependency = (
                    existing_run.get("status") == "failed"
                    and failed_stage == stages[0]["name"]
                    and failure_category == "dependency_failure"
                )
                retryable_quality_gate = (
                    existing_run.get("status") == "failed"
                    and failure_category == "quality_gate_failed"
                    and any(
                        stage["name"] == failed_stage and stage["quality_gate"]
                        for stage in stages
                    )
                )
                if not (retryable_dependency or retryable_quality_gate):
                    raise ValueError(
                        "Recovery is allowed only for a first-stage dependency failure "
                        "or a configured quality-gate failure"
                    )
            else:
                # Reuse every same-day terminal or indeterminate status. Reinvoking a
                # current mutating stage could duplicate business records after a
                # timeout or partial failure, so recovery requires the explicit,
                # narrowly guarded retry path above.
                return existing_run

    persist_run(run, status_uri)

    for index, stage in enumerate(stages):
        stage_run = run["stages"][index]
        started_at = utc_now()
        started_clock = time.monotonic()
        stage_run.update({"started_at": iso_timestamp(started_at), "status": "running"})
        persist_run(run, status_uri)

        try:
            checks = invoke_stage(
                stage,
                {
                    "logical_run_date": logical_run_date,
                    "run_date": logical_run_date,
                    "pipeline_stage": stage["name"],
                    "dry_run": dry_run,
                    "retry_failed_run": retry_failed_run,
                    **temporal_context,
                },
                run_started_at=run["started_at"],
                stage_started_at=stage_run["started_at"],
            )
        except StageFailure as exc:
            completed_at = utc_now()
            stage_run.update(
                {
                    "completed_at": iso_timestamp(completed_at),
                    "duration_ms": max(0, int((time.monotonic() - started_clock) * 1000)),
                    "status": "failed",
                    "failure_category": exc.category,
                    "quality_checks": exc.quality_checks,
                }
            )
            run.update(
                {
                    "completed_at": iso_timestamp(completed_at),
                    "status": "failed",
                    "failed_stage": stage["name"],
                    "failure_category": exc.category,
                }
            )
            persist_run(run, status_uri)
            return run
        except Exception:
            completed_at = utc_now()
            stage_run.update(
                {
                    "completed_at": iso_timestamp(completed_at),
                    "duration_ms": max(0, int((time.monotonic() - started_clock) * 1000)),
                    "status": "failed",
                    "failure_category": "unexpected_failure",
                }
            )
            run.update(
                {
                    "completed_at": iso_timestamp(completed_at),
                    "status": "failed",
                    "failed_stage": stage["name"],
                    "failure_category": "unexpected_failure",
                }
            )
            persist_run(run, status_uri)
            return run

        completed_at = utc_now()
        stage_run.update(
            {
                "completed_at": iso_timestamp(completed_at),
                "duration_ms": max(0, int((time.monotonic() - started_clock) * 1000)),
                "status": "succeeded",
                "quality_checks": checks,
            }
        )
        persist_run(run, status_uri)

    completed_at = utc_now()
    run.update({"completed_at": iso_timestamp(completed_at), "status": "succeeded"})
    persist_run(run, status_uri)
    return run


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    event = event if isinstance(event, dict) else {}
    stages = load_stage_config()
    status_uri = os.environ.get("PIPELINE_STATUS_S3_URI")
    if not status_uri:
        raise ValueError("PIPELINE_STATUS_S3_URI is required")
    logical_run_date = event.get("logical_run_date")
    if not logical_run_date:
        timezone_name = os.getenv("PIPELINE_TIMEZONE", "Australia/Sydney")
        try:
            pipeline_timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown PIPELINE_TIMEZONE: {timezone_name}") from exc
        logical_run_date = utc_now().astimezone(pipeline_timezone).date().isoformat()
    dry_run = event.get("dry_run") is True
    retry_failed_run = event.get("retry_failed_run") is True
    temporal_context = resolve_temporal_context(
        logical_run_date,
        event,
        now=utc_now(),
    )
    effective_status_uri = temporal_status_uri(status_uri, temporal_context)
    run = execute_pipeline(
        stages,
        logical_run_date,
        effective_status_uri,
        dry_run=dry_run,
        retry_failed_run=retry_failed_run,
        temporal_context=temporal_context,
    )
    if run["status"] == "running":
        raise RuntimeError("Pipeline run is already running or has indeterminate state")
    if run["status"] != "succeeded":
        # Raising makes EventBridge Scheduler apply its retry and DLQ policy. The
        # sanitized failure record has already been persisted for OPS readers.
        failed_checks = []
        for stage in run.get("stages", []):
            if stage.get("name") == run.get("failed_stage"):
                failed_checks = sorted(
                    check["name"]
                    for check in stage.get("quality_checks", [])
                    if check.get("status") == "failed"
                )
                break
        check_detail = (
            f"; failed_checks={','.join(failed_checks)}" if failed_checks else ""
        )
        raise RuntimeError(
            f"Pipeline failed at {run['failed_stage']}: "
            f"{run['failure_category']}{check_detail}"
        )
    return run


def validate_run_date(value: Any) -> date:
    if not isinstance(value, str):
        raise ValueError("Existing pipeline status has no logical_run_date")
    return date.fromisoformat(value)
