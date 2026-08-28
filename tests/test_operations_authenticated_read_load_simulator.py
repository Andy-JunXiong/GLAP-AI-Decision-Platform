import copy
import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "simulate_operations_authenticated_read_load",
    ROOT / "ops" / "simulate_operations_authenticated_read_load.py",
)
SIMULATOR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = SIMULATOR
SPEC.loader.exec_module(SIMULATOR)


class OperationsAuthenticatedReadLoadSimulatorTests(unittest.TestCase):
    def setUp(self):
        self.plan = SIMULATOR.CONTRACT.load_plan()

    def test_schedule_is_deterministic_bounded_and_paced(self):
        first = SIMULATOR.build_request_schedule(self.plan)
        second = SIMULATOR.build_request_schedule(self.plan)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 1740)
        self.assertLessEqual(len(first), self.plan["load_shape"]["max_total_requests"])
        self.assertEqual(first[0]["offset_ms"], 0)
        self.assertEqual(first[59]["offset_ms"], 59000)
        self.assertEqual(first[60]["offset_ms"], 60000)
        self.assertEqual(first[61]["offset_ms"], 60500)
        self.assertEqual(first[-1]["offset_ms"], 899500)

    def test_weighted_cycle_reconciles_exactly(self):
        cycle = SIMULATOR._weighted_route_cycle(self.plan)
        self.assertEqual(len(cycle), 100)
        for route in self.plan["routes"]:
            self.assertEqual(cycle.count(route["id"]), route["weight_pct"])

    def test_healthy_scenario_completes_without_runtime_claim(self):
        report = SIMULATOR.simulate_scenario(self.plan, "healthy")
        self.assertEqual(report["result"]["run_status"], "COMPLETED")
        self.assertEqual(
            report["result"]["requests_completed"],
            report["schedule"]["scheduled_requests"],
        )
        self.assertTrue(report["result"]["candidate_baseline_valid"])
        self.assertFalse(report["execution"]["network_access"])
        self.assertFalse(report["execution"]["staging_requests_executed"])
        self.assertFalse(report["claim_boundary"]["staging_runtime_evidence"])

    def test_authorization_failure_aborts_on_first_simulated_response(self):
        report = SIMULATOR.simulate_scenario(self.plan, "authorization_failure")
        self.assertEqual(report["result"]["requests_completed"], 1)
        self.assertEqual(report["result"]["responses_other_4xx"], 1)
        self.assertEqual(report["result"]["abort_reason_code"], "AUTHORIZATION_FAILURE")

    def test_throttle_rate_breach_aborts_after_minimum_window(self):
        report = SIMULATOR.simulate_scenario(self.plan, "throttle_breach")
        self.assertEqual(report["result"]["requests_completed"], 20)
        self.assertEqual(report["result"]["responses_429"], 2)
        self.assertEqual(report["result"]["abort_reason_code"], "THROTTLE_RATE_EXCEEDED")

    def test_server_error_rate_breach_aborts_after_minimum_window(self):
        report = SIMULATOR.simulate_scenario(self.plan, "server_error_breach")
        self.assertEqual(report["result"]["requests_completed"], 20)
        self.assertEqual(report["result"]["responses_5xx"], 1)
        self.assertEqual(report["result"]["abort_reason_code"], "SERVER_ERROR_RATE_EXCEEDED")

    def test_latency_breach_aborts_after_minimum_window(self):
        report = SIMULATOR.simulate_scenario(self.plan, "latency_breach")
        self.assertEqual(report["result"]["requests_completed"], 20)
        self.assertGreater(report["result"]["latency_p95_ms"], 3000)
        self.assertEqual(report["result"]["abort_reason_code"], "P95_LATENCY_EXCEEDED")

    def test_consecutive_failures_abort_before_rate_window(self):
        report = SIMULATOR.simulate_scenario(self.plan, "consecutive_failures")
        self.assertEqual(report["result"]["requests_completed"], 5)
        self.assertEqual(report["result"]["responses_5xx"], 5)
        self.assertEqual(
            report["result"]["abort_reason_code"],
            "CONSECUTIVE_FAILURES_EXCEEDED",
        )

    def test_route_and_method_drift_abort_before_simulated_response(self):
        for scenario, reason in (
            ("non_allowlisted_route", "NON_ALLOWLISTED_ROUTE"),
            ("unexpected_http_method", "UNEXPECTED_HTTP_METHOD"),
        ):
            with self.subTest(scenario=scenario):
                report = SIMULATOR.simulate_scenario(self.plan, scenario)
                self.assertEqual(report["result"]["requests_attempted"], 1)
                self.assertEqual(report["result"]["requests_completed"], 0)
                self.assertEqual(report["result"]["abort_reason_code"], reason)

    def test_identity_cleanup_failure_fails_closed_after_aggregation(self):
        report = SIMULATOR.simulate_scenario(self.plan, "identity_cleanup_failure")
        self.assertEqual(report["result"]["run_status"], "FAILED_CLOSED")
        self.assertEqual(report["result"]["abort_reason_code"], "IDENTITY_CLEANUP_FAILED")
        self.assertTrue(report["result"]["candidate_baseline_valid"])

    def test_reconciliation_failure_withholds_baseline_evidence(self):
        report = SIMULATOR.simulate_scenario(self.plan, "reconciliation_failure")
        self.assertEqual(report["result"]["run_status"], "FAILED_CLOSED")
        self.assertEqual(
            report["result"]["abort_reason_code"],
            "RESULT_RECONCILIATION_FAILED",
        )
        self.assertFalse(report["result"]["candidate_baseline_valid"])
        self.assertFalse(report["claim_boundary"]["staging_runtime_evidence"])

    def test_report_validator_rejects_raw_field_and_authority_expansion(self):
        report = SIMULATOR.simulate_scenario(self.plan, "healthy")
        report["result"]["request_id"] = "raw"
        report["authority"]["staging_load_run_authorized"] = True
        errors = SIMULATOR.validate_simulation_report(report, self.plan)
        self.assertTrue(any("protected raw field" in error for error in errors))
        self.assertTrue(any("authority" in error for error in errors))

    def test_report_validator_rejects_count_and_latency_drift(self):
        report = SIMULATOR.simulate_scenario(self.plan, "healthy")
        report["result"]["responses_2xx"] -= 1
        report["result"]["latency_p50_ms"] = report["result"]["latency_p99_ms"] + 1
        errors = SIMULATOR.validate_simulation_report(report, self.plan)
        self.assertTrue(any("response totals" in error for error in errors))
        self.assertTrue(any("not monotonic" in error for error in errors))

    def test_renderer_labels_repository_simulation_and_zero_staging_requests(self):
        rendered = SIMULATOR.render_markdown(
            SIMULATOR.simulate_scenario(self.plan, "healthy")
        )
        self.assertIn("REPOSITORY_ENGINEERING_SIMULATION", rendered)
        self.assertIn("Staging requests executed: `false`", rendered)
        self.assertIn("not staging runtime evidence", rendered)

    def test_simulator_has_no_network_wait_aws_or_subprocess_client(self):
        source = (
            ROOT / "ops" / "simulate_operations_authenticated_read_load.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "import boto3",
            "import requests",
            "import subprocess",
            "import socket",
            "import urllib",
            "import time",
            "sleep(",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
