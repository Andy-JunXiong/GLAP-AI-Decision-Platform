import copy
import importlib.util
import json
import sys
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


robustness = load_module(
    "a303_outcome_robustness_for_tests", "ops/evaluate_a303_outcome_robustness.py"
)


class A303OutcomeRobustnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.simulator = json.loads(
            (ROOT / "docs" / "a303_outcome_simulator_v1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.protocol = json.loads(
            (
                ROOT / "docs" / "a303_outcome_sensitivity_protocol_v1.json"
            ).read_text(encoding="utf-8")
        )
        cls.gate = json.loads(
            (ROOT / "docs" / "a303_synthetic_capability_gate_v1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.bundle = json.loads(
            (ROOT / "blinded-review-survey" / "data" / "review-bundle.json").read_text(
                encoding="utf-8"
            )
        )
        cls.corpus_path = (
            ROOT / "tests" / "fixtures" / "historical_replay" / "corpus_v1.json"
        )
        cls.corpus = json.loads(cls.corpus_path.read_text(encoding="utf-8"))
        corpus_report = robustness._CORPUS.run_corpus(cls.corpus, cls.corpus_path.parent)
        changed = {
            (scenario["scenario_id"], cutoff["cutoff_id"]): cutoff["comparison"][
                "decision_changed"
            ]
            for scenario in corpus_report["scenario_reports"]
            for cutoff in scenario["cutoff_results"]
        }
        split_case = (
            "new-zealand-cyclone-gabrielle-roads-2023-v1",
            "T1_COROMANDEL_HIGHWAY_CLOSURES_CONFIRMED",
        )
        package_summaries = []
        for package in cls.bundle["packages"]:
            scenario = package["scenario"]
            key = (scenario["scenario_id"], scenario["cutoff_id"])
            favors_a303 = changed[key] and key != split_case
            package_summaries.append(
                {
                    "review_id": package["review_id"],
                    "package_digest": package["package_digest"],
                    "review_count": 4,
                    "result": (
                        "REVIEW_EVIDENCE_FAVORS_VARIANT"
                        if favors_a303
                        else "REVIEWERS_DO_NOT_AGREE"
                    ),
                    "favored_variant_id": "glap-a303-on" if favors_a303 else None,
                }
            )
        cls.quality = {
            "schema_version": "decision-quality-corpus-summary.v1",
            "bundle_id": cls.bundle["bundle_id"],
            "bundle_digest": cls.bundle["bundle_digest"],
            "reviewer_count": 4,
            "package_count": 30,
            "package_summaries": package_summaries,
        }
        cls.report = cls.evaluate()

    @classmethod
    def evaluate(cls, *, simulator=None, protocol=None, gate=None, quality=None):
        return robustness.run_robustness(
            cls.simulator if simulator is None else simulator,
            cls.protocol if protocol is None else protocol,
            cls.gate if gate is None else gate,
            cls.quality if quality is None else quality,
            cls.bundle,
            cls.corpus,
            cls.corpus_path.parent,
        )

    def test_all_attributed_changes_and_controls_are_evaluated(self):
        self.assertEqual(
            self.report["coverage"],
            {
                "scenario_count": 10,
                "decision_package_count": 30,
                "attributed_change_count": 16,
                "negative_control_count": 14,
                "parameter_combination_count": 243,
                "central_combination_count": 11,
            },
        )
        self.assertEqual(len(self.report["scenario_stability"]), 16)
        self.assertEqual(len(self.report["decision_flip_boundaries"]), 16)

    def test_human_preference_is_parallel_evidence_not_simulator_eligibility(self):
        self.assertEqual(
            self.report["evaluation_layers"]["decision_quality"]["counts"],
            {"FAVORS_A303_ON": 15, "FAVORS_A303_OFF": 0, "INCONCLUSIVE": 1},
        )
        inconclusive = copy.deepcopy(self.quality)
        for item in inconclusive["package_summaries"]:
            item["result"] = "REVIEWERS_DO_NOT_AGREE"
            item["favored_variant_id"] = None
        report = self.evaluate(quality=inconclusive)
        self.assertEqual(report["coverage"]["attributed_change_count"], 16)
        self.assertEqual(
            report["evaluation_layers"]["decision_quality"]["counts"],
            {"FAVORS_A303_ON": 0, "FAVORS_A303_OFF": 0, "INCONCLUSIVE": 16},
        )

    def test_negative_controls_are_exact_zero_across_the_full_grid(self):
        integrity = self.report["negative_control_integrity"]
        self.assertEqual(integrity["status"], "PASS")
        self.assertEqual(integrity["paired_comparisons_checked"], 14 * 243)
        self.assertEqual(integrity["non_zero_delta_count"], 0)

    def test_frozen_confirmatory_result_is_not_robust(self):
        self.assertEqual(
            self.report["base_case"]["attributed_package_counts"],
            {
                "MODEL_FAVORS_A303_ON": 2,
                "MODEL_FAVORS_A303_OFF": 7,
                "NO_MATERIAL_MODELED_DIFFERENCE": 7,
            },
        )
        self.assertEqual(
            self.report["global_robustness"]["interpretation_counts"],
            {
                "MODEL_FAVORS_A303_ON": 1086,
                "MODEL_FAVORS_A303_OFF": 2340,
                "NO_MATERIAL_MODELED_DIFFERENCE": 462,
            },
        )
        self.assertEqual(
            self.report["global_robustness"]["global_non_negative_pct"], 39.81
        )
        self.assertEqual(
            self.report["capability_gate"]["synthetic_outcome_robustness"],
            "NOT_ROBUST",
        )
        self.assertEqual(
            self.report["capability_gate"]["scenario_stability_counts"],
            {
                "STABLE_POSITIVE": 0,
                "PARAMETER_SENSITIVE": 2,
                "STABLE_NEGATIVE": 14,
            },
        )

    def test_tracked_result_matches_the_reproducible_report(self):
        result = json.loads(
            (
                ROOT / "docs" / "a303_synthetic_outcome_robustness_result_v1.json"
            ).read_text(encoding="utf-8")
        )
        schema = json.loads(
            (
                ROOT
                / "docs"
                / "a303_synthetic_outcome_robustness_result_v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(set(result), set(schema["required"]))
        self.assertEqual(set(result), set(schema["properties"]))
        self.assertEqual(
            result["frozen_inputs"],
            {
                "simulator_sha256": self.report["frozen_inputs"]["simulator_digest"],
                "sensitivity_protocol_sha256": self.report["frozen_inputs"]["sensitivity_protocol_digest"],
                "capability_gate_sha256": self.report["frozen_inputs"]["capability_gate_digest"],
            },
        )
        self.assertEqual(
            result["base_case_simulated_outcome"],
            {
                "model_favors_a303_on": self.report["base_case"]["attributed_package_counts"]["MODEL_FAVORS_A303_ON"],
                "model_favors_a303_off": self.report["base_case"]["attributed_package_counts"]["MODEL_FAVORS_A303_OFF"],
                "no_material_modeled_difference": self.report["base_case"]["attributed_package_counts"]["NO_MATERIAL_MODELED_DIFFERENCE"],
            },
        )
        self.assertEqual(
            result["capability_gate"],
            {
                "synthetic_outcome_robustness": self.report["capability_gate"]["synthetic_outcome_robustness"],
                "real_business_outcome_effect": "NOT_EVALUATED",
            },
        )

    def test_exploratory_selected_run_is_preserved_but_ineligible(self):
        method = json.loads(
            (
                ROOT
                / "docs"
                / "archive"
                / "evaluation"
                / "a303_decision_outcome_method_exploratory_v0.json"
            ).read_text(encoding="utf-8")
        )
        run = json.loads(
            (
                ROOT
                / "docs"
                / "archive"
                / "evaluation"
                / "a303_exploratory_conditional_run_2026-08-22.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(run["method"]["sha256"], robustness.canonical_digest(method))
        self.assertEqual(run["run_classification"], "EXPLORATORY_CONDITIONAL")
        self.assertEqual(
            run["confirmatory_eligibility"], "NOT_ELIGIBLE_FOR_CAPABILITY_GATE"
        )
        self.assertEqual(
            run["result"],
            {
                "model_favors_a303_on": 14,
                "model_favors_a303_off": 0,
                "no_material_modeled_difference": 1,
            },
        )

    def test_nonidentical_negative_control_fails_closed(self):
        drifted_report = robustness._CORPUS.run_corpus(
            self.corpus, self.corpus_path.parent
        )
        changed = False
        for scenario in drifted_report["scenario_reports"]:
            for cutoff in scenario["cutoff_results"]:
                if not cutoff["comparison"]["decision_changed"]:
                    cutoff["variants"][1]["recommendation"] = "RISK_MITIGATION"
                    changed = True
                    break
            if changed:
                break
        with mock.patch.object(robustness._CORPUS, "run_corpus", return_value=drifted_report):
            with self.assertRaisesRegex(
                robustness.RobustnessError, "negative control decisions are not identical"
            ):
                self.evaluate()

    def test_frozen_protocol_digest_mismatch_fails_closed(self):
        protocol = copy.deepcopy(self.protocol)
        protocol["parameters"]["mitigation_incremental_cost_index"]["high"] = 41.0
        with self.assertRaisesRegex(
            robustness.RobustnessError,
            "capability gate does not bind",
        ):
            self.evaluate(protocol=protocol)

    def test_simulator_cannot_regain_human_quality_gate(self):
        simulator = copy.deepcopy(self.simulator)
        simulator["coverage_contract"][
            "human_decision_quality_required_for_simulation"
        ] = True
        with self.assertRaisesRegex(
            robustness.RobustnessError, "coverage contract drifted"
        ):
            self.evaluate(simulator=simulator)

    def test_gate_cannot_gain_production_authority(self):
        gate = copy.deepcopy(self.gate)
        gate["authority"]["model_promotion_authorized"] = True
        with self.assertRaisesRegex(
            robustness.RobustnessError, "authority expanded"
        ):
            self.evaluate(gate=gate)

    def test_report_is_deterministic_private_and_read_only(self):
        second = self.evaluate()
        self.assertEqual(self.report, second)
        rendered = json.dumps(self.report, sort_keys=True)
        self.assertNotIn("reviewer_ref", rendered)
        self.assertNotIn("review_id", rendered)
        self.assertEqual(self.report["operational_mutations"], [])
        self.assertEqual(
            self.report["evaluation_layers"]["business_outcome_effect"][
                "real_business_outcome_effect"
            ],
            "NOT_EVALUATED",
        )

    def test_every_attributed_package_has_five_one_at_a_time_boundaries(self):
        packages_with_flips = 0
        for item in self.report["decision_flip_boundaries"]:
            self.assertEqual(len(item["parameters"]), 5)
            self.assertEqual(
                {entry["parameter"] for entry in item["parameters"]},
                set(robustness.PARAMETER_NAMES),
            )
            self.assertTrue(all(len(entry["points"]) == 3 for entry in item["parameters"]))
            self.assertTrue(
                all("net_positive_condition" in entry for entry in item["parameters"])
            )
            packages_with_flips += any(
                entry["flip_detected"] for entry in item["parameters"]
            )
        self.assertEqual(packages_with_flips, 13)


if __name__ == "__main__":
    unittest.main()
