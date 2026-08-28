import copy
from datetime import date
import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "evaluate_operations_production_readiness",
    ROOT / "ops" / "evaluate_operations_production_readiness.py",
)
EVALUATOR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = EVALUATOR
SPEC.loader.exec_module(EVALUATOR)


class OperationsProductionReadinessTests(unittest.TestCase):
    def setUp(self):
        self.evidence = EVALUATOR.load_evidence()

    def test_repository_evidence_is_valid_and_not_ready(self):
        self.assertEqual(
            EVALUATOR.validate_evidence(
                self.evidence, today=date(2026, 8, 28)
            ),
            [],
        )
        report = EVALUATOR.build_report(self.evidence)
        self.assertEqual(report["status"], "NOT_READY_INCOMPLETE_EVIDENCE")
        self.assertEqual(report["summary"]["eligible_gate_count"], 4)
        self.assertEqual(report["summary"]["blocked_gate_count"], 6)
        self.assertFalse(report["summary"]["production_readiness"])

    def test_schema_is_valid_json_and_requires_all_false_authority(self):
        schema = json.loads(
            (ROOT / "docs" / "operations_production_readiness_evidence_v1.schema.json")
            .read_text(encoding="utf-8")
        )
        properties = schema["properties"]["authority"]["properties"]
        self.assertEqual(set(properties), EVALUATOR.AUTHORITY_FIELDS)
        self.assertTrue(all(value == {"const": False} for value in properties.values()))

    def test_production_or_external_write_authority_fails_closed(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["authority"]["production_deployment_authorized"] = True
        evidence["execution"]["external_writes_executed"] = True
        errors = EVALUATOR.validate_evidence(evidence, today=date(2026, 8, 28))
        self.assertTrue(any("production_deployment_authorized" in error for error in errors))
        self.assertTrue(any("external_writes_executed" in error for error in errors))

    def test_partial_gate_cannot_be_counted_as_runtime_verified(self):
        evidence = copy.deepcopy(self.evidence)
        gate = next(
            gate for gate in evidence["required_gates"]
            if gate["id"] == "security_negative_suite"
        )
        gate["state"] = "RUNTIME_VERIFIED_STAGING"
        errors = EVALUATOR.validate_evidence(evidence, today=date(2026, 8, 28))
        self.assertTrue(any("summary does not match" in error for error in errors))

    def test_not_executed_gate_cannot_claim_runtime_evidence(self):
        evidence = copy.deepcopy(self.evidence)
        gate = next(
            gate for gate in evidence["required_gates"]
            if gate["id"] == "athena_query_cost_baseline"
        )
        gate["evidence_class"] = "STAGING_ENGINEERING"
        errors = EVALUATOR.validate_evidence(evidence, today=date(2026, 8, 28))
        self.assertTrue(any("must use NONE" in error for error in errors))

    def test_sustained_read_load_is_partial_but_not_runtime_verified(self):
        gate = next(
            gate for gate in self.evidence["required_gates"]
            if gate["id"] == "sustained_read_load"
        )
        self.assertEqual(gate["state"], "PARTIAL_EVIDENCE")
        self.assertEqual(gate["evidence_class"], "STAGING_ENGINEERING")
        self.assertIn(
            "docs/operations_authenticated_read_load_plan_v1.json",
            gate["evidence_refs"],
        )
        self.assertIn(
            "ops/run_operations_authenticated_read_load_staging.ps1",
            gate["evidence_refs"],
        )
        self.assertIn("20 of 20 responses were successful", gate["finding"])
        self.assertIn("p95 latency was 6177 ms", gate["finding"])
        self.assertIn("temporary viewer was confirmed removed", gate["finding"])

    def test_future_as_of_date_fails_closed(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["as_of_date"] = "2026-08-29"
        errors = EVALUATOR.validate_evidence(evidence, today=date(2026, 8, 28))
        self.assertTrue(any("current Sydney date" in error for error in errors))

    def test_required_gate_inventory_is_exact(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["required_gates"].pop()
        errors = EVALUATOR.validate_evidence(evidence, today=date(2026, 8, 28))
        self.assertTrue(any("gate inventory" in error for error in errors))

    def test_malformed_nested_shapes_fail_closed_without_exception(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["execution"] = []
        evidence["authority"] = "production"
        evidence["required_gates"][0] = "verified"
        evidence["claim_boundary"] = None
        errors = EVALUATOR.validate_evidence(evidence, today=date(2026, 8, 28))
        self.assertTrue(any("execution must be an object" in error for error in errors))
        self.assertTrue(any("authority must be an object" in error for error in errors))
        self.assertTrue(any("every gate must be an object" in error for error in errors))
        self.assertTrue(any("claim boundary must be an object" in error for error in errors))

    def test_report_is_aggregate_and_excludes_evidence_references(self):
        report = EVALUATOR.build_report(self.evidence)
        encoded = json.dumps(report)
        self.assertNotIn("evidence_refs", encoded)
        self.assertNotIn("query_id", encoded)
        self.assertNotIn("actor", encoded)
        self.assertNotIn("arn", encoded.lower())
        self.assertFalse(report["execution"]["network_access"])
        self.assertFalse(report["execution"]["external_writes_executed"])

    def test_protected_finding_and_unexpected_field_fail_closed(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["required_gates"][0]["finding"] = "account 123456789012"
        evidence["required_gates"][0]["raw_identity"] = "hidden"
        errors = EVALUATOR.validate_evidence(evidence, today=date(2026, 8, 28))
        self.assertTrue(any("protected identifier" in error for error in errors))
        self.assertTrue(any("field inventory" in error for error in errors))

    def test_evaluator_has_no_network_aws_or_subprocess_client(self):
        source = (ROOT / "ops" / "evaluate_operations_production_readiness.py").read_text(
            encoding="utf-8"
        )
        for forbidden in ("import boto3", "import requests", "import subprocess", "import socket", "import urllib"):
            self.assertNotIn(forbidden, source)

    def test_markdown_states_the_non_authority_boundary(self):
        rendered = EVALUATOR.render_markdown(EVALUATOR.build_report(self.evidence))
        self.assertIn("Eligible gates: 4/10", rendered)
        self.assertIn("Production readiness: `false`", rendered)
        self.assertIn("executed no network request or external write", rendered)


if __name__ == "__main__":
    unittest.main()
