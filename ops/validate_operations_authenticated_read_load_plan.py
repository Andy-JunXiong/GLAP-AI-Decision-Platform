"""Validate and render the plan-only authenticated Operations API read load."""

from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "docs" / "operations_authenticated_read_load_plan_v1.json"
PLAN_SCHEMA_PATH = (
    ROOT / "docs" / "operations_authenticated_read_load_plan_v1.schema.json"
)
BASELINE_SCHEMA_PATH = (
    ROOT / "docs" / "operations_authenticated_read_load_baseline_v1.schema.json"
)

TOP_LEVEL_FIELDS = {
    "schema_version",
    "as_of_date",
    "status",
    "business_timezone",
    "scope",
    "evidence_boundary",
    "execution",
    "authorization",
    "authentication",
    "load_shape",
    "routes",
    "abort_gates",
    "sanitized_baseline",
    "claim_boundary",
}
AUTHORIZATION_FIELDS = {
    "named_human_run_authorization_required",
    "temporary_identity_creation_authorized",
    "staging_load_run_authorized",
    "alarm_or_throttle_change_authorized",
    "operational_mutation_authorized",
    "production_access_authorized",
    "recurring_schedule_authorized",
}
ROUTES = (
    ("risks_open", "GET", "/v1/risks?status=OPEN&limit=50", 20),
    ("actions_proposed", "GET", "/v1/actions?status=PROPOSED&limit=50", 20),
    ("actions_edited", "GET", "/v1/actions?status=EDITED&limit=50", 10),
    ("outcomes_pending", "GET", "/v1/outcomes?status=PENDING&limit=50", 15),
    ("learning_review", "GET", "/v1/learning", 10),
    ("pipeline_health", "GET", "/v1/pipeline-health", 15),
    ("label_readiness", "GET", "/v1/label-readiness", 10),
)
PROHIBITED_BASELINE_FIELDS = {
    "authorization_header",
    "access_token",
    "identity_claim",
    "email",
    "actor",
    "request_id",
    "query_id",
    "action_id",
    "outcome_id",
    "shipment_id",
    "raw_url",
    "infrastructure_identifier",
}
BASELINE_TOP_LEVEL_FIELDS = {
    "schema_version",
    "as_of_date",
    "business_timezone",
    "scope",
    "plan_schema_version",
    "evidence_class",
    "run_status",
    "load_shape",
    "summary",
    "routes",
    "authority",
    "claim_boundary",
}
BASELINE_SUMMARY_FIELDS = {
    "requests_attempted",
    "requests_completed",
    "responses_2xx",
    "responses_429",
    "responses_other_4xx",
    "responses_5xx",
    "latency_p50_ms",
    "latency_p95_ms",
    "latency_p99_ms",
    "abort_reason_code",
}
BASELINE_ROUTE_FIELDS = {
    "route_id",
    "requests_completed",
    "responses_2xx",
    "responses_429",
    "responses_other_4xx",
    "responses_5xx",
    "latency_p50_ms",
    "latency_p95_ms",
    "latency_p99_ms",
}
ABORT_REASON_CODES = {
    "NONE",
    "AUTHORIZATION_FAILURE",
    "NON_ALLOWLISTED_ROUTE",
    "UNEXPECTED_HTTP_METHOD",
    "THROTTLE_RATE_EXCEEDED",
    "SERVER_ERROR_RATE_EXCEEDED",
    "CONSECUTIVE_FAILURES_EXCEEDED",
    "P95_LATENCY_EXCEEDED",
    "IDENTITY_CLEANUP_FAILED",
    "RESULT_RECONCILIATION_FAILED",
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_plan(path: Path = PLAN_PATH) -> dict[str, Any]:
    return _load_json(path)


def sydney_business_date() -> date:
    return datetime.now(ZoneInfo("Australia/Sydney")).date()


def _property_names(value: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(value, dict):
        properties = value.get("properties")
        if isinstance(properties, dict):
            names.update(properties)
        for nested in value.values():
            names.update(_property_names(nested))
    elif isinstance(value, list):
        for nested in value:
            names.update(_property_names(nested))
    return names


def _all_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        keys.update(value)
        for nested in value.values():
            keys.update(_all_keys(nested))
    elif isinstance(value, list):
        for nested in value:
            keys.update(_all_keys(nested))
    return keys


def _non_negative_ints(record: dict[str, Any], fields: set[str]) -> bool:
    return all(type(record.get(field)) is int and record[field] >= 0 for field in fields)


def validate_plan(
    plan: dict[str, Any],
    *,
    today: date | None = None,
    root: Path = ROOT,
    plan_schema: dict[str, Any] | None = None,
    baseline_schema: dict[str, Any] | None = None,
) -> list[str]:
    if not isinstance(plan, dict):
        return ["plan must be an object"]
    errors: list[str] = []
    if set(plan) != TOP_LEVEL_FIELDS:
        errors.append("top-level field inventory is incomplete or unexpected")
    if plan.get("schema_version") != "operations-authenticated-read-load-plan.v1":
        errors.append("unsupported schema_version")
    if plan.get("status") != "PLAN_ONLY_NOT_AUTHORIZED":
        errors.append("plan status must remain not authorized")
    if plan.get("business_timezone") != "Australia/Sydney":
        errors.append("business timezone must remain Australia/Sydney")
    if plan.get("scope") != "PRIVATE_OPERATIONS_STAGING":
        errors.append("scope must remain private Operations staging")
    if plan.get("evidence_boundary") != "SYNTHETIC_ENGINEERING_ONLY":
        errors.append("evidence boundary must remain synthetic engineering only")
    try:
        as_of_date = date.fromisoformat(plan.get("as_of_date", ""))
    except (TypeError, ValueError):
        errors.append("as_of_date must be an ISO calendar date")
    else:
        if as_of_date > (today or sydney_business_date()):
            errors.append("as_of_date cannot exceed the current Sydney date")

    execution = plan.get("execution", {})
    expected_execution = {
        "mode": "OFFLINE_CONTRACT_VALIDATION",
        "network_access": False,
        "load_executed": False,
        "external_writes_executed": False,
    }
    if execution != expected_execution:
        errors.append("execution must remain offline with zero load or external writes")

    authorization = plan.get("authorization", {})
    if not isinstance(authorization, dict) or set(authorization) != AUTHORIZATION_FIELDS:
        errors.append("authorization field inventory is incomplete or unexpected")
        authorization = {}
    if authorization.get("named_human_run_authorization_required") is not True:
        errors.append("a named-human run authorization must be required")
    for field in AUTHORIZATION_FIELDS - {"named_human_run_authorization_required"}:
        if authorization.get(field) is not False:
            errors.append(f"authorization.{field} must remain false")

    authentication = plan.get("authentication", {})
    expected_authentication = {
        "mechanism": "COGNITO_ADMIN_USER_PASSWORD_AUTH",
        "role": "viewer",
        "temporary_identity_required": True,
        "email_delivery_suppressed": True,
        "token_storage": "PROCESS_MEMORY_ONLY",
        "token_or_claim_logging_allowed": False,
        "temporary_identity_removal_required": True,
    }
    if authentication != expected_authentication:
        errors.append("authentication must remain viewer-only, ephemeral, and non-logging")

    load_shape = plan.get("load_shape", {})
    expected_load_fields = {
        "duration_seconds",
        "ramp_up_seconds",
        "target_requests_per_second",
        "max_concurrency",
        "max_total_requests",
        "request_timeout_ms",
        "retries_per_request",
    }
    if not isinstance(load_shape, dict) or set(load_shape) != expected_load_fields:
        errors.append("load shape field inventory is incomplete or unexpected")
        load_shape = {}
    numeric_fields = expected_load_fields - {"retries_per_request"}
    if any(
        type(load_shape.get(field)) is not int or load_shape.get(field, 0) <= 0
        for field in numeric_fields
    ):
        errors.append("load shape values must be positive integers")
    if load_shape.get("duration_seconds") != 900:
        errors.append("duration must remain the bounded 900-second plan")
    if load_shape.get("ramp_up_seconds") != 60:
        errors.append("ramp-up must remain 60 seconds")
    if load_shape.get("target_requests_per_second") != 2:
        errors.append("target rate must remain two requests per second")
    if load_shape.get("max_concurrency") != 4:
        errors.append("maximum concurrency must remain four")
    if load_shape.get("max_total_requests") != 1800:
        errors.append("maximum request count must remain 1800")
    if load_shape.get("request_timeout_ms") != 10000:
        errors.append("request timeout must remain 10000 milliseconds")
    if load_shape.get("retries_per_request") != 0:
        errors.append("automatic request retries must remain disabled")

    routes = plan.get("routes", [])
    route_projection = []
    if not isinstance(routes, list):
        errors.append("routes must be a list")
    else:
        for route in routes:
            if not isinstance(route, dict) or set(route) != {
                "id", "method", "path", "weight_pct"
            }:
                errors.append("route field inventory is incomplete or unexpected")
                continue
            route_projection.append(
                (route.get("id"), route.get("method"), route.get("path"), route.get("weight_pct"))
            )
            path = route.get("path", "")
            if route.get("method") != "GET":
                errors.append(f"{route.get('id')} must remain GET-only")
            if not isinstance(path, str) or not path.startswith("/v1/"):
                errors.append(f"{route.get('id')} has an invalid API path")
            if any(marker in path for marker in ("{", "}", "/events", "/shipments")):
                errors.append(f"{route.get('id')} is not an aggregate allowlisted read")
    if tuple(route_projection) != ROUTES:
        errors.append("route inventory, order, path, or weight drifted")
    if sum(item[3] for item in ROUTES) != 100:
        errors.append("route weights must total 100 percent")

    abort_gates = plan.get("abort_gates", {})
    expected_abort_gates = {
        "abort_on_non_allowlisted_route": True,
        "abort_on_unexpected_http_method": True,
        "abort_on_any_401_or_403": True,
        "max_429_rate_pct": 5.0,
        "max_5xx_rate_pct": 1.0,
        "max_consecutive_failures": 5,
        "max_p95_latency_ms": 3000,
        "mutation_routes_allowed": False,
        "automatic_retries_allowed": False,
    }
    if abort_gates != expected_abort_gates:
        errors.append("abort gates or no-mutation boundary drifted")

    baseline = plan.get("sanitized_baseline", {})
    expected_baseline_fields = {
        "schema_version",
        "schema_path",
        "aggregate_only",
        "raw_request_records_allowed",
        "artifact_storage_authorized",
        "prohibited_fields",
    }
    if not isinstance(baseline, dict) or set(baseline) != expected_baseline_fields:
        errors.append("sanitized baseline field inventory is incomplete or unexpected")
        baseline = {}
    if baseline.get("schema_version") != "operations-authenticated-read-load-baseline.v1":
        errors.append("sanitized baseline schema version drifted")
    if baseline.get("schema_path") != "docs/operations_authenticated_read_load_baseline_v1.schema.json":
        errors.append("sanitized baseline schema path drifted")
    for field, expected in (
        ("aggregate_only", True),
        ("raw_request_records_allowed", False),
        ("artifact_storage_authorized", False),
    ):
        if baseline.get(field) is not expected:
            errors.append(f"sanitized_baseline.{field} drifted")
    if set(baseline.get("prohibited_fields", [])) != PROHIBITED_BASELINE_FIELDS:
        errors.append("protected baseline field inventory drifted")

    plan_schema = plan_schema or _load_json(
        root / "docs" / "operations_authenticated_read_load_plan_v1.schema.json"
    )
    if plan_schema.get("additionalProperties") is not False:
        errors.append("plan schema must reject additional properties")
    if set(plan_schema.get("required", [])) != TOP_LEVEL_FIELDS:
        errors.append("plan schema required field inventory drifted")
    if (
        plan_schema.get("properties", {}).get("schema_version", {}).get("const")
        != "operations-authenticated-read-load-plan.v1"
    ):
        errors.append("plan schema version constant drifted")

    baseline_schema = baseline_schema or _load_json(
        root / "docs" / "operations_authenticated_read_load_baseline_v1.schema.json"
    )
    if baseline_schema.get("additionalProperties") is not False:
        errors.append("baseline schema must reject additional properties")
    if set(baseline_schema.get("required", [])) != BASELINE_TOP_LEVEL_FIELDS:
        errors.append("baseline schema required field inventory drifted")
    if set(baseline_schema.get("properties", {})) != BASELINE_TOP_LEVEL_FIELDS:
        errors.append("baseline schema property inventory drifted")
    leaked_fields = PROHIBITED_BASELINE_FIELDS & _property_names(baseline_schema)
    if leaked_fields:
        errors.append("baseline schema exposes protected raw fields")

    claim = plan.get("claim_boundary", {})
    expected_claim_fields = {
        "production_readiness",
        "production_sla",
        "real_logistics_performance",
        "operational_mutation_authority",
        "deployment_authority",
    }
    if not isinstance(claim, dict) or set(claim) != expected_claim_fields:
        errors.append("claim boundary field inventory is incomplete or unexpected")
        claim = {}
    for field in expected_claim_fields:
        if claim.get(field) is not False:
            errors.append(f"claim_boundary.{field} must remain false")
    return errors


def validate_baseline(
    baseline: dict[str, Any],
    plan: dict[str, Any],
    *,
    today: date | None = None,
) -> list[str]:
    """Validate one future aggregate result without accepting raw request evidence."""
    if not isinstance(baseline, dict):
        return ["baseline must be an object"]
    errors: list[str] = []
    if set(baseline) != BASELINE_TOP_LEVEL_FIELDS:
        errors.append("baseline top-level field inventory is incomplete or unexpected")
    if PROHIBITED_BASELINE_FIELDS & _all_keys(baseline):
        errors.append("baseline contains a protected raw field")
    if baseline.get("schema_version") != "operations-authenticated-read-load-baseline.v1":
        errors.append("unsupported baseline schema_version")
    if baseline.get("plan_schema_version") != plan.get("schema_version"):
        errors.append("baseline plan schema version drifted")
    if baseline.get("business_timezone") != "Australia/Sydney":
        errors.append("baseline timezone must remain Australia/Sydney")
    if baseline.get("scope") != "PRIVATE_OPERATIONS_STAGING":
        errors.append("baseline scope must remain private Operations staging")
    if baseline.get("evidence_class") != "STAGING_ENGINEERING":
        errors.append("baseline evidence class must remain staging engineering")
    try:
        as_of_date = date.fromisoformat(baseline.get("as_of_date", ""))
    except (TypeError, ValueError):
        errors.append("baseline as_of_date must be an ISO calendar date")
    else:
        if as_of_date > (today or sydney_business_date()):
            errors.append("baseline as_of_date cannot exceed the current Sydney date")

    run_status = baseline.get("run_status")
    if run_status not in {"COMPLETED", "ABORTED", "FAILED_CLOSED"}:
        errors.append("baseline run status is unsupported")
    expected_shape = {
        "duration_seconds": plan.get("load_shape", {}).get("duration_seconds"),
        "target_requests_per_second": plan.get("load_shape", {}).get(
            "target_requests_per_second"
        ),
        "max_concurrency": plan.get("load_shape", {}).get("max_concurrency"),
    }
    if baseline.get("load_shape") != expected_shape:
        errors.append("baseline load shape does not match the approved plan shape")

    summary = baseline.get("summary", {})
    if not isinstance(summary, dict) or set(summary) != BASELINE_SUMMARY_FIELDS:
        errors.append("baseline summary field inventory is incomplete or unexpected")
        summary = {}
    count_fields = {
        "requests_attempted",
        "requests_completed",
        "responses_2xx",
        "responses_429",
        "responses_other_4xx",
        "responses_5xx",
        "latency_p50_ms",
        "latency_p95_ms",
        "latency_p99_ms",
    }
    if not _non_negative_ints(summary, count_fields):
        errors.append("baseline summary values must be non-negative integers")
    completed = summary.get("requests_completed", -1)
    attempted = summary.get("requests_attempted", -1)
    status_total = sum(
        summary.get(field, -1)
        for field in (
            "responses_2xx",
            "responses_429",
            "responses_other_4xx",
            "responses_5xx",
        )
    )
    if not (0 <= completed <= attempted <= plan.get("load_shape", {}).get("max_total_requests", -1)):
        errors.append("baseline request totals exceed or contradict the bounded plan")
    if status_total != completed:
        errors.append("baseline status totals do not reconcile to completed requests")
    if not (
        summary.get("latency_p50_ms", -1)
        <= summary.get("latency_p95_ms", -1)
        <= summary.get("latency_p99_ms", -1)
    ):
        errors.append("baseline latency percentiles are not monotonic")
    abort_reason = summary.get("abort_reason_code")
    if abort_reason not in ABORT_REASON_CODES:
        errors.append("baseline abort reason is unsupported")
    if run_status == "COMPLETED" and abort_reason != "NONE":
        errors.append("completed baseline cannot carry an abort reason")
    if run_status in {"ABORTED", "FAILED_CLOSED"} and abort_reason == "NONE":
        errors.append("non-completed baseline requires a bounded abort reason")
    if (
        run_status == "COMPLETED"
        and summary.get("latency_p95_ms", 0)
        > plan.get("abort_gates", {}).get("max_p95_latency_ms", -1)
    ):
        errors.append("completed baseline exceeds the p95 abort gate")

    routes = baseline.get("routes", [])
    if not isinstance(routes, list):
        errors.append("baseline routes must be a list")
        routes = []
    expected_route_ids = [route[0] for route in ROUTES]
    actual_route_ids: list[Any] = []
    route_totals = {
        "requests_completed": 0,
        "responses_2xx": 0,
        "responses_429": 0,
        "responses_other_4xx": 0,
        "responses_5xx": 0,
    }
    for route in routes:
        if not isinstance(route, dict) or set(route) != BASELINE_ROUTE_FIELDS:
            errors.append("baseline route field inventory is incomplete or unexpected")
            continue
        actual_route_ids.append(route.get("route_id"))
        numeric_fields = BASELINE_ROUTE_FIELDS - {"route_id"}
        if not _non_negative_ints(route, numeric_fields):
            errors.append(f"{route.get('route_id')} baseline metrics must be non-negative integers")
            continue
        route_status_total = sum(
            route[field]
            for field in (
                "responses_2xx",
                "responses_429",
                "responses_other_4xx",
                "responses_5xx",
            )
        )
        if route_status_total != route["requests_completed"]:
            errors.append(f"{route.get('route_id')} status totals do not reconcile")
        if not (
            route["latency_p50_ms"]
            <= route["latency_p95_ms"]
            <= route["latency_p99_ms"]
        ):
            errors.append(f"{route.get('route_id')} latency percentiles are not monotonic")
        for field in route_totals:
            route_totals[field] += route[field]
    if actual_route_ids != expected_route_ids:
        errors.append("baseline route inventory or order drifted")
    for field, route_total in route_totals.items():
        if route_total != summary.get(field):
            errors.append(f"baseline route {field} does not reconcile to summary")

    expected_authority = {
        "operational_mutation_executed": False,
        "production_accessed": False,
        "recurring_schedule_created": False,
    }
    if baseline.get("authority") != expected_authority:
        errors.append("baseline authority must remain all false")
    expected_claim = {
        "production_readiness": False,
        "production_sla": False,
        "real_logistics_performance": False,
    }
    if baseline.get("claim_boundary") != expected_claim:
        errors.append("baseline claim boundary must remain all false")
    return errors


def render_plan(plan: dict[str, Any]) -> str:
    shape = plan["load_shape"]
    return "\n".join(
        [
            "# Authenticated Operations API read-load plan",
            "",
            f"- Status: `{plan['status']}`",
            f"- Sydney as-of date: `{plan['as_of_date']}`",
            f"- Scope: `{plan['scope']}`",
            f"- Allowlisted GET routes: {len(plan['routes'])}",
            f"- Proposed duration: {shape['duration_seconds']} seconds",
            f"- Proposed rate: {shape['target_requests_per_second']} requests/second",
            f"- Maximum planned requests: {shape['max_total_requests']}",
            "- Requests executed by this validation: 0",
            "- Production readiness: `false`",
            "",
            "The plan requires separate named-human authorization before any temporary identity or staging traffic. ",
            "Its future baseline format is aggregate-only and grants no production or mutation authority.",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=PLAN_PATH)
    parser.add_argument(
        "--baseline",
        type=Path,
        help="validate one aggregate-only staging result against the plan",
    )
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args()
    plan = load_plan(args.plan)
    errors = validate_plan(plan)
    if not errors and args.baseline:
        errors.extend(validate_baseline(_load_json(args.baseline), plan))
    if errors:
        for error in errors:
            print(f"DRIFT: {error}")
        return 1
    if args.baseline:
        print("Authenticated read-load aggregate baseline: PASS")
        return 0
    if args.format == "json":
        print(
            json.dumps(
                {
                    "schema_version": plan["schema_version"],
                    "status": plan["status"],
                    "route_count": len(plan["routes"]),
                    "max_total_requests": plan["load_shape"]["max_total_requests"],
                    "requests_executed": 0,
                    "production_readiness": False,
                },
                indent=2,
            )
        )
    else:
        print(render_plan(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
