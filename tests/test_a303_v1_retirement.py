import copy
import importlib.util
import json
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


retirement = load_module(
    "a303_v1_retirement_for_tests", "ops/validate_a303_v1_retirement.py"
)


class A303V1RetirementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.decision = json.loads(
            (ROOT / "docs" / "a303_v1_retirement_decision.json").read_text(
                encoding="utf-8"
            )
        )
        cls.robustness = json.loads(
            (
                ROOT / "docs" / "a303_synthetic_outcome_robustness_result_v1.json"
            ).read_text(encoding="utf-8")
        )
        cls.guardrail = json.loads(
            (
                ROOT / "docs" / "a303_v2_guardrail_development_result_v1.json"
            ).read_text(encoding="utf-8")
        )

    def validate(self, decision=None, robustness=None, guardrail=None):
        return retirement.validate_retirement(
            self.decision if decision is None else decision,
            self.robustness if robustness is None else robustness,
            self.guardrail if guardrail is None else guardrail,
        )

    def test_repository_records_human_retirement_without_mutation(self):
        report = self.validate()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["decision"], "RETIRE_A303_V1_FROM_PROGRESSION")
        self.assertEqual(report["development_status"], "RETIRED_FROM_PROGRESSION")
        self.assertEqual(report["evidence_history"], "PRESERVED_READ_ONLY")
        self.assertEqual(report["operational_mutations"], [])

    def test_evidence_result_digest_drift_fails_closed(self):
        robustness = copy.deepcopy(self.robustness)
        robustness["capability_gate"]["synthetic_outcome_robustness"] = "ROBUST"
        with self.assertRaisesRegex(retirement.RetirementDecisionError, "digest"):
            self.validate(robustness=robustness)

    def test_a303_v1_cannot_be_reactivated_by_contract_drift(self):
        decision = copy.deepcopy(self.decision)
        decision["reopening_rule"]["a303_v1_may_be_reactivated"] = True
        with self.assertRaisesRegex(retirement.RetirementDecisionError, "reopening"):
            self.validate(decision=decision)

    def test_retirement_cannot_gain_production_authority(self):
        decision = copy.deepcopy(self.decision)
        decision["authority_boundary"]["production_change_authorized"] = True
        with self.assertRaisesRegex(retirement.RetirementDecisionError, "authority"):
            self.validate(decision=decision)

    def test_retirement_cannot_delete_review_evidence(self):
        decision = copy.deepcopy(self.decision)
        decision["scope"]["does_not_delete_or_rewrite"].remove(
            "ORIGINAL_REVIEW_SUBMISSIONS"
        )
        with self.assertRaisesRegex(retirement.RetirementDecisionError, "preservation"):
            self.validate(decision=decision)

    def test_decision_shape_matches_versioned_schema(self):
        schema = json.loads(
            (
                ROOT / "docs" / "a303_v1_retirement_decision.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(set(self.decision), set(schema["required"]))
        self.assertEqual(set(self.decision), set(schema["properties"]))


if __name__ == "__main__":
    unittest.main()
