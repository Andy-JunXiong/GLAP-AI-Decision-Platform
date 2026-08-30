"""Validate an aggregate AWS observation and build a public-safe System candidate.

This exporter deliberately has no AWS client. A separately authorized collector
must supply an aggregate-only observation that already excludes every resource
identifier. The tracked Sites snapshot is never overwritten by this command.
"""

from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "decision-brief-demo/contracts/system-evidence-source.v2.json"
TRACKED_SNAPSHOT_PATH = (
    ROOT / "decision-brief-demo/public/data/system-evidence-snapshot.json"
)

OBSERVATION_SCHEMA_VERSION = "system-runtime-observation.v1"
PUBLIC_SCHEMA_VERSION = "public-system-evidence-snapshot.v2"
SOURCE_SCHEMA_VERSION = "system-evidence-source.v2"
SERVICE_DETAILS = (
    (
        "storage",
        "Amazon S3",
        "Iceberg data files and Athena query results; resource names and paths remain private.",
    ),
    (
        "catalog",
        "AWS Glue",
        "Governed table metadata for production analytics and isolated staging lifecycle data.",
    ),
    (
        "analytics",
        "Amazon Athena",
        "Cutoff-safe SQL analytics and Iceberg operations with bounded failure handling.",
    ),
    (
        "compute",
        "AWS Lambda",
        "Deterministic orchestration, validation, export, and bounded release functions.",
    ),
    (
        "reliability",
        "Scheduler + SQS",
        "Production scheduling, bounded retries, and encrypted dead-letter recovery.",
    ),
    (
        "observability",
        "CloudWatch + SNS",
        "Safe alarms and notifications while subscriber details remain protected.",
    ),
)
SERVICE_KEYS = tuple(item[0] for item in SERVICE_DETAILS)
RELIABILITY = {
    "stage_count": 6,
    "quality_check_count": 10,
    "retry_count": 2,
    "max_event_age_hours": 24,
    "dlq_retention_days": 14,
}
AUTHORITY = {
    "aws_write": False,
    "infrastructure_change": False,
    "production_alias_move": False,
    "schedule_change": False,
    "action_mutation": False,
    "policy_activation": False,
    "model_promotion": False,
}
PROTECTED_VALUE_PATTERNS = (
    re.compile(r"arn:aws", re.IGNORECASE),
    re.compile(r"s3://", re.IGNORECASE),
    re.compile(r"\b\d{12}\b"),
    re.compile(r"https://[^\s]*\.amazonaws\.com", re.IGNORECASE),
)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain one JSON object")
    return value


def _exact_keys(value: Any, expected: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == expected


def _contains_protected_value(value: Any) -> bool:
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in PROTECTED_VALUE_PATTERNS)
    if isinstance(value, dict):
        return any(_contains_protected_value(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_protected_value(item) for item in value)
    return False


def _sydney_date_for_utc_timestamp(value: str) -> date:
    if not value.endswith("Z"):
        raise ValueError("observed_at_utc must be an ISO-8601 UTC timestamp ending in Z")
    try:
        observed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("observed_at_utc must be an ISO-8601 UTC timestamp") from exc
    if observed.tzinfo != timezone.utc:
        raise ValueError("observed_at_utc must use UTC")
    return observed.astimezone(ZoneInfo("Australia/Sydney")).date()


def validate_runtime_observation(
    observation: dict[str, Any], today: date | None = None
) -> list[str]:
    errors: list[str] = []
    current_date = today or datetime.now(ZoneInfo("Australia/Sydney")).date()
    expected_root = {
        "schema_version",
        "as_of_date",
        "observed_at_utc",
        "evidence_class",
        "aggregate_only",
        "read_only",
        "athena_query_started",
        "external_write",
        "identifiers_retained",
        "production_track",
        "staging_track",
        "reliability",
        "services",
        "authority",
    }
    if not _exact_keys(observation, expected_root):
        errors.append("runtime observation envelope has drifted")
    if observation.get("schema_version") != OBSERVATION_SCHEMA_VERSION:
        errors.append("runtime observation schema is unsupported")
    if observation.get("evidence_class") != "AWS_CONTROL_PLANE_READS":
        errors.append("runtime observation evidence class has drifted")
    if observation.get("aggregate_only") is not True:
        errors.append("runtime observation must be aggregate-only")
    if observation.get("read_only") is not True:
        errors.append("runtime observation must be read-only")
    if observation.get("athena_query_started") is not False:
        errors.append("runtime observation must not start Athena")
    if observation.get("external_write") is not False:
        errors.append("runtime observation must not perform an external write")
    if observation.get("identifiers_retained") is not False:
        errors.append("runtime observation must not retain identifiers")

    try:
        as_of_date = date.fromisoformat(str(observation.get("as_of_date")))
        if as_of_date != current_date:
            errors.append("runtime observation must use the current Sydney date")
    except ValueError:
        as_of_date = None
        errors.append("as_of_date must use YYYY-MM-DD")
    try:
        observed_date = _sydney_date_for_utc_timestamp(
            str(observation.get("observed_at_utc"))
        )
        if as_of_date is not None and observed_date != as_of_date:
            errors.append("observed_at_utc does not reconcile to as_of_date in Sydney")
    except ValueError as exc:
        errors.append(str(exc))

    if observation.get("production_track") != {
        "scheduler_targets_prod_alias": True,
        "immutable_alias": True,
    }:
        errors.append("production runtime boundary is not verified")
    if observation.get("staging_track") != {
        "manual_only": True,
        "scheduler_present": False,
        "production_alias_present": False,
        "production_table_write": False,
    }:
        errors.append("staging isolation is not verified")
    if observation.get("reliability") != RELIABILITY:
        errors.append("runtime reliability controls have drifted")
    if observation.get("authority") != AUTHORITY:
        errors.append("runtime observation has gained authority")

    services = observation.get("services")
    if not isinstance(services, list) or len(services) != len(SERVICE_KEYS):
        errors.append("runtime service verification is incomplete")
    else:
        for index, service in enumerate(services):
            if service != {"key": SERVICE_KEYS[index], "verified": True}:
                errors.append("runtime service verification order or state has drifted")
                break
    if _contains_protected_value(observation):
        errors.append("runtime observation contains a protected identifier value")
    return errors


def _load_public_service_template() -> list[dict[str, Any]]:
    source = load_json(SOURCE_PATH)
    if source.get("schema_version") != SOURCE_SCHEMA_VERSION:
        raise ValueError("System evidence source schema is unsupported")
    public_snapshot = source.get("public_snapshot")
    if not isinstance(public_snapshot, dict):
        raise ValueError("System evidence public source is missing")
    if public_snapshot.get("reliability") != RELIABILITY:
        raise ValueError("System evidence source reliability controls have drifted")
    if public_snapshot.get("authority") != AUTHORITY:
        raise ValueError("System evidence source authority has drifted")
    services = public_snapshot.get("services")
    if not isinstance(services, list) or len(services) != len(SERVICE_KEYS):
        raise ValueError("System evidence source services are incomplete")
    for index, service in enumerate(services):
        expected_key, expected_label, expected_responsibility = SERVICE_DETAILS[index]
        if not _exact_keys(service, {"key", "label", "status", "responsibility"}):
            raise ValueError("System evidence source service shape has drifted")
        if (
            service.get("key") != expected_key
            or service.get("label") != expected_label
            or service.get("responsibility") != expected_responsibility
        ):
            raise ValueError("System evidence source service order has drifted")
        if service.get("status") != "DEPLOYED_ARCHITECTURE":
            raise ValueError("System evidence source service status has drifted")
        if not isinstance(service.get("label"), str) or not isinstance(
            service.get("responsibility"), str
        ):
            raise ValueError("System evidence source public copy is invalid")
    if _contains_protected_value(services):
        raise ValueError("System evidence source contains a protected identifier value")
    return deepcopy(services)


def build_public_runtime_snapshot(
    observation: dict[str, Any], today: date | None = None
) -> dict[str, Any]:
    errors = validate_runtime_observation(observation, today=today)
    if errors:
        raise ValueError("invalid runtime observation: " + "; ".join(errors))
    services = _load_public_service_template()
    for service in services:
        service["status"] = "RUNTIME_VERIFIED"
    snapshot = {
        "schema_version": PUBLIC_SCHEMA_VERSION,
        "as_of_date": observation["as_of_date"],
        "evidence_class": "AWS_RUNTIME_INSPECTION",
        "live_aws_inspection": True,
        "read_only": True,
        "disclosure": (
            "Derived from an aggregate read-only AWS control-plane inspection; "
            "not production readiness evidence."
        ),
        "source_provenance": {
            "mode": "AWS_CONTROL_PLANE_READS",
            "observation_contract": OBSERVATION_SCHEMA_VERSION,
            "athena_query_started": False,
            "external_write": False,
            "identifiers_retained": False,
        },
        "production_track": {
            "status": "RUNTIME_VERIFIED",
            "scheduler_target": "PROD_ALIAS",
            "immutable_alias": True,
        },
        "staging_track": {
            "status": "RUNTIME_VERIFIED",
            **observation["staging_track"],
        },
        "reliability": deepcopy(RELIABILITY),
        "services": services,
        "authority": deepcopy(AUTHORITY),
    }
    errors = validate_public_runtime_snapshot(snapshot, today=today)
    if errors:
        raise ValueError("generated public System snapshot is invalid: " + "; ".join(errors))
    return snapshot


def validate_public_runtime_snapshot(
    snapshot: dict[str, Any], today: date | None = None
) -> list[str]:
    errors: list[str] = []
    current_date = today or datetime.now(ZoneInfo("Australia/Sydney")).date()
    expected_root = {
        "schema_version",
        "as_of_date",
        "evidence_class",
        "live_aws_inspection",
        "read_only",
        "disclosure",
        "source_provenance",
        "production_track",
        "staging_track",
        "reliability",
        "services",
        "authority",
    }
    if not _exact_keys(snapshot, expected_root):
        errors.append("public System snapshot envelope has drifted")
    if snapshot.get("schema_version") != PUBLIC_SCHEMA_VERSION:
        errors.append("public System snapshot schema is unsupported")
    if snapshot.get("evidence_class") != "AWS_RUNTIME_INSPECTION":
        errors.append("public System snapshot evidence class has drifted")
    if snapshot.get("live_aws_inspection") is not True or snapshot.get("read_only") is not True:
        errors.append("public System snapshot runtime/read-only mode has drifted")
    try:
        as_of_date = date.fromisoformat(str(snapshot.get("as_of_date")))
        if as_of_date != current_date:
            errors.append("public runtime System snapshot must use the current Sydney date")
    except ValueError:
        errors.append("public System as_of_date must use YYYY-MM-DD")
    if snapshot.get("disclosure") != (
        "Derived from an aggregate read-only AWS control-plane inspection; "
        "not production readiness evidence."
    ):
        errors.append("public System disclosure has drifted")
    if snapshot.get("source_provenance") != {
        "mode": "AWS_CONTROL_PLANE_READS",
        "observation_contract": OBSERVATION_SCHEMA_VERSION,
        "athena_query_started": False,
        "external_write": False,
        "identifiers_retained": False,
    }:
        errors.append("public System provenance has drifted")
    if snapshot.get("production_track") != {
        "status": "RUNTIME_VERIFIED",
        "scheduler_target": "PROD_ALIAS",
        "immutable_alias": True,
    }:
        errors.append("public production track has drifted")
    if snapshot.get("staging_track") != {
        "status": "RUNTIME_VERIFIED",
        "manual_only": True,
        "scheduler_present": False,
        "production_alias_present": False,
        "production_table_write": False,
    }:
        errors.append("public staging isolation has drifted")
    if snapshot.get("reliability") != RELIABILITY:
        errors.append("public reliability controls have drifted")
    if snapshot.get("authority") != AUTHORITY:
        errors.append("public System snapshot has gained authority")
    services = snapshot.get("services")
    try:
        expected_services = _load_public_service_template()
    except ValueError as exc:
        expected_services = []
        errors.append(str(exc))
    if not isinstance(services, list) or len(services) != len(SERVICE_KEYS):
        errors.append("public System services are incomplete")
    else:
        for index, service in enumerate(services):
            if not isinstance(service, dict) or service.get("key") != SERVICE_KEYS[index]:
                errors.append("public System service order has drifted")
                break
            if set(service) != {"key", "label", "status", "responsibility"}:
                errors.append("public System service shape has drifted")
                break
            if service.get("status") != "RUNTIME_VERIFIED":
                errors.append("public System service is not runtime verified")
                break
            if expected_services and (
                service.get("label") != expected_services[index]["label"]
                or service.get("responsibility")
                != expected_services[index]["responsibility"]
            ):
                errors.append("public System service copy has drifted")
                break
    if _contains_protected_value(snapshot):
        errors.append("protected identifier value reached the public System snapshot")
    return errors


def canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--output",
        type=Path,
        help="write a candidate snapshot; the tracked Sites snapshot is forbidden",
    )
    output_group.add_argument(
        "--check-output",
        type=Path,
        help="compare a candidate snapshot without writing",
    )
    args = parser.parse_args()

    snapshot = build_public_runtime_snapshot(load_json(args.input))
    rendered = canonical_json(snapshot)
    if args.output:
        if args.output.resolve() == TRACKED_SNAPSHOT_PATH.resolve():
            parser.error("the exporter cannot overwrite the tracked Sites snapshot")
        args.output.write_text(rendered, encoding="utf-8")
        print("WROTE: aggregate public System candidate")
        return 0
    if args.check_output:
        if args.check_output.read_text(encoding="utf-8") != rendered:
            print("INVALID: candidate snapshot differs from the validated observation")
            return 1
        print("PASS: candidate snapshot matches the validated aggregate observation")
        return 0
    print("PASS: aggregate AWS observation is safe to project; no file was written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
