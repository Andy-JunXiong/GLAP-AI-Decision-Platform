import copy
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


calibration = load_module(
    "a303_outcome_calibration_for_tests", "ops/calibrate_a303_outcome_method.py"
)
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=ZoneInfo("Australia/Sydney"))


class A303OutcomeCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.simulator = json.loads(
            (ROOT / "docs" / "a303_outcome_simulator_v1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.policy = json.loads(
            (ROOT / "docs" / "a303_outcome_calibration_policy_v1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.modeled = {
            "schema_version": "a303-synthetic-outcome-robustness-report.v1",
            "frozen_inputs": {
                "simulator_digest": calibration._canonical_digest(cls.simulator),
            },
            "evaluation_layers": {
                "business_outcome_effect": {
                    "outcome_evidence_class": "SIMULATED_COUNTERFACTUAL",
                    "real_business_outcome_effect": "NOT_EVALUATED",
                }
            },
            "scenario_stability": [
                cls.modeled_package(index) for index in range(1, 4)
            ],
            "operational_mutations": [],
        }

    @staticmethod
    def modeled_package(index):
        return {
            "scenario_id": f"scenario-{index}",
            "cutoff_id": f"T{index}",
            "sla_criticality": "HIGH",
            "base_case_variants": [
                {
                    "variant_id": "baseline-a303-off",
                    "metrics": {
                        "expected_delay_hours": 96.0,
                        "stockout_exposure_days": 1.0,
                        "intervention_cost_index": 0.0,
                    },
                },
                {
                    "variant_id": "glap-a303-on",
                    "metrics": {
                        "expected_delay_hours": 52.8,
                        "stockout_exposure_days": 0.0,
                        "intervention_cost_index": 18.0,
                    },
                },
            ],
        }

    @staticmethod
    def empty_evidence():
        return {
            "schema_version": "a303-outcome-calibration-input.v1",
            "evidence_set_id": "calibration-2026-08",
            "collection_status": "DRAFT",
            "independent_validation_attested": False,
            "observations": [],
            "operational_mutations": [],
        }

    @staticmethod
    def controlled_pair(index):
        return {
            "observation_id": f"controlled-pair-{index}",
            "observation_kind": "CONTROLLED_PAIR",
            "scenario_id": f"scenario-{index}",
            "cutoff_id": f"T{index}",
            "outcome_evidence_class": "PROSPECTIVE_CONTROLLED",
            "time_basis": "ACTUAL_CALENDAR",
            "observed_at": f"2026-08-1{index}T02:00:00+00:00",
            "source_available_at": f"2026-08-1{index}T03:00:00+00:00",
            "source_digest": str(index) * 64,
            "independent_evaluator_attested": True,
            "baseline_metrics": {
                "delay_hours": 96.0,
                "stockout_exposure_days": 1.0,
                "intervention_cost_index": 0.0,
            },
            "a303_metrics": {
                "delay_hours": 52.8,
                "stockout_exposure_days": 0.0,
                "intervention_cost_index": 18.0,
            },
        }

    @staticmethod
    def baseline_observation(index=1):
        return {
            "observation_id": f"baseline-observation-{index}",
            "observation_kind": "BASELINE_OBSERVATION",
            "scenario_id": f"scenario-{index}",
            "cutoff_id": f"T{index}",
            "outcome_evidence_class": "OBSERVED_FACTUAL",
            "time_basis": "ACTUAL_CALENDAR",
            "observed_at": f"2026-08-1{index}T02:00:00+00:00",
            "source_available_at": f"2026-08-1{index}T03:00:00+00:00",
            "source_digest": str(index) * 64,
            "independent_evaluator_attested": True,
            "observed_variant_id": "baseline-a303-off",
            "metrics": {
                "delay_hours": 96.0,
                "stockout_exposure_days": 1.0,
                "intervention_cost_index": 0.0,
            },
        }

    def run_calibration(self, evidence, *, simulator=None, modeled=None, policy=None):
        return calibration.calibrate(
            self.simulator if simulator is None else simulator,
            self.modeled if modeled is None else modeled,
            evidence,
            self.policy if policy is None else policy,
            now=NOW,
        )

    def test_empty_input_reports_blocked_evidence_without_inventing_results(self):
        report = self.run_calibration(self.empty_evidence())
        self.assertEqual(report["readiness"]["status"], "BLOCKED_EVIDENCE")
        self.assertEqual(
            report["readiness"]["blockers"],
            [
                "INSUFFICIENT_BASELINE_OBSERVATIONS",
                "INSUFFICIENT_PROSPECTIVE_CONTROLLED_PAIRS",
            ],
        )
        self.assertIsNone(
            report["calibration_metrics"]["treatment_effect"][
                "treatment_direction_agreement_pct"
            ]
        )
        self.assertEqual(report["operational_mutations"], [])

    def test_three_independent_controlled_pairs_can_pass_declared_checks(self):
        evidence = self.empty_evidence()
        evidence.update(
            {
                "collection_status": "FROZEN",
                "independent_validation_attested": True,
                "observations": [self.controlled_pair(index) for index in range(1, 4)],
            }
        )
        report = self.run_calibration(evidence)
        self.assertEqual(report["readiness"], {"status": "CALIBRATION_CHECKS_PASS", "blockers": []})
        self.assertEqual(
            report["calibration_metrics"]["treatment_effect"][
                "treatment_direction_agreement_pct"
            ],
            100.0,
        )
        rendered = json.dumps(report, sort_keys=True)
        self.assertNotIn("controlled-pair-1", rendered)
        self.assertNotIn("source_digest", rendered)

    def test_observed_factual_record_cannot_claim_controlled_treatment_effect(self):
        evidence = self.empty_evidence()
        pair = self.controlled_pair(1)
        pair["outcome_evidence_class"] = "OBSERVED_FACTUAL"
        evidence.update(
            {
                "collection_status": "FROZEN",
                "independent_validation_attested": True,
                "observations": [pair],
            }
        )
        with self.assertRaisesRegex(calibration.CalibrationError, "ineligible evidence class"):
            self.run_calibration(evidence)

    def test_simulated_record_is_ineligible(self):
        evidence = self.empty_evidence()
        item = self.baseline_observation()
        item["outcome_evidence_class"] = "SIMULATED_COUNTERFACTUAL"
        evidence.update(
            {
                "collection_status": "FROZEN",
                "independent_validation_attested": True,
                "observations": [item],
            }
        )
        with self.assertRaisesRegex(calibration.CalibrationError, "ineligible evidence class"):
            self.run_calibration(evidence)

    def test_future_available_source_fails_temporal_gate(self):
        evidence = self.empty_evidence()
        item = self.baseline_observation()
        item["source_available_at"] = "2026-08-23T00:00:00+10:00"
        evidence.update(
            {
                "collection_status": "FROZEN",
                "independent_validation_attested": True,
                "observations": [item],
            }
        )
        with self.assertRaisesRegex(calibration.CalibrationError, "future-dated"):
            self.run_calibration(evidence)

    def test_nonempty_draft_is_not_eligible_evidence(self):
        evidence = self.empty_evidence()
        evidence["observations"] = [self.baseline_observation()]
        with self.assertRaisesRegex(calibration.CalibrationError, "frozen and independently attested"):
            self.run_calibration(evidence)

    def test_modeled_report_must_match_frozen_simulator_digest(self):
        modeled = copy.deepcopy(self.modeled)
        modeled["frozen_inputs"]["simulator_digest"] = "0" * 64
        with self.assertRaisesRegex(calibration.CalibrationError, "does not match"):
            self.run_calibration(self.empty_evidence(), modeled=modeled)

    def test_policy_cannot_gain_model_promotion_authority(self):
        policy = copy.deepcopy(self.policy)
        policy["authority"]["model_promotion_allowed"] = True
        with self.assertRaisesRegex(calibration.CalibrationError, "cannot gain"):
            self.run_calibration(self.empty_evidence(), policy=policy)

    def test_report_shape_matches_versioned_schema(self):
        report = self.run_calibration(self.empty_evidence())
        schema = json.loads(
            (
                ROOT / "docs" / "a303_outcome_calibration_report_v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(set(report), set(schema["required"]))
        self.assertEqual(set(report), set(schema["properties"]))


if __name__ == "__main__":
    unittest.main()
