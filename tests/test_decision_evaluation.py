import copy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "decision_evaluation", ROOT / "ops" / "evaluate_decision_capabilities.py"
)
evaluation = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(evaluation)
FIXTURE = ROOT / "tests" / "fixtures" / "evaluation" / "a303_high_risk_route_v1.json"


def manifest():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class DecisionEvaluationTests(unittest.TestCase):
    def test_schema_declares_the_frozen_v1_boundary(self):
        schema = json.loads(
            (ROOT / "docs" / "evaluation_experiment_v1.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(schema["properties"]["schema_version"]["const"], "evaluation-experiment.v1")
        boundary = schema["properties"]["execution_boundary"]["properties"]
        self.assertFalse(boundary["operational_writes_allowed"]["const"])
        self.assertFalse(boundary["production_effect"]["const"])

    def test_a303_is_the_only_difference_and_is_attributed(self):
        report = evaluation.run_experiment(manifest())
        decisions = {item["role"]: item["decision"] for item in report["variants"]}
        self.assertEqual(decisions["BASELINE"]["recommendation"], "MONITOR")
        self.assertEqual(decisions["CHALLENGER"]["recommendation"], "RISK_MITIGATION")
        self.assertEqual(report["comparison"]["attribution"], "ATTRIBUTED_TO_A303_HIGH_RISK_ROUTE")
        self.assertEqual(report["evaluation_layers"]["capability_attribution"]["status"], "PASS")

    def test_post_cutoff_evidence_is_not_visible_to_either_variant(self):
        report = evaluation.run_experiment(manifest())
        self.assertEqual(report["evidence_window"]["visible_evidence_ids"], ["signal-a303-high-v1"])
        self.assertEqual(report["evidence_window"]["post_cutoff_evidence_ids"], ["post-cutoff-recovery-v1"])
        for variant in report["variants"]:
            self.assertNotIn("post-cutoff-recovery-v1", variant["trace"]["visible_evidence_ids"])

    def test_run_is_deterministic_and_has_no_operational_mutation(self):
        first = evaluation.run_experiment(manifest())
        second = evaluation.run_experiment(manifest())
        self.assertEqual(first, second)
        self.assertEqual(first["operational_mutations"], [])
        self.assertTrue(all(item["operational_mutations"] == [] for item in first["variants"]))
        self.assertEqual(first["evaluation_layers"]["system_correctness"]["status"], "PASS")

    def test_quality_and_business_effect_are_not_inferred_from_decision_delta(self):
        report = evaluation.run_experiment(manifest())
        self.assertEqual(report["evaluation_layers"]["decision_quality"]["status"], "NOT_EVALUATED")
        self.assertEqual(report["evaluation_layers"]["business_outcome_effect"]["status"], "NOT_EVALUATED")
        self.assertIn("BUSINESS_OUTCOME_IMPROVEMENT", report["claim_boundary"]["not_supported"])

    def test_manifest_fails_closed_if_operational_writes_are_enabled(self):
        changed = copy.deepcopy(manifest())
        changed["execution_boundary"]["operational_writes_allowed"] = True
        with self.assertRaisesRegex(evaluation.ContractError, "operational_writes_allowed must be false"):
            evaluation.run_experiment(changed)

    def test_manifest_fails_closed_if_another_capability_varies(self):
        changed = copy.deepcopy(manifest())
        changed["variants"][1]["capabilities"]["EXTERNAL_EVIDENCE"] = True
        with self.assertRaisesRegex(evaluation.ContractError, "only A303 may vary"):
            evaluation.run_experiment(changed)


if __name__ == "__main__":
    unittest.main()
