"""Simulate the authenticated Operations API read-load contract without I/O."""

from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = Path(__file__).with_name(
    "validate_operations_authenticated_read_load_plan.py"
)


def _load_validator():
    module_name = "_glap_authenticated_read_load_contract"
    existing = sys.modules.get(module_name)
    if existing is not None and Path(existing.__file__).resolve() == VALIDATOR_PATH.resolve():
        return existing
    spec = importlib.util.spec_from_file_location(module_name, VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("authenticated read-load validator could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


CONTRACT = _load_validator()
SCENARIOS = (
    "healthy",
    "authorization_failure",
    "throttle_breach",
    "server_error_breach",
    "latency_breach",
    "consecutive_failures",
    "non_allowlisted_route",
    "unexpected_http_method",
    "identity_cleanup_failure",
    "reconciliation_failure",
)
SCENARIO_ABORT_REASON = {
    "healthy": "NONE",
    "authorization_failure": "AUTHORIZATION_FAILURE",
    "throttle_breach": "THROTTLE_RATE_EXCEEDED",
    "server_error_breach": "SERVER_ERROR_RATE_EXCEEDED",
    "latency_breach": "P95_LATENCY_EXCEEDED",
    "consecutive_failures": "CONSECUTIVE_FAILURES_EXCEEDED",
    "non_allowlisted_route": "NON_ALLOWLISTED_ROUTE",
    "unexpected_http_method": "UNEXPECTED_HTTP_METHOD",
    "identity_cleanup_failure": "IDENTITY_CLEANUP_FAILED",
    "reconciliation_failure": "RESULT_RECONCILIATION_FAILED",
}
REPORT_FIELDS = {
    "schema_version",
    "as_of_date",
    "evidence_class",
    "scenario",
    "schedule",
    "result",
    "execution",
    "authority",
    "claim_boundary",
}
SCHEDULE_FIELDS = {
    "duration_seconds",
    "ramp_up_seconds",
    "target_requests_per_second",
    "max_concurrency",
    "scheduled_requests",
    "first_offset_ms",
    "last_offset_ms",
    "route_request_counts",
}
RESULT_FIELDS = {
    "run_status",
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
    "candidate_baseline_valid",
}


def _weighted_route_cycle(plan: dict[str, Any]) -> list[str]:
    route_ids = [route["id"] for route in plan["routes"]]
    weights = {route["id"]: route["weight_pct"] for route in plan["routes"]}
    deficits = {route_id: 0 for route_id in route_ids}
    cycle: list[str] = []
    for _ in range(100):
        for route_id in route_ids:
            deficits[route_id] += weights[route_id]
        selected = max(route_ids, key=lambda route_id: deficits[route_id])
        cycle.append(selected)
        deficits[selected] -= 100
    if Counter(cycle) != Counter(weights):
        raise ValueError("weighted route cycle did not reconcile to 100 percent")
    return cycle


def build_request_schedule(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a deterministic in-memory schedule; it never waits or sends a request."""
    plan_errors = CONTRACT.validate_plan(plan)
    if plan_errors:
        raise ValueError("read-load plan failed validation")
    shape = plan["load_shape"]
    cycle = _weighted_route_cycle(plan)
    offsets: list[int] = []

    # The fixed two-rps plan uses a conservative one-rps first minute, then the
    # target two-rps cadence. The 1,800 request value remains a hard ceiling.
    for second in range(shape["ramp_up_seconds"]):
        offsets.append(second * 1000)
    steady_interval_ms = 1000 // shape["target_requests_per_second"]
    offset_ms = shape["ramp_up_seconds"] * 1000
    duration_ms = shape["duration_seconds"] * 1000
    while offset_ms < duration_ms and len(offsets) < shape["max_total_requests"]:
        offsets.append(offset_ms)
        offset_ms += steady_interval_ms

    return [
        {
            "offset_ms": offset,
            "route_id": cycle[index % len(cycle)],
            "method": "GET",
        }
        for index, offset in enumerate(offsets)
    ]


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _simulated_response(scenario: str, index: int) -> tuple[int, int]:
    latency_ms = 90 + (index % 11) * 10
    if scenario == "authorization_failure" and index == 0:
        return 401, latency_ms
    if scenario == "throttle_breach" and index in {0, 19}:
        return 429, latency_ms
    if scenario == "server_error_breach" and index == 19:
        return 503, latency_ms
    if scenario == "latency_breach" and index < 20:
        return 200, 3501
    if scenario == "consecutive_failures" and index < 5:
        return 503, latency_ms
    return 200, latency_ms


def _abort_reason(
    observations: list[dict[str, Any]],
    plan: dict[str, Any],
) -> str:
    latest_status = observations[-1]["status_code"]
    if latest_status in {401, 403}:
        return "AUTHORIZATION_FAILURE"
    consecutive_failures = 0
    for observation in reversed(observations):
        if observation["status_code"] == 429 or observation["status_code"] >= 500:
            consecutive_failures += 1
        else:
            break
    if consecutive_failures >= plan["abort_gates"]["max_consecutive_failures"]:
        return "CONSECUTIVE_FAILURES_EXCEEDED"
    if len(observations) < 20:
        return "NONE"
    throttle_count = sum(item["status_code"] == 429 for item in observations)
    server_error_count = sum(item["status_code"] >= 500 for item in observations)
    if throttle_count * 100 / len(observations) > plan["abort_gates"]["max_429_rate_pct"]:
        return "THROTTLE_RATE_EXCEEDED"
    if server_error_count * 100 / len(observations) > plan["abort_gates"]["max_5xx_rate_pct"]:
        return "SERVER_ERROR_RATE_EXCEEDED"
    p95 = _percentile([item["latency_ms"] for item in observations], 0.95)
    if p95 > plan["abort_gates"]["max_p95_latency_ms"]:
        return "P95_LATENCY_EXCEEDED"
    return "NONE"


def _aggregate_observations(
    observations: list[dict[str, Any]],
    route_ids: list[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    def aggregate(items: list[dict[str, Any]]) -> dict[str, int]:
        latencies = [item["latency_ms"] for item in items]
        return {
            "requests_completed": len(items),
            "responses_2xx": sum(200 <= item["status_code"] < 300 for item in items),
            "responses_429": sum(item["status_code"] == 429 for item in items),
            "responses_other_4xx": sum(
                400 <= item["status_code"] < 500 and item["status_code"] != 429
                for item in items
            ),
            "responses_5xx": sum(item["status_code"] >= 500 for item in items),
            "latency_p50_ms": _percentile(latencies, 0.50),
            "latency_p95_ms": _percentile(latencies, 0.95),
            "latency_p99_ms": _percentile(latencies, 0.99),
        }

    summary = aggregate(observations)
    routes: list[dict[str, Any]] = []
    for route_id in route_ids:
        metrics = aggregate(
            [item for item in observations if item["route_id"] == route_id]
        )
        routes.append({"route_id": route_id, **metrics})
    return summary, routes


def _baseline_candidate(
    plan: dict[str, Any],
    scenario: str,
    schedule: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    observations: list[dict[str, Any]] = []
    attempted = 0
    reason = "NONE"

    if scenario == "non_allowlisted_route":
        attempted = 1
        reason = "NON_ALLOWLISTED_ROUTE"
    elif scenario == "unexpected_http_method":
        attempted = 1
        reason = "UNEXPECTED_HTTP_METHOD"
    else:
        for index, scheduled in enumerate(schedule):
            attempted += 1
            status_code, latency_ms = _simulated_response(scenario, index)
            observations.append(
                {
                    "route_id": scheduled["route_id"],
                    "status_code": status_code,
                    "latency_ms": latency_ms,
                }
            )
            reason = _abort_reason(observations, plan)
            if reason != "NONE":
                break
        if scenario == "identity_cleanup_failure" and reason == "NONE":
            reason = "IDENTITY_CLEANUP_FAILED"
        if scenario == "reconciliation_failure" and reason == "NONE":
            reason = "RESULT_RECONCILIATION_FAILED"

    if reason == "NONE":
        run_status = "COMPLETED"
    elif reason in {"IDENTITY_CLEANUP_FAILED", "RESULT_RECONCILIATION_FAILED"}:
        run_status = "FAILED_CLOSED"
    else:
        run_status = "ABORTED"

    route_ids = [route["id"] for route in plan["routes"]]
    summary, routes = _aggregate_observations(observations, route_ids)
    summary = {
        "requests_attempted": attempted,
        **summary,
        "abort_reason_code": reason,
    }
    baseline = {
        "schema_version": "operations-authenticated-read-load-baseline.v1",
        "as_of_date": plan["as_of_date"],
        "business_timezone": "Australia/Sydney",
        "scope": "PRIVATE_OPERATIONS_STAGING",
        "plan_schema_version": plan["schema_version"],
        "evidence_class": "STAGING_ENGINEERING",
        "run_status": run_status,
        "load_shape": {
            "duration_seconds": plan["load_shape"]["duration_seconds"],
            "target_requests_per_second": plan["load_shape"]["target_requests_per_second"],
            "max_concurrency": plan["load_shape"]["max_concurrency"],
        },
        "summary": summary,
        "routes": routes,
        "authority": {
            "operational_mutation_executed": False,
            "production_accessed": False,
            "recurring_schedule_created": False,
        },
        "claim_boundary": {
            "production_readiness": False,
            "production_sla": False,
            "real_logistics_performance": False,
        },
    }
    if scenario == "reconciliation_failure":
        baseline["summary"]["responses_2xx"] += 1
    return baseline, observations


def simulate_scenario(plan: dict[str, Any], scenario: str) -> dict[str, Any]:
    if scenario not in SCENARIOS:
        raise ValueError("unsupported simulation scenario")
    plan_errors = CONTRACT.validate_plan(plan)
    if plan_errors:
        raise ValueError("read-load plan failed validation")
    schedule = build_request_schedule(plan)
    baseline, observations = _baseline_candidate(plan, scenario, schedule)
    baseline_errors = CONTRACT.validate_baseline(baseline, plan)
    candidate_valid = baseline_errors == []
    if scenario == "reconciliation_failure":
        if candidate_valid:
            raise AssertionError("reconciliation failure scenario unexpectedly passed")
    elif not candidate_valid:
        raise AssertionError("simulated baseline candidate failed reconciliation")

    aggregate, _ = _aggregate_observations(
        observations, [route["id"] for route in plan["routes"]]
    )
    route_counts = Counter(item["route_id"] for item in schedule)
    reason = SCENARIO_ABORT_REASON[scenario]
    if scenario == "healthy":
        run_status = "COMPLETED"
    elif scenario in {"identity_cleanup_failure", "reconciliation_failure"}:
        run_status = "FAILED_CLOSED"
    else:
        run_status = "ABORTED"
    report = {
        "schema_version": "operations-authenticated-read-load-simulation.v1",
        "as_of_date": plan["as_of_date"],
        "evidence_class": "REPOSITORY_ENGINEERING_SIMULATION",
        "scenario": scenario,
        "schedule": {
            "duration_seconds": plan["load_shape"]["duration_seconds"],
            "ramp_up_seconds": plan["load_shape"]["ramp_up_seconds"],
            "target_requests_per_second": plan["load_shape"]["target_requests_per_second"],
            "max_concurrency": plan["load_shape"]["max_concurrency"],
            "scheduled_requests": len(schedule),
            "first_offset_ms": schedule[0]["offset_ms"],
            "last_offset_ms": schedule[-1]["offset_ms"],
            "route_request_counts": {
                route["id"]: route_counts[route["id"]] for route in plan["routes"]
            },
        },
        "result": {
            "run_status": run_status,
            "requests_attempted": baseline["summary"]["requests_attempted"],
            **aggregate,
            "abort_reason_code": reason,
            "candidate_baseline_valid": candidate_valid,
        },
        "execution": {
            "network_access": False,
            "identity_created": False,
            "staging_requests_executed": False,
            "external_writes_executed": False,
        },
        "authority": {
            "staging_load_run_authorized": False,
            "operational_mutation_authorized": False,
            "production_access_authorized": False,
            "recurring_schedule_authorized": False,
        },
        "claim_boundary": {
            "staging_runtime_evidence": False,
            "production_readiness": False,
            "production_sla": False,
            "real_logistics_performance": False,
        },
    }
    report_errors = validate_simulation_report(report, plan)
    if report_errors:
        raise AssertionError("simulation report failed validation")
    return report


def validate_simulation_report(
    report: dict[str, Any], plan: dict[str, Any]
) -> list[str]:
    if not isinstance(report, dict):
        return ["simulation report must be an object"]
    errors: list[str] = []
    if set(report) != REPORT_FIELDS:
        errors.append("simulation report field inventory drifted")
    if CONTRACT.PROHIBITED_BASELINE_FIELDS & CONTRACT._all_keys(report):
        errors.append("simulation report contains a protected raw field")
    if report.get("schema_version") != "operations-authenticated-read-load-simulation.v1":
        errors.append("simulation report schema version drifted")
    if report.get("evidence_class") != "REPOSITORY_ENGINEERING_SIMULATION":
        errors.append("simulation report evidence class drifted")
    scenario = report.get("scenario")
    if scenario not in SCENARIOS:
        errors.append("simulation scenario is unsupported")

    schedule = report.get("schedule", {})
    if not isinstance(schedule, dict) or set(schedule) != SCHEDULE_FIELDS:
        errors.append("simulation schedule field inventory drifted")
        schedule = {}
    route_counts = schedule.get("route_request_counts", {})
    route_ids = [route["id"] for route in plan["routes"]]
    if not isinstance(route_counts, dict) or list(route_counts) != route_ids:
        errors.append("simulation schedule route inventory drifted")
        route_counts = {}
    scheduled = schedule.get("scheduled_requests")
    if type(scheduled) is not int or not 0 < scheduled <= plan["load_shape"]["max_total_requests"]:
        errors.append("simulation schedule exceeds the request ceiling")
    if sum(value for value in route_counts.values() if type(value) is int) != scheduled:
        errors.append("simulation route counts do not reconcile")
    expected_schedule_shape = {
        "duration_seconds": plan["load_shape"]["duration_seconds"],
        "ramp_up_seconds": plan["load_shape"]["ramp_up_seconds"],
        "target_requests_per_second": plan["load_shape"]["target_requests_per_second"],
        "max_concurrency": plan["load_shape"]["max_concurrency"],
    }
    if any(schedule.get(field) != value for field, value in expected_schedule_shape.items()):
        errors.append("simulation schedule shape drifted from the plan")

    result = report.get("result", {})
    if not isinstance(result, dict) or set(result) != RESULT_FIELDS:
        errors.append("simulation result field inventory drifted")
        result = {}
    numeric_fields = RESULT_FIELDS - {
        "run_status", "abort_reason_code", "candidate_baseline_valid"
    }
    if any(type(result.get(field)) is not int or result[field] < 0 for field in numeric_fields):
        errors.append("simulation result metrics must be non-negative integers")
    if result.get("requests_attempted", 0) > scheduled:
        errors.append("simulation attempts exceed the schedule")
    status_total = sum(
        result.get(field, -1)
        for field in (
            "responses_2xx",
            "responses_429",
            "responses_other_4xx",
            "responses_5xx",
        )
    )
    if status_total != result.get("requests_completed"):
        errors.append("simulation response totals do not reconcile")
    if not (
        result.get("latency_p50_ms", -1)
        <= result.get("latency_p95_ms", -1)
        <= result.get("latency_p99_ms", -1)
    ):
        errors.append("simulation latency percentiles are not monotonic")
    expected_reason = SCENARIO_ABORT_REASON.get(scenario)
    if result.get("abort_reason_code") != expected_reason:
        errors.append("simulation abort reason does not match the scenario")
    if scenario == "healthy":
        if result.get("run_status") != "COMPLETED":
            errors.append("healthy simulation must complete")
        if result.get("requests_completed") != scheduled:
            errors.append("healthy simulation must complete the full schedule")
        if result.get("candidate_baseline_valid") is not True:
            errors.append("healthy simulation candidate must reconcile")
    elif scenario == "reconciliation_failure":
        if result.get("run_status") != "FAILED_CLOSED":
            errors.append("reconciliation failure must fail closed")
        if result.get("candidate_baseline_valid") is not False:
            errors.append("reconciliation failure candidate must be invalid")
    elif result.get("candidate_baseline_valid") is not True:
        errors.append("non-reconciliation scenario candidate must reconcile")

    expected_execution = {
        "network_access": False,
        "identity_created": False,
        "staging_requests_executed": False,
        "external_writes_executed": False,
    }
    if report.get("execution") != expected_execution:
        errors.append("simulation execution boundary expanded")
    expected_authority = {
        "staging_load_run_authorized": False,
        "operational_mutation_authorized": False,
        "production_access_authorized": False,
        "recurring_schedule_authorized": False,
    }
    if report.get("authority") != expected_authority:
        errors.append("simulation authority boundary expanded")
    expected_claim = {
        "staging_runtime_evidence": False,
        "production_readiness": False,
        "production_sla": False,
        "real_logistics_performance": False,
    }
    if report.get("claim_boundary") != expected_claim:
        errors.append("simulation claim boundary expanded")
    return errors


def render_markdown(report: dict[str, Any]) -> str:
    result = report["result"]
    schedule = report["schedule"]
    return "\n".join(
        [
            "# Authenticated read-load offline simulation",
            "",
            f"- Scenario: `{report['scenario']}`",
            f"- Evidence class: `{report['evidence_class']}`",
            f"- Scheduled requests: {schedule['scheduled_requests']}",
            f"- Simulated completed requests: {result['requests_completed']}",
            f"- Result: `{result['run_status']}`",
            f"- Abort reason: `{result['abort_reason_code']}`",
            f"- Candidate baseline valid: `{str(result['candidate_baseline_valid']).lower()}`",
            "- Network access: `false`",
            "- Staging requests executed: `false`",
            "- Production readiness: `false`",
            "",
            "This is repository engineering simulation only. It is not staging runtime evidence.",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=CONTRACT.PLAN_PATH)
    parser.add_argument("--scenario", choices=SCENARIOS, default="healthy")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args()
    plan = CONTRACT.load_plan(args.plan)
    report = simulate_scenario(plan, args.scenario)
    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        print(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
