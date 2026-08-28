import copy
from datetime import date
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_operations_authenticated_read_load_plan",
    ROOT / "ops" / "validate_operations_authenticated_read_load_plan.py",
)
VALIDATOR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)


class OperationsAuthenticatedReadLoadPlanTests(unittest.TestCase):
    def setUp(self):
        self.plan = VALIDATOR.load_plan()

    def _baseline(self):
        routes = []
        for route_id, _, _, _ in VALIDATOR.ROUTES:
            routes.append(
                {
                    "route_id": route_id,
                    "requests_completed": 10,
                    "responses_2xx": 10,
                    "responses_429": 0,
                    "responses_other_4xx": 0,
                    "responses_5xx": 0,
                    "latency_p50_ms": 100,
                    "latency_p95_ms": 200,
                    "latency_p99_ms": 300,
                }
            )
        return {
            "schema_version": "operations-authenticated-read-load-baseline.v1",
            "as_of_date": "2026-08-28",
            "business_timezone": "Australia/Sydney",
            "scope": "PRIVATE_OPERATIONS_STAGING",
            "plan_schema_version": "operations-authenticated-read-load-plan.v1",
            "evidence_class": "STAGING_ENGINEERING",
            "run_status": "COMPLETED",
            "load_shape": {
                "duration_seconds": 900,
                "target_requests_per_second": 2,
                "max_concurrency": 4,
            },
            "summary": {
                "requests_attempted": 70,
                "requests_completed": 70,
                "responses_2xx": 70,
                "responses_429": 0,
                "responses_other_4xx": 0,
                "responses_5xx": 0,
                "latency_p50_ms": 100,
                "latency_p95_ms": 200,
                "latency_p99_ms": 300,
                "abort_reason_code": "NONE",
            },
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

    def test_repository_plan_is_valid_bounded_and_not_authorized(self):
        self.assertEqual(
            VALIDATOR.validate_plan(self.plan, today=date(2026, 8, 28)),
            [],
        )
        self.assertEqual(self.plan["status"], "PLAN_ONLY_NOT_AUTHORIZED")
        self.assertFalse(self.plan["execution"]["network_access"])
        self.assertFalse(self.plan["execution"]["load_executed"])
        self.assertEqual(len(self.plan["routes"]), 7)

    def test_future_date_fails_closed(self):
        plan = copy.deepcopy(self.plan)
        plan["as_of_date"] = "2026-08-29"
        errors = VALIDATOR.validate_plan(plan, today=date(2026, 8, 28))
        self.assertTrue(any("Sydney date" in error for error in errors))

    def test_external_execution_or_run_authority_fails_closed(self):
        plan = copy.deepcopy(self.plan)
        plan["execution"]["network_access"] = True
        plan["execution"]["load_executed"] = True
        plan["authorization"]["staging_load_run_authorized"] = True
        errors = VALIDATOR.validate_plan(plan, today=date(2026, 8, 28))
        self.assertTrue(any("zero load" in error for error in errors))
        self.assertTrue(any("staging_load_run_authorized" in error for error in errors))

    def test_route_inventory_is_exact_get_only_and_aggregate(self):
        plan = copy.deepcopy(self.plan)
        plan["routes"][0]["method"] = "POST"
        plan["routes"][0]["path"] = "/v1/actions/{action_id}/events"
        errors = VALIDATOR.validate_plan(plan, today=date(2026, 8, 28))
        self.assertTrue(any("GET-only" in error for error in errors))
        self.assertTrue(any("aggregate allowlisted read" in error for error in errors))
        self.assertTrue(any("route inventory" in error for error in errors))

    def test_load_shape_and_retries_cannot_expand(self):
        plan = copy.deepcopy(self.plan)
        plan["load_shape"]["target_requests_per_second"] = 20
        plan["load_shape"]["max_total_requests"] = 18000
        plan["load_shape"]["retries_per_request"] = 1
        errors = VALIDATOR.validate_plan(plan, today=date(2026, 8, 28))
        self.assertTrue(any("two requests" in error for error in errors))
        self.assertTrue(any("1800" in error for error in errors))
        self.assertTrue(any("retries" in error for error in errors))

    def test_authentication_remains_viewer_ephemeral_and_non_logging(self):
        plan = copy.deepcopy(self.plan)
        plan["authentication"]["role"] = "administrator"
        plan["authentication"]["token_storage"] = "LOCAL_STORAGE"
        plan["authentication"]["token_or_claim_logging_allowed"] = True
        errors = VALIDATOR.validate_plan(plan, today=date(2026, 8, 28))
        self.assertTrue(any("viewer-only" in error for error in errors))

    def test_abort_and_no_mutation_gates_fail_closed(self):
        plan = copy.deepcopy(self.plan)
        plan["abort_gates"]["abort_on_any_401_or_403"] = False
        plan["abort_gates"]["mutation_routes_allowed"] = True
        errors = VALIDATOR.validate_plan(plan, today=date(2026, 8, 28))
        self.assertTrue(any("abort gates" in error for error in errors))

    def test_baseline_schema_is_aggregate_only_and_has_no_protected_fields(self):
        baseline_schema = json.loads(
            (ROOT / "docs" / "operations_authenticated_read_load_baseline_v1.schema.json")
            .read_text(encoding="utf-8")
        )
        self.assertFalse(baseline_schema["additionalProperties"])
        self.assertEqual(
            set(baseline_schema["properties"]),
            VALIDATOR.BASELINE_TOP_LEVEL_FIELDS,
        )
        self.assertFalse(
            VALIDATOR.PROHIBITED_BASELINE_FIELDS
            & VALIDATOR._property_names(baseline_schema)
        )

    def test_protected_baseline_field_in_schema_fails_closed(self):
        baseline_schema = json.loads(
            (ROOT / "docs" / "operations_authenticated_read_load_baseline_v1.schema.json")
            .read_text(encoding="utf-8")
        )
        baseline_schema["properties"]["summary"]["properties"]["request_id"] = {
            "type": "string"
        }
        errors = VALIDATOR.validate_plan(
            self.plan,
            today=date(2026, 8, 28),
            baseline_schema=baseline_schema,
        )
        self.assertTrue(any("protected raw fields" in error for error in errors))

    def test_renderer_states_zero_requests_and_non_authority(self):
        rendered = VALIDATOR.render_plan(self.plan)
        self.assertIn("Requests executed by this validation: 0", rendered)
        self.assertIn("Production readiness: `false`", rendered)
        self.assertIn("separate named-human authorization", rendered)

    def test_sanitized_aggregate_baseline_reconciles(self):
        self.assertEqual(
            VALIDATOR.validate_baseline(
                self._baseline(), self.plan, today=date(2026, 8, 28)
            ),
            [],
        )

    def test_cli_validates_one_aggregate_baseline_without_echoing_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline_path = Path(directory) / "baseline.json"
            baseline_path.write_text(
                json.dumps(self._baseline()), encoding="utf-8"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "ops" / "validate_operations_authenticated_read_load_plan.py"),
                    "--baseline",
                    str(baseline_path),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "Authenticated read-load aggregate baseline: PASS",
        )

    def test_baseline_raw_field_or_authority_expansion_fails_closed(self):
        baseline = self._baseline()
        baseline["summary"]["request_id"] = "raw"
        baseline["authority"]["operational_mutation_executed"] = True
        errors = VALIDATOR.validate_baseline(
            baseline, self.plan, today=date(2026, 8, 28)
        )
        self.assertTrue(any("protected raw field" in error for error in errors))
        self.assertTrue(any("authority" in error for error in errors))

    def test_baseline_totals_latency_and_abort_state_fail_closed(self):
        baseline = self._baseline()
        baseline["summary"]["responses_2xx"] = 69
        baseline["summary"]["latency_p50_ms"] = 400
        baseline["summary"]["latency_p99_ms"] = 300
        baseline["run_status"] = "ABORTED"
        errors = VALIDATOR.validate_baseline(
            baseline, self.plan, today=date(2026, 8, 28)
        )
        self.assertTrue(any("status totals" in error for error in errors))
        self.assertTrue(any("not monotonic" in error for error in errors))
        self.assertTrue(any("requires a bounded abort reason" in error for error in errors))

    def test_validator_has_no_network_aws_or_subprocess_client(self):
        source = (
            ROOT / "ops" / "validate_operations_authenticated_read_load_plan.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "import boto3",
            "import requests",
            "import subprocess",
            "import socket",
            "import urllib",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
